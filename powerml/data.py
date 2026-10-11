"""Loaders for the three EIA sources this project uses.

1. ICE day-ahead on-peak power prices, republished by EIA as yearly spreadsheets.
2. Henry Hub daily natural gas spot price (EIA series RNGWHHD).
3. EIA-930 daily demand, demand forecast, and net generation by fuel (EIA API v2).

Every loader caches to data/raw or data/cache so re-runs are offline and cheap.

How to read this file: start with ice_power_prices() and henry_hub() (plain file downloads),
then eia_api() (the one function that talks to EIA's API), then eia930_daily() and
fundamentals(), which turn API rows into one tidy table per hub. caiso_storage() at the bottom
is the trick used in thesis T01b to find batteries that EIA doesn't label.
"""
from __future__ import annotations

import os
import time
from datetime import date

import pandas as pd
import requests
from dotenv import load_dotenv

from .config import CACHE, EIA930_FIRST_DAY, FUELS, HUBS, ICE_FIRST_YEAR, RAW, REGION_TYPES

ICE_BASE = "https://www.eia.gov/electricity/wholesale/xls"
HENRY_HUB_URL = "https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls"
API_BASE = "https://api.eia.gov/v2"
PAGE = 5000  # EIA API v2 max rows per request

load_dotenv()  # picks up EIA_API_KEY from a local .env


def _download(url: str, dest, force: bool = False):
    # Caching: if we already have the file, use it. Only re-download when forced (e.g. the
    # current year's file, which EIA keeps appending to).
    if dest.exists() and not force:
        return dest
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    # A missing file on eia.gov returns a normal web page (status 200) instead of an error,
    # so check the first bytes: a real spreadsheet never starts with "<!doctype html".
    if r.content[:15].lower().startswith(b"<!doctype html"):
        raise RuntimeError(f"{url} returned an HTML page, not a data file")
    dest.write_bytes(r.content)
    return dest


# --------------------------------------------------------------------------- ICE power prices
def ice_power_prices(first_year: int = ICE_FIRST_YEAR, last_year: int | None = None) -> pd.DataFrame:
    """Daily on-peak day-ahead prices, one row per (hub, delivery_date).

    Only single-day delivery packages are kept; multi-day weekend/holiday strips are dropped
    so every price maps cleanly onto one delivery day of fundamentals.
    """
    last_year = last_year or date.today().year
    frames = []
    for year in range(first_year, last_year + 1):
        current = year == date.today().year
        name = f"ice_electric-{year}.xlsx" if current else f"ice_electric-{year}final.xlsx"
        url = f"{ICE_BASE}/{name}" if current else f"{ICE_BASE}/archive/{name}"
        path = _download(url, RAW / name, force=current)
        frames.append(pd.read_excel(path))

    df = pd.concat(frames, ignore_index=True)
    df.columns = [" ".join(str(c).split()) for c in df.columns]  # headers contain stray newlines
    df = df.rename(columns={
        "Price hub": "ice_name",
        "Trade date": "trade_date",
        "Delivery start date": "delivery_start",
        "Delivery end date": "delivery_end",
        "High price $/MWh": "high",
        "Low price $/MWh": "low",
        "Wtd avg price $/MWh": "price",
        "Daily volume MWh": "volume_mwh",
        "Number of trades": "n_trades",
        "Number of counterparties": "n_counterparties",
    })
    for c in ("trade_date", "delivery_start", "delivery_end"):
        df[c] = pd.to_datetime(df[c])

    # Translate ICE's long hub names ("SP15 EZ Gen DA LMP Peak") to short keys ("SP15").
    # Hubs we don't model map to NaN and are dropped on the next line.
    name_to_key = {h.ice_name: k for k, h in HUBS.items()}
    df["hub"] = df["ice_name"].map(name_to_key)
    # Keep single-day products only. A Friday trade covering Sat-Mon is one price for three
    # days, which can't be matched to one day of grid data.
    df = df[df["hub"].notna() & (df["delivery_start"] == df["delivery_end"])]
    df = df.rename(columns={"delivery_start": "date"})
    cols = ["hub", "date", "trade_date", "price", "high", "low", "volume_mwh", "n_trades"]
    return df[cols].drop_duplicates(["hub", "date"], keep="last").sort_values(["hub", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------- Henry Hub gas
def henry_hub() -> pd.DataFrame:
    """Henry Hub spot $/MMBtu indexed by trade date."""
    path = _download(HENRY_HUB_URL, RAW / "RNGWHHDd.xls", force=_stale(RAW / "RNGWHHDd.xls"))
    df = pd.read_excel(path, sheet_name="Data 1", skiprows=2)   # first 2 rows are titles
    df.columns = ["trade_date", "gas"]
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    # Excel sometimes hands numbers back as text; force them to floats so math works.
    # errors="coerce" turns anything unparseable into NaN, which dropna() then removes.
    df["gas"] = pd.to_numeric(df["gas"], errors="coerce")
    return df.dropna().reset_index(drop=True)


def _stale(path, days: int = 1) -> bool:
    return not path.exists() or (time.time() - path.stat().st_mtime) > days * 86400


# --------------------------------------------------------------------------- EIA-930 via API v2
def _api_key() -> str:
    key = os.environ.get("EIA_API_KEY")
    if key:
        return key
    global _warned
    if not _warned:
        _warned = True
        print("[eia] EIA_API_KEY not set - using DEMO_KEY (heavily rate limited). "
              "Register free at https://www.eia.gov/opendata/register.php")
    return "DEMO_KEY"


_warned = False


def eia_api(route: str, facets: dict, start: str, end: str, frequency: str = "daily") -> pd.DataFrame:
    """Fetch every page of an EIA API v2 data route into a DataFrame."""
    params = {
        "api_key": _api_key(),
        "frequency": frequency,
        "data[0]": "value",
        "start": start,
        "end": end,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": PAGE,
    }
    # Facets are filters, e.g. {"respondent": ["CISO"], "fueltype": ["SUN", "WND"]}
    # becomes facets[respondent][]=CISO&facets[fueltype][]=SUN&facets[fueltype][]=WND.
    for name, values in facets.items():
        params[f"facets[{name}][]"] = list(values)

    # Pagination: EIA returns at most 5,000 rows per request, so keep asking for the next
    # 5,000 (offset 0, 5000, 10000, ...) until we've collected the 'total' it reports.
    rows, offset = [], 0
    while True:
        params["offset"] = offset
        for attempt in range(4):
            try:
                r = requests.get(f"{API_BASE}/{route}/data/", params=params, timeout=120)
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(5 * 2 ** attempt)        # dropped connection: same backoff as a 429
                continue
            # 429 = "too many requests", 5xx = server hiccup. Both are usually temporary, so
            # wait and retry with exponential backoff: 5s, 10s, 20s, 40s.
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * 2 ** attempt)
                continue
            if not r.ok:
                _raise(r)
            break
        else:
            _raise(r)
        body = r.json()["response"]
        rows.extend(body["data"])
        offset += PAGE
        if offset >= int(body["total"]):
            break
    df = pd.DataFrame(rows)
    if not df.empty:
        df["period"] = pd.to_datetime(df["period"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def _raise(r):
    """Raise on a failed EIA call without echoing the request URL, which contains the API key."""
    raise requests.HTTPError(f"EIA API returned {r.status_code}: {r.text[:300]}")


def eia930_daily(ba: str, timezone: str, end: str | None = None, refresh: bool = False) -> pd.DataFrame:
    """Wide daily table for one balancing authority: demand, forecast, and generation by fuel (MWh)."""
    path = CACHE / f"eia930_{ba}.parquet"
    end = end or date.today().isoformat()
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    region = eia_api("electricity/rto/daily-region-data",
                     {"respondent": [ba], "type": REGION_TYPES, "timezone": [timezone]},
                     EIA930_FIRST_DAY, end)
    fuel = eia_api("electricity/rto/daily-fuel-type-data",
                   {"respondent": [ba], "fueltype": FUELS, "timezone": [timezone]},
                   EIA930_FIRST_DAY, end)

    # The API returns "long" data (one row per date per series). pivot_table reshapes it to
    # "wide" data: one row per date, one column per series (demand, demand_fcst, gen_sun, ...).
    region_w = region.pivot_table(index="period", columns="type", values="value", aggfunc="sum")
    region_w = region_w.rename(columns={"D": "demand", "DF": "demand_fcst"})
    fuel_w = fuel.pivot_table(index="period", columns="fueltype", values="value", aggfunc="sum")
    fuel_w.columns = [f"gen_{c.lower()}" for c in fuel_w.columns]

    wide = region_w.join(fuel_w, how="outer").rename_axis("date").reset_index()
    wide.to_parquet(path, index=False)
    return wide


def fundamentals(hub_key: str, refresh: bool = False) -> pd.DataFrame:
    """EIA-930 daily fundamentals for a hub, summing across its balancing authorities."""
    hub = HUBS[hub_key]
    # Most hubs map to one balancing authority; Palo Verde maps to two (APS + SRP), so
    # stack their tables and add them up day by day. min_count=1 keeps a day as NaN
    # (missing) rather than 0 when no BA reported it.
    parts = [eia930_daily(ba, hub.timezone, refresh=refresh) for ba in hub.bas]
    return pd.concat(parts).groupby("date", as_index=False).sum(min_count=1)


def eia930_hourly(ba: str, fuels, refresh: bool = False) -> pd.DataFrame:
    """Hourly net generation by fuel (UTC periods) for one BA, long format, cached."""
    path = CACHE / f"eia930_{ba}_hourly_{'_'.join(sorted(fuels)).lower()}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    d = eia_api("electricity/rto/fuel-type-data", {"respondent": [ba], "fueltype": list(fuels)},
                f"{EIA930_FIRST_DAY}T00", f"{date.today().isoformat()}T00", frequency="hourly")
    d = d[["period", "fueltype", "value"]]
    d.to_parquet(path, index=False)
    return d


def caiso_storage(refresh: bool = False) -> pd.DataFrame:
    """Daily CAISO battery charge/discharge (GWh), recovered from the hourly 'Other' series.

    CAISO reports storage inside EIA-930's OTH bucket rather than as BAT. Its daily total
    nets to ~zero (round-trip losses), but the hourly shape is unmistakable: negative at
    midday (charging on solar) and positive in the evening (discharging into the ramp).
    """
    h = eia930_hourly("CISO", ["OTH"], refresh=refresh)
    # EIA hourly data is in UTC. Convert to California time before grouping by day, or the
    # 8pm discharge (04:00 UTC the next day) would be counted on the wrong date.
    local = h["period"].dt.tz_localize("UTC").dt.tz_convert("US/Pacific")
    h = h.assign(date=local.dt.tz_localize(None).dt.normalize())
    # Positive hours = discharging (selling power); negative hours = charging (buying power).
    daily = h.groupby("date")["value"].agg(
        batt_discharge_gwh=lambda v: v.clip(lower=0).sum() / 1000,
        batt_charge_gwh=lambda v: -v.clip(upper=0).sum() / 1000,
    ).reset_index()
    # Fleet-size proxy: trailing 90-day 95th percentile of discharge. Using capability rather
    # than same-day dispatch avoids reverse causality (batteries discharge MORE on high-price days).
    daily["batt_fleet_gwh"] = (daily["batt_discharge_gwh"].shift(1)
                               .rolling(90, min_periods=30).quantile(0.95))
    return daily


def _hourly_series(ba: str, route: str, facets: dict, name: str, refresh: bool) -> pd.DataFrame:
    """One EIA-930 hourly route for one BA (UTC hour-ending periods), long format, cached."""
    path = CACHE / f"eia930_{ba}_{name}_hourly.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    d = eia_api(route, {"respondent": [ba], **facets}, f"{EIA930_FIRST_DAY}T00",
                f"{date.today().isoformat()}T00", frequency="hourly")
    key = "fueltype" if "fueltype" in d.columns else "type"
    d = d[["period", key, "value"]].rename(columns={key: "series"})
    d.to_parquet(path, index=False)
    return d


def hourly_grid(ba: str, tz: str, refresh: bool = False) -> pd.DataFrame:
    """Wide hourly table for one balancing authority, in its local time.

    Columns: date, he (hour ending 1-24), demand, solar, wind, gas_gen, other, battery (MW),
    net_load = demand - solar - wind, and storage = other + battery (net storage output; see
    the thesis scripts for how each market reports it).
    """
    gen = _hourly_series(ba, "electricity/rto/fuel-type-data",
                         {"fueltype": ["SUN", "WND", "NG", "OTH", "BAT"]}, "fuel", refresh)
    dem = _hourly_series(ba, "electricity/rto/region-data", {"type": ["D"]}, "demand", refresh)
    d = pd.concat([gen, dem.assign(series="D")])
    # EIA-930 periods are UTC and mark the END of the hour, the same convention as ISO "hour
    # ending". Step back one hour to the hour's start, convert to local time, and the local date
    # plus (start hour + 1) is the delivery date and hour ending.
    start = (d["period"] - pd.Timedelta("1h")).dt.tz_localize("UTC").dt.tz_convert(tz).dt.tz_localize(None)
    d = d.assign(date=start.dt.normalize(), he=start.dt.hour + 1)
    wide = d.pivot_table(index=["date", "he"], columns="series", values="value", aggfunc="mean").reset_index()
    wide = wide.rename(columns={"D": "demand", "SUN": "solar", "WND": "wind", "NG": "gas_gen",
                                "OTH": "other", "BAT": "battery"})
    for c in ("solar", "wind", "battery", "other"):
        if c not in wide:
            wide[c] = 0.0
    wide[["solar", "wind"]] = wide[["solar", "wind"]].fillna(0.0)
    wide["net_load"] = wide["demand"] - wide["solar"] - wide["wind"]
    wide["storage"] = wide["other"].fillna(0) + wide["battery"].fillna(0)
    return wide
