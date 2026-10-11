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

from .config import CACHE, RAW
from .data import hourly_grid

LIST_URL = "https://www.ercot.com/misapp/GetReports.do?reportTypeId={}"
FILE_URL = "https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={}"
HEADERS = {"User-Agent": "Mozilla/5.0 (power-market-ml research)"}
HUBS = ("HB_NORTH", "HB_HOUSTON", "HB_SOUTH", "HB_WEST", "HB_PAN", "HB_HUBAVG")

# ERCOT's public yearly archives used here: (report type ID, file-name tag)
REPORTS = {
    "dam": (13060, "DAMLZHBSPP"),   # day-ahead hub & load-zone prices, hourly
    "rtm": (13061, "RTMLZHBSPP"),   # real-time hub & load-zone prices, 15-minute
    "as": (13091, "DAMASMCPC"),     # day-ahead ancillary-service clearing prices, hourly
}


def _yearly_doc_ids(kind: str = "dam") -> dict[int, str]:
    """Map each year to the document ID of that report's yearly file, read from ERCOT's report page.

    ERCOT links files by numeric ID, not by name, and the IDs change every year. Reading the
    listing page with a regular expression means new years are picked up automatically.
    """
    report_id, tag = REPORTS[kind]
    html = requests.get(LIST_URL.format(report_id), headers=HEADERS, timeout=60).text
    ids = {}
    for name, doc in re.findall(tag + r"_(\d{4})\.zip.*?doclookupId=(\d+)", html, flags=re.S):
        ids.setdefault(int(name), doc)          # listing is newest-first; keep the latest file per year
    if not ids:  # the link sometimes precedes the file name in the row
        for doc, name in re.findall(r"doclookupId=(\d+).*?" + tag + r"_(\d{4})\.zip", html, flags=re.S):
            ids.setdefault(int(name), doc)
    return ids


def _read_member(content: bytes) -> pd.DataFrame:
    """Read the single file inside an ERCOT zip: a workbook (one sheet per month) or a CSV."""
    z = zipfile.ZipFile(io.BytesIO(content))
    name = z.namelist()[0]
    if name.lower().endswith(".csv"):
        return pd.read_csv(z.open(name))
    # sheet_name=None returns {sheet name: table}; concat stacks Jan-Dec together.
    sheets = pd.read_excel(z.open(name), sheet_name=None, header=None)
    frames = []
    for raw in sheets.values():
        # Some workbooks put title rows above the real header. Use the row that starts with
        # "Delivery Date" as the header and keep everything below it.
        hits = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Delivery Date"]
        if len(hits) == 0:
            continue
        body = raw.iloc[hits[0] + 1:].copy()
        body.columns = [str(c).strip() for c in raw.iloc[hits[0]]]
        frames.append(body)
    return pd.concat(frames, ignore_index=True)


def _yearly(kind: str, parse, first_year: int, refresh: bool) -> pd.DataFrame:
    """Download, parse and cache one ERCOT report year by year.

    Past years never change, so they're read from the cache. The current year is still
    growing, so it is re-downloaded on every run.
    """
    frames, ids = [], None
    for year in range(first_year, date.today().year + 1):
        path = CACHE / f"ercot_{kind}_{year}.parquet"
        current = year == date.today().year
        if path.exists() and not (refresh or current):
            frames.append(pd.read_parquet(path))
            continue
        ids = ids or _yearly_doc_ids(kind)
        if year not in ids:
            continue
        r = requests.get(FILE_URL.format(ids[year]), headers=HEADERS, timeout=600)
        r.raise_for_status()
        (RAW / f"ercot_{kind}_{year}.zip").write_bytes(r.content)
        df = parse(_read_member(r.content))
        df.to_parquet(path, index=False)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _parse_dam(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = ["date", "hour", "repeated", "point", "price"]
    df = df[df["point"].isin(HUBS) & (df["repeated"] != "Y")]   # drop the duplicate hour at DST fall-back
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    df["he"] = df["hour"].str.slice(0, 2).astype(int)           # hour ending 1..24, Central prevailing time
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df[["date", "he", "point", "price"]]


def _parse_rtm(df: pd.DataFrame) -> pd.DataFrame:
    # Real-time prices settle every 15 minutes (4 intervals per hour). Average them to hourly so
    # they line up one-to-one with day-ahead prices.
    df.columns = ["date", "he", "interval", "repeated", "point", "type", "price"]
    df = df[df["point"].isin(HUBS) & (df["repeated"] != "Y")].copy()
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    df["he"] = df["he"].astype(int)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df.groupby(["date", "he", "point"], as_index=False)["price"].mean()


def _parse_as(df: pd.DataFrame) -> pd.DataFrame:
    # One row per hour, one column per ancillary service ($/MW per hour of standby capacity).
    # ECRS only exists from June 2023, so earlier years simply lack that column.
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df[df["repeated hour flag"] != "Y"].copy()
    out = pd.DataFrame({"date": pd.to_datetime(df["delivery date"], format="%m/%d/%Y"),
                        "he": df["hour ending"].astype(str).str.slice(0, 2).astype(int)})
    for c in ("regup", "regdn", "rrs", "nspin", "ecrs"):
        out[c] = pd.to_numeric(df[c], errors="coerce") if c in df else float("nan")
    return out


def dam_hub_prices(first_year: int = 2019, refresh: bool = False) -> pd.DataFrame:
    """Hourly day-ahead settlement point prices ($/MWh) for ERCOT's trading hubs, long format."""
    out = _yearly("dam", _parse_dam, first_year, refresh)
    out["price"] = pd.to_numeric(out["price"], errors="coerce")   # older cached years stored text
    return out


def rtm_hub_prices(first_year: int = 2019, refresh: bool = False) -> pd.DataFrame:
    """Hourly-averaged real-time settlement point prices ($/MWh) for ERCOT's trading hubs."""
    return _yearly("rtm", _parse_rtm, first_year, refresh)


def as_prices(first_year: int = 2019, refresh: bool = False) -> pd.DataFrame:
    """Hourly day-ahead ancillary-service clearing prices ($/MW-h): REGUP, REGDN, RRS, NSPIN, ECRS."""
    return _yearly("as", _parse_as, first_year, refresh)


# --------------------------------------------------------------------------- EIA-930, local hours
def hourly_fundamentals(refresh: bool = False) -> pd.DataFrame:
    """Wide hourly ERCOT table: demand, solar, wind, gas and storage (MW), by local date and hour ending.

    The work is done by data.hourly_grid(), shared with CAISO so both markets are built the same way.
    Sanity check used when this was built: average Texas solar peaks around HE13-15, as it should.
    """
    return hourly_grid("ERCO", "US/Central", refresh=refresh)


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
    # 'Other' also holds small non-storage plants that run around the clock. Their level is
    # estimated from the overnight hours (HE1-5) and subtracted, leaving the storage swing.
    base = s[s["he"].between(1, 5)].groupby("date")["stor"].median().clip(lower=0)
    peak = s[s["he"].isin(range(17, 24))].groupby("date")["stor"].max()
    out = pd.DataFrame({"batt_peak_gw": (peak - base).clip(lower=0) / 1000})
    # Daily discharge goes up and down with prices; the fleet's capability only grows. A high
    # percentile over the past 90 days tracks capability, and shift(1) keeps today's prices out.
    out["batt_fleet_gw"] = out["batt_peak_gw"].shift(1).rolling(90, min_periods=30).quantile(0.95)
    return out.reset_index()


def daily_panel(hub: str = "HB_HUBAVG", gas: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per ERCOT delivery day: price shape, load and net-load shape, solar, storage, gas."""
    from .data import henry_hub

    p = dam_hub_prices()
    p = p[p["point"] == hub]
    f = hourly_fundamentals()
    # Hourly prices + hourly grid data, matched on (date, hour ending). An inner join keeps
    # only hours present in both sources.
    h = p.merge(f, on=["date", "he"], how="inner")

    def at_max(g, col):
        """Hour ending at which `col` is highest that day (idxmax finds the row of the max)."""
        return g.loc[g[col].idxmax(), "he"]

    # Collapse 24 hourly rows into one row per day. Each entry below is one daily summary,
    # e.g. "price_eve" = average price over the evening hours, "he_price_max" = the hour
    # the price peaked.
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
    # Net-load ramp: how far net load climbs from its midday low (solar at full output) to its
    # evening high (sun down). This is what the grid must cover after sunset, and what E2 uses.
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
