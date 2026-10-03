"""Loaders for the three EIA sources this project uses.

1. ICE day-ahead on-peak power prices, republished by EIA as yearly spreadsheets.
2. Henry Hub daily natural gas spot price (EIA series RNGWHHD).
3. EIA-930 daily demand, demand forecast, and net generation by fuel (EIA API v2).

Every loader caches to data/raw or data/cache so re-runs are offline and cheap.
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
    if dest.exists() and not force:
        return dest
    r = requests.get(url, timeout=120)
    r.raise_for_status()
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

    name_to_key = {h.ice_name: k for k, h in HUBS.items()}
    df["hub"] = df["ice_name"].map(name_to_key)
    df = df[df["hub"].notna() & (df["delivery_start"] == df["delivery_end"])]
    df = df.rename(columns={"delivery_start": "date"})
    cols = ["hub", "date", "trade_date", "price", "high", "low", "volume_mwh", "n_trades"]
    return df[cols].drop_duplicates(["hub", "date"], keep="last").sort_values(["hub", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------- Henry Hub gas
def henry_hub() -> pd.DataFrame:
    """Henry Hub spot $/MMBtu indexed by trade date."""
    path = _download(HENRY_HUB_URL, RAW / "RNGWHHDd.xls", force=_stale(RAW / "RNGWHHDd.xls"))
    df = pd.read_excel(path, sheet_name="Data 1", skiprows=2)
    df.columns = ["trade_date", "gas"]
    df["trade_date"] = pd.to_datetime(df["trade_date"])
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
    for name, values in facets.items():
        params[f"facets[{name}][]"] = list(values)

    rows, offset = [], 0
    while True:
        params["offset"] = offset
        for attempt in range(4):
            r = requests.get(f"{API_BASE}/{route}/data/", params=params, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * 2 ** attempt)
                continue
            r.raise_for_status()
            break
        else:
            r.raise_for_status()
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
    parts = [eia930_daily(ba, hub.timezone, refresh=refresh) for ba in hub.bas]
    return pd.concat(parts).groupby("date", as_index=False).sum(min_count=1)
