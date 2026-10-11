"""CAISO data: hourly day-ahead hub prices from CAISO's OASIS, via the open-source gridstatus library.

EIA only publishes one daily on-peak price for SP15. CAISO's own market system (OASIS) has every
hourly price at every node. The gridstatus package (pip install gridstatus) handles OASIS's
quirks (zipped CSVs, 31-day request limits, rate limits) and needs no account or key.

The hosted Gridstatus API (gridstatus.io) is a separate, paid-tier product that needs a key;
this module only uses the free open-source library.
"""
from __future__ import annotations

import sys
import time
from datetime import date

import pandas as pd

from .config import CACHE

SP15 = "TH_SP15_GEN-APND"    # CAISO's trading hub for Southern California


def _month_starts(first_year: int, last_year: int | None = None):
    d = pd.Timestamp(f"{first_year}-01-01")
    end = pd.Timestamp(date.today())
    if last_year is not None:
        end = min(end, pd.Timestamp(f"{last_year}-12-31"))
    while d <= end:
        yield d, min(d + pd.offsets.MonthBegin(1), end + pd.Timedelta("1D"))
        d += pd.offsets.MonthBegin(1)


def dam_hub_prices(first_year: int = 2023, node: str = SP15, refresh: bool = False) -> pd.DataFrame:
    """Hourly day-ahead LMPs ($/MWh) for one CAISO node, keyed by local date and hour ending.

    Downloaded one month at a time (OASIS allows at most 31 days per request) and cached per
    month, so an interrupted download resumes where it stopped. OASIS keeps only about the last
    three years (from mid-2023 as of Oct 2026); older hourly prices need Gridstatus's paid archive.
    """
    import gridstatus
    import logging
    logging.getLogger("gridstatus").setLevel(logging.WARNING)

    iso, frames = gridstatus.CAISO(), []
    this_month = pd.Timestamp(date.today()).to_period("M")
    for start, end in _month_starts(first_year):
        path = CACHE / f"caiso_dam_{node}_{start:%Y_%m}.parquet"
        current = start.to_period("M") == this_month
        if path.exists() and not (refresh or current):
            frames.append(pd.read_parquet(path))
            continue
        raw = None
        for attempt in range(4):
            try:
                raw = iso.get_lmp(date=start, end=end, market="DAY_AHEAD_HOURLY", locations=[node])
                break
            except Exception as e:
                # OASIS only keeps a rolling ~3 years of prices. Older months answer "No data
                # found": skip those instead of retrying. Anything else is usually a rate limit.
                # (gridstatus surfaces that as "No objects to concatenate" for multi-day ranges.)
                if "No data found" in str(e) or "No objects to concatenate" in str(e):
                    break
                time.sleep(10 * 2 ** attempt)
        else:
            raise RuntimeError(f"OASIS kept failing for {start:%Y-%m}")
        if raw is None:
            # Remember that OASIS has nothing for this month, so later runs don't ask again.
            pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "he": pd.Series(dtype=int),
                          "price": pd.Series(dtype=float)}).to_parquet(path, index=False)
            continue
        # Interval Start is local Pacific time. ERCOT-style keys: delivery date + hour ending 1-24.
        t = raw["Interval Start"].dt.tz_localize(None)
        df = pd.DataFrame({"date": t.dt.normalize(), "he": t.dt.hour + 1, "price": raw["LMP"].astype(float)})
        df = df.drop_duplicates(["date", "he"])      # the repeated hour at the DST fall-back
        df.to_parquet(path, index=False)
        frames.append(df)
        time.sleep(5)                                # stay polite to OASIS
    return pd.concat(frames, ignore_index=True)


def hourly_grid(first_year: int = 2019, refresh: bool = False, last_year: int | None = None) -> pd.DataFrame:
    """CAISO's own hourly load and generation mix (MW), in the same layout as data.hourly_grid().

    Why not EIA-930 for CAISO? Its CISO hourly timestamps drift by up to 1.5 hours between
    mid-2022 and 2025 (solar appears to peak at 2-3pm). CAISO's published 5-minute fuel mix has
    no such problem and reports batteries directly, charging and discharging.
    """
    import gridstatus
    import logging
    logging.getLogger("gridstatus").setLevel(logging.WARNING)

    iso, frames = gridstatus.CAISO(), []
    this_month = pd.Timestamp(date.today()).to_period("M")
    for start, end in _month_starts(first_year, last_year):
        path = CACHE / f"caiso_grid_{start:%Y_%m}.parquet"
        current = start.to_period("M") == this_month
        if path.exists() and not (refresh or current):
            frames.append(pd.read_parquet(path))
            continue
        end = min(end, pd.Timestamp(date.today()))            # today's file is still filling in
        if end <= start:
            continue
        for attempt in range(4):
            try:
                mix = iso.get_fuel_mix(date=start, end=end)
                load = iso.get_load(date=start, end=end)
                break
            except Exception:
                time.sleep(10 * 2 ** attempt)
        else:
            raise RuntimeError(f"CAISO kept failing for {start:%Y-%m}")
        five = mix.merge(load[["Interval Start", "Load"]], on="Interval Start", how="inner")
        t = five["Interval Start"].dt.tz_localize(None)            # local Pacific time
        five = five.assign(date=t.dt.normalize(), he=t.dt.hour + 1)
        cols = {"Load": "demand", "Solar": "solar", "Wind": "wind", "Natural Gas": "gas_gen",
                "Batteries": "battery", "Imports": "imports"}
        # Average the twelve 5-minute readings in each hour to get that hour's MW.
        df = five.groupby(["date", "he"])[list(cols)].mean().rename(columns=cols).reset_index()
        df.to_parquet(path, index=False)
        frames.append(df)
    h = pd.concat(frames, ignore_index=True)
    h[["solar", "wind", "battery"]] = h[["solar", "wind", "battery"]].fillna(0.0)
    h["other"] = 0.0
    h["net_load"] = h["demand"] - h["solar"] - h["wind"]
    h["storage"] = h["battery"]                       # positive = discharging, negative = charging
    return h


if __name__ == "__main__":
    if "grid" in sys.argv:
        g = hourly_grid()
        print(len(g), "hours", g["date"].min().date(), "->", g["date"].max().date())
        sys.exit()
    p = dam_hub_prices()
    print(len(p), "hours", p["date"].min().date(), "->", p["date"].max().date())
