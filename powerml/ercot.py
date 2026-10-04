"""ERCOT data: hourly day-ahead hub prices from ERCOT itself, hourly fundamentals from EIA-930.

EIA's ICE price files stopped carrying ERCOT after 2018, so prices come straight from ERCOT's
public market reports (report NP4-180-ER, "Historical DAM Load Zone and Hub Prices"): one zip
per year, one Excel sheet per month, one row per hour per settlement point. No login needed.

Unlike the other hubs in this project, these prices are HOURLY, which is what makes intraday
questions (when in the day is power scarce? are batteries flattening the evening peak?) testable.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import pandas as pd
import requests

from .config import CACHE, EIA930_FIRST_DAY, RAW
from .data import eia_api

LIST_URL = "https://www.ercot.com/misapp/GetReports.do?reportTypeId=13060"
FILE_URL = "https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={}"
HEADERS = {"User-Agent": "Mozilla/5.0 (power-market-ml research)"}
HUBS = ("HB_NORTH", "HB_HOUSTON", "HB_SOUTH", "HB_WEST", "HB_PAN", "HB_HUBAVG")


def _yearly_doc_ids() -> dict[int, str]:
    html = requests.get(LIST_URL, headers=HEADERS, timeout=60).text
    ids = {}
    for name, doc in re.findall(r"DAMLZHBSPP_(\d{4})\.zip.*?doclookupId=(\d+)", html, flags=re.S):
        ids.setdefault(int(name), doc)          # listing is newest-first; keep the latest file per year
    if not ids:  # the link sometimes precedes the file name in the row
        for doc, name in re.findall(r"doclookupId=(\d+).*?DAMLZHBSPP_(\d{4})\.zip", html, flags=re.S):
            ids.setdefault(int(name), doc)
    return ids


def _parse_year(content: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(content))
    sheets = pd.read_excel(z.open(z.namelist()[0]), sheet_name=None)
    df = pd.concat(sheets.values(), ignore_index=True)
    df.columns = ["date", "hour", "repeated", "point", "price"]
    df = df[df["point"].isin(HUBS) & (df["repeated"] != "Y")]   # drop the duplicate hour at DST fall-back
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    df["he"] = df["hour"].str.slice(0, 2).astype(int)           # hour ending 1..24, Central prevailing time
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df[["date", "he", "point", "price"]]


def dam_hub_prices(first_year: int = 2019, refresh: bool = False) -> pd.DataFrame:
    """Hourly day-ahead settlement point prices ($/MWh) for ERCOT's trading hubs, long format."""
    frames, ids = [], None
    for year in range(first_year, date.today().year + 1):
        path = CACHE / f"ercot_dam_{year}.parquet"
        current = year == date.today().year
        if path.exists() and not (refresh or current):
            frames.append(pd.read_parquet(path))
            continue
        ids = ids or _yearly_doc_ids()
        if year not in ids:
            continue
        r = requests.get(FILE_URL.format(ids[year]), headers=HEADERS, timeout=300)
        r.raise_for_status()
        (RAW / f"ercot_dam_{year}.zip").write_bytes(r.content)
        df = _parse_year(r.content)
        df.to_parquet(path, index=False)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["price"] = pd.to_numeric(out["price"], errors="coerce")   # older cached years stored text
    return out


# --------------------------------------------------------------------------- EIA-930, local hours
def _hourly(route: str, facets: dict, name: str, refresh: bool) -> pd.DataFrame:
    """EIA-930 hourly series for ERCOT (UTC hour-ending periods), cached."""
    path = CACHE / f"eia930_ERCO_{name}_hourly.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    d = eia_api(route, facets, f"{EIA930_FIRST_DAY}T00", f"{date.today().isoformat()}T00", frequency="hourly")
    key = "fueltype" if "fueltype" in d.columns else "type"
    d = d[["period", key, "value"]].rename(columns={key: "series"})
    d.to_parquet(path, index=False)
    return d


def hourly_fundamentals(refresh: bool = False) -> pd.DataFrame:
    """Wide hourly ERCOT table: demand, solar, wind, gas and storage (MW), by local date and hour ending."""
    gen = _hourly("electricity/rto/fuel-type-data",
                  {"respondent": ["ERCO"], "fueltype": ["SUN", "WND", "NG", "OTH", "BAT"]}, "fuel", refresh)
    dem = _hourly("electricity/rto/region-data", {"respondent": ["ERCO"], "type": ["D"]}, "demand", refresh)
    d = pd.concat([gen, dem.assign(series="D")])
    # EIA-930 periods are UTC and mark the END of the hour, the same convention as ERCOT's
    # "hour ending". Step back one hour to the hour's start, convert to Central time, and the
    # local date plus (start hour + 1) is ERCOT's delivery date and hour ending.
    start = (d["period"] - pd.Timedelta("1h")).dt.tz_localize("UTC").dt.tz_convert("US/Central").dt.tz_localize(None)
    d = d.assign(date=start.dt.normalize(), he=start.dt.hour + 1)
    wide = d.pivot_table(index=["date", "he"], columns="series", values="value", aggfunc="mean").reset_index()
    wide = wide.rename(columns={"D": "demand", "SUN": "solar", "WND": "wind", "NG": "gas_gen",
                                "OTH": "other", "BAT": "battery"})
    for c in ("solar", "wind", "battery", "other"):
        if c not in wide:
            wide[c] = 0.0
    wide[["solar", "wind"]] = wide[["solar", "wind"]].fillna(0.0)
    wide["net_load"] = wide["demand"] - wide["solar"] - wide["wind"]
    return wide


MIDDAY = range(10, 16)     # HE10-15: solar at full output
EVENING = range(19, 23)    # HE19-22: sun down, load still high - the net-load peak


def battery_fleet(f: pd.DataFrame) -> pd.DataFrame:
    """Daily ERCOT storage fleet proxy (GW) from hourly EIA-930 'Other' + 'Battery'.

    Until late 2024 ERCOT batteries show up only as evening DISCHARGE inside 'Other' (charging is
    netted into load), and from Nov 2024 they get their own BAT series that also shows charging.
    Evening discharge is visible under both regimes, so the proxy uses that: the day's peak
    storage output above the overnight baseline, then the trailing 90-day 95th percentile,
    shifted a day so it measures fleet capability rather than reacting to today's prices.
    """
    s = f.assign(stor=f["other"].fillna(0) + f["battery"].fillna(0))
    base = s[s["he"].between(1, 5)].groupby("date")["stor"].median().clip(lower=0)
    peak = s[s["he"].isin(range(17, 24))].groupby("date")["stor"].max()
    out = pd.DataFrame({"batt_peak_gw": (peak - base).clip(lower=0) / 1000})
    out["batt_fleet_gw"] = out["batt_peak_gw"].shift(1).rolling(90, min_periods=30).quantile(0.95)
    return out.reset_index()


def daily_panel(hub: str = "HB_HUBAVG", gas: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per ERCOT delivery day: price shape, load and net-load shape, solar, storage, gas."""
    from .data import henry_hub

    p = dam_hub_prices()
    p = p[p["point"] == hub]
    f = hourly_fundamentals()
    h = p.merge(f, on=["date", "he"], how="inner")

    def at_max(g, col):
        return g.loc[g[col].idxmax(), "he"]

    g = h.groupby("date")
    day = pd.DataFrame({
        "price_mean": g["price"].mean(),
        "price_max": g["price"].max(),
        "he_price_max": g.apply(lambda x: at_max(x, "price"), include_groups=False),
        "price_mid": h[h["he"].isin(MIDDAY)].groupby("date")["price"].mean(),
        "price_eve": h[h["he"].isin(EVENING)].groupby("date")["price"].mean(),
        "load_peak_gw": g["demand"].max() / 1000,
        "he_load_peak": g.apply(lambda x: at_max(x, "demand"), include_groups=False),
        "netload_peak_gw": g["net_load"].max() / 1000,
        "he_netload_peak": g.apply(lambda x: at_max(x, "net_load"), include_groups=False),
        "netload_mid_min_gw": h[h["he"].isin(range(9, 17))].groupby("date")["net_load"].min() / 1000,
        "netload_eve_max_gw": h[h["he"].isin(range(17, 24))].groupby("date")["net_load"].max() / 1000,
        "solar_share": g["solar"].sum() / g["demand"].sum(),
        "wind_share": g["wind"].sum() / g["demand"].sum(),
        "hours": g.size(),
    }).reset_index()
    day = day[day["hours"] >= 23]                                    # skip days with missing hours
    day["ramp_gw"] = day["netload_eve_max_gw"] - day["netload_mid_min_gw"]
    day = day.merge(battery_fleet(f), on="date", how="left")

    # Day-ahead trades the day before delivery, so pair each day with gas from the prior trading day.
    gas = henry_hub() if gas is None else gas
    day["trade_date"] = day["date"] - pd.Timedelta("1D")
    day = pd.merge_asof(day.sort_values("trade_date"), gas.sort_values("trade_date"), on="trade_date",
                        direction="backward", tolerance=pd.Timedelta("5D")).sort_values("date")
    day["year"] = day["date"].dt.year
    day["month"] = day["date"].dt.month
    day["dow"] = day["date"].dt.dayofweek
    day["trend_yrs"] = (day["date"] - pd.Timestamp("2019-01-01")).dt.days / 365.25
    # Winter Storm Uri (Feb 2021) hit the $9,000 cap for days; it is a different regime entirely.
    day["uri"] = day["date"].between("2021-02-10", "2021-02-20")
    return day[day["year"] >= 2019].reset_index(drop=True)
