"""Leakage guards: the two ways this project could silently cheat."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from powerml.features import build_panel
from powerml.models import Persistence, walk_forward


def _fake_inputs(n_days=900):
    days = pd.bdate_range("2019-01-02", periods=n_days)
    rng = np.random.default_rng(0)
    prices = pd.DataFrame({"hub": "SP15", "date": days, "trade_date": days - pd.offsets.BDay(1),
                           "price": 40 + rng.normal(0, 5, n_days), "high": 0, "low": 0,
                           "volume_mwh": 0, "n_trades": 1})
    all_days = pd.date_range(days[0] - pd.Timedelta("10D"), days[-1])
    gas = pd.DataFrame({"trade_date": all_days, "gas": 3.0})
    # Make each day's demand equal to its ordinal so lags are easy to verify.
    fund = pd.DataFrame({"date": all_days, "demand": all_days.map(pd.Timestamp.toordinal).astype(float),
                         "demand_fcst": 1.0, "gen_sun": 0.0, "gen_wnd": 0.0})
    return prices, gas, fund


def test_lagged_fundamentals_come_from_before_the_trade_date():
    df = build_panel("SP15", *_fake_inputs())
    known_day = pd.to_datetime((df["demand_gw_lag"] * 24 * 1000).round().astype(int).map(pd.Timestamp.fromordinal))
    assert (known_day < df["trade_date"]).all()


def test_walk_forward_never_trains_on_test_year():
    df = build_panel("SP15", *_fake_inputs())
    seen = []

    class Spy(Persistence):
        def fit(self, X, y):
            seen.append(X["year"].max())
            return self

    bt = walk_forward(df, {"spy": Spy}, ["price_lag"], first_test_year=2021)
    test_years = sorted(bt.preds["year"].unique())
    assert len(seen) == len(test_years)
    assert all(last_train < test for last_train, test in zip(seen, test_years))
