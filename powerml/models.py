"""Model zoo + walk-forward backtester for next-day on-peak price forecasts.

Every model is trained on all history strictly before a test year and scored on that year
(expanding window), so no fold ever sees its own future.

Every model here has the same two methods, fit(X, y) and predict(X), like scikit-learn. That
shared shape is what lets walk_forward() at the bottom run any of them interchangeably.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


class Persistence:
    """Tomorrow's price = last cleared price. The bar every real model has to clear."""

    def fit(self, X, y):
        return self

    def predict(self, X):
        return X["price_lag"].to_numpy()


class HeatRateRidge:
    """Forecast the implied heat rate linearly, then multiply back by gas.

    Modeling heat rate instead of $/MWh strips out the gas level, which otherwise dominates
    every power-price regression and makes the fundamental coefficients unstable.
    """

    def __init__(self, features):
        # Dollar-denominated inputs are dropped: the model works in heat-rate units, and gas
        # is used separately to convert back to $/MWh. Month and weekday are handled below.
        drop = ("gas", "price_lag", "price_lag_5d_mean", "month", "dow")
        self.features = [f for f in features if f not in drop]

    def fit(self, X, y):
        # Preprocessing, bundled with the model in one Pipeline so it's fit on TRAINING data
        # only (fitting the scaler on all data would leak test-period information):
        #   StandardScaler: rescale each numeric feature to mean 0, std 1, so the ridge
        #                   penalty treats features in big and small units equally.
        #   OneHotEncoder:  turn month/weekday into 0/1 columns, so December (12) isn't
        #                   treated as "12 times" January (1).
        ct = ColumnTransformer([
            ("num", StandardScaler(), self.features),
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["month", "dow"]),
        ])
        # RidgeCV tries 20 penalty strengths from 0.01 to 1000 and keeps the best one.
        self.model = make_pipeline(ct, RidgeCV(alphas=np.logspace(-2, 3, 20)))
        # Target transformation: learn heat rate (price / gas), not price.
        self.model.fit(X[self.features + ["month", "dow"]], y / X["gas"])
        return self

    def predict(self, X):
        # Predicted heat rate x today's gas price = predicted $/MWh.
        return self.model.predict(X[self.features + ["month", "dow"]]) * X["gas"].to_numpy()


class GBM:
    """LightGBM on the same KNOWN features. objective='quantile' gives tail bands."""

    def __init__(self, features, objective="regression", alpha=None):
        self.features = features
        # Gradient boosting builds many small decision trees in sequence, each one fit to the
        # errors the earlier trees still make. The settings below keep it from overfitting:
        #   n_estimators=400 trees, each contributing only 3% (learning_rate) of its prediction;
        #   num_leaves=15 keeps each tree small; min_child_samples=20 means a leaf needs 20+ days;
        #   subsample / colsample_bytree = each tree sees a random 80% of days and features.
        # objective: "regression" = squared error (predicts the mean), "huber" = robust to
        # spike days, "quantile" with alpha=0.9 = predicts the 90th percentile instead.
        self.params = dict(objective=objective, n_estimators=400, learning_rate=0.03,
                           num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                           colsample_bytree=0.8, verbose=-1)
        if alpha is not None:
            self.params["alpha"] = alpha

    def fit(self, X, y):
        self.model = lgb.LGBMRegressor(**self.params).fit(X[self.features], y)
        return self

    def predict(self, X):
        return self.model.predict(X[self.features])


class OnPersistence:
    """Wrap any model so it learns the day-over-day change instead of the price level.

    Trees cannot extrapolate beyond the price range they were trained on, so a level model
    trained through 2021 has no way to forecast 2022's gas crisis. Predicting the delta from
    the last cleared price keeps persistence as the floor and lets fundamentals add the edge.
    """

    def __init__(self, inner):
        self.inner = inner

    def fit(self, X, y):
        # Train on "how much did the price move?" rather than "what was the price?"
        self.inner.fit(X, y - X["price_lag"])
        return self

    def predict(self, X):
        return X["price_lag"].to_numpy() + self.inner.predict(X)


@dataclass
class Backtest:
    preds: pd.DataFrame  # date, year, y, and one column per model

    def scores(self) -> pd.DataFrame:
        rows = []
        models = [c for c in self.preds.columns if c not in ("date", "year", "y", "price_lag")]
        for name in models:
            err = self.preds[name] - self.preds["y"]
            # Directional accuracy: did the model call up vs down correctly? np.sign gives
            # +1 (up), -1 (down) or 0 (flat); flat days are skipped below.
            true_move = np.sign(self.preds["y"] - self.preds["price_lag"])
            pred_move = np.sign(self.preds[name] - self.preds["price_lag"])
            rows.append({
                # MAE = typical miss in $/MWh. RMSE punishes big misses more than MAE.
                # bias = average signed miss: positive means the model runs too high.
                "model": name,
                "MAE": err.abs().mean(),
                "RMSE": np.sqrt((err ** 2).mean()),
                "bias": err.mean(),
                "dir_acc": (true_move == pred_move)[true_move != 0].mean() if name != "persistence" else np.nan,
            })
        return pd.DataFrame(rows).set_index("model").sort_values("MAE")


def walk_forward(df: pd.DataFrame, models: dict[str, Callable[[], object]], features,
                 target: str = "price", first_test_year: int = 2022) -> Backtest:
    """Expanding-window backtest: for each test year, train on every earlier year, predict that year.

    `models` maps a name to a function that builds a FRESH, untrained model, so nothing learned
    in one year's fold can carry over into the next.
    """
    df = df.dropna(subset=features + [target, "price_lag", "gas"]).sort_values("date")
    out = []
    for year in sorted(df["year"].unique()):
        if year < first_test_year:
            continue
        # The core of walk-forward: training data is strictly in the past.
        train, test = df[df["year"] < year], df[df["year"] == year]
        if len(train) < 250 or test.empty:      # need about a year of history to learn anything
            continue
        fold = test[["date", "year", "price_lag"]].copy()
        fold["y"] = test[target].to_numpy()
        for name, make in models.items():
            fold[name] = make().fit(train, train[target]).predict(test)
        out.append(fold)
    return Backtest(pd.concat(out, ignore_index=True))
