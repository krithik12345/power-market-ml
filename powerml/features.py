"""Turn raw prices + gas + EIA-930 into one modeling panel per hub.

Two feature families, kept deliberately separate:

* EXPLAIN features describe the delivery day itself (actual demand, actual solar, ...).
  They are what you use to test a structural thesis ("solar share compresses heat rates").
  They are NOT available when the trade happens, so never use them to score a forecast.

* KNOWN features are what a trader actually has on the trade date: the EIA day-ahead
  demand forecast for the delivery day, yesterday's realized fuel mix, gas on the trade
  date, and the last cleared price. Forecast backtests use only these.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data

EXPLAIN = ["demand_gw", "net_load_gw", "solar_share", "wind_share", "hydro_share",
           "nuclear_share", "gas_share"]
CALENDAR = ["dow", "month", "doy_sin", "doy_cos", "trend_yrs"]
KNOWN = ["demand_fcst_gw", "demand_fcst_delta", "solar_share_lag", "wind_share_lag",
         "hydro_share_lag", "net_load_gw_lag", "gas", "gas_chg", "price_lag", "ihr_lag",
         "price_lag_5d_mean"]


def _shares(f: pd.DataFrame) -> pd.DataFrame:
    """Add unit conversions and fuel shares to a daily fundamentals table."""
    f = f.copy()
    # gen("gen_sun") returns that column, or zeros if this region has no such fuel
    # (e.g. New England reports no meaningful solar early on). Missing days count as 0.
    gen = lambda c: f.get(c, pd.Series(0.0, index=f.index)).fillna(0.0)
    d = f["demand"]
    # Shares (fuel / demand) are scale-free, so they compare fairly across years even as
    # total demand grows. A raw "MWh of solar" would mix up solar growth and load growth.
    f["demand_gw"] = d / 24 / 1000                    # daily MWh -> average GW
    f["demand_fcst_gw"] = f["demand_fcst"] / 24 / 1000
    f["net_load_gw"] = (d - gen("gen_sun") - gen("gen_wnd")) / 24 / 1000
    f["solar_share"] = gen("gen_sun") / d
    f["wind_share"] = gen("gen_wnd") / d
    f["hydro_share"] = gen("gen_wat") / d
    f["nuclear_share"] = gen("gen_nuc") / d
    f["gas_share"] = gen("gen_ng") / d
    return f


def build_panel(hub: str, prices: pd.DataFrame | None = None, gas: pd.DataFrame | None = None,
                fund: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per delivery day for one hub, with prices, gas, fundamentals and features.

    Every thesis and forecast script starts by calling this. The optional arguments let the
    tests pass in small fake tables instead of downloading real data.
    """
    prices = data.ice_power_prices() if prices is None else prices
    gas = data.henry_hub() if gas is None else gas
    fund = data.fundamentals(hub) if fund is None else fund

    p = prices[prices["hub"] == hub].sort_values("date").copy()

    # Gas on the power trade date (both are next-day products traded the same morning).
    # merge_asof is a "nearest earlier match" join: if Henry Hub didn't print that day
    # (a holiday), use the most recent earlier price, up to 5 days back.
    p = pd.merge_asof(p.sort_values("trade_date"), gas.sort_values("trade_date"),
                      on="trade_date", direction="backward", tolerance=pd.Timedelta("5D"))
    p = p.sort_values("date")
    # Implied market heat rate (MMBtu/MWh): power price relative to its fuel. This is the
    # project's core variable. It removes gas-price swings so grid effects are visible.
    p["ihr"] = p["price"] / p["gas"]

    f = _shares(fund).sort_values("date")
    # LOOK-AHEAD GUARD. On the trade-date morning, the latest complete day of grid data is
    # the day BEFORE the trade date. So the "_lag" columns are pulled from trade_date - 1,
    # never from the delivery day. tests/test_pipeline.py checks this.
    lagged = f[["date", "demand_gw", "solar_share", "wind_share", "hydro_share", "net_load_gw"]].copy()
    lagged.columns = ["lag_date"] + [f"{c}_lag" for c in lagged.columns[1:]]

    df = p.merge(f, on="date", how="left")
    df["lag_date"] = df["trade_date"] - pd.Timedelta("1D")
    df = df.merge(lagged, on="lag_date", how="left").drop(columns="lag_date")

    # Expected load change into the delivery day: tomorrow's forecast vs the last realized day.
    df["demand_fcst_delta"] = df["demand_fcst_gw"] - df["demand_gw_lag"]
    df["gas_chg"] = df["gas"] - df["gas"].shift(1)
    # shift(1) = "the previous row". Rows are delivery days in order, and the previous
    # delivery day's price was traded before this one, so it's known at trade time.
    df["price_lag"] = df["price"].shift(1)
    df["ihr_lag"] = df["ihr"].shift(1)
    df["price_lag_5d_mean"] = df["price"].shift(1).rolling(5, min_periods=3).mean()

    df["dow"] = df["date"].dt.dayofweek
    df["month"] = df["date"].dt.month
    df["year"] = df["date"].dt.year
    # Season as a point on a circle: Dec 31 and Jan 1 end up next to each other, which a
    # plain 1-365 day number can't express (it would put them 364 apart).
    doy = df["date"].dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    # Years since 2019 as a decimal. Lets regressions test "is this effect changing over time?"
    df["trend_yrs"] = (df["date"] - pd.Timestamp("2019-01-01")).dt.days / 365.25
    df["hub"] = hub
    return df.reset_index(drop=True)
