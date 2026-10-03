"""Thesis 02 - The Mid-C vs SP15 spread is a hydro story.

Claim: The Mid-C minus SP15 on-peak spread is set by Pacific Northwest hydro. When BPA hydro
runs above its seasonal norm, Mid-C falls further below SP15, and yesterday's hydro anomaly
(known on the trade date) helps forecast tomorrow's spread.

Outputs land in reports/T02_midc_hydro/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer

from powerml.config import REPORTS
from powerml.data import fundamentals
from powerml.features import build_panel

OUT = REPORTS / "T02_midc_hydro"
OUT.mkdir(parents=True, exist_ok=True)
HAC = dict(cov_type="HAC", cov_kwds={"maxlags": 5})

# ---------------------------------------------------------------- data
bpa = fundamentals("MIDC")
bpa = bpa.assign(
    hydro_gw=bpa["gen_wat"] / 24 / 1000,
    bpa_wind_gw=bpa["gen_wnd"] / 24 / 1000,
    bpa_load_gw=bpa["demand"] / 24 / 1000,
    month=bpa["date"].dt.month,
)
# Hydro anomaly = today's hydro minus the average for that calendar month across all years.
# Fine for the structural test; the forecast test below rebuilds it from past years only.
bpa["hydro_anom_gw"] = bpa["hydro_gw"] - bpa.groupby("month")["hydro_gw"].transform("mean")

mid = build_panel("MIDC")[["date", "trade_date", "year", "month", "dow", "price", "gas"]]
sp = build_panel("SP15")[["date", "price", "solar_share", "demand_gw"]].rename(
    columns={"price": "sp15", "solar_share": "ciso_solar", "demand_gw": "ciso_load_gw"})
df = (mid.rename(columns={"price": "midc"}).merge(sp, on="date")
      .merge(bpa[["date", "hydro_gw", "hydro_anom_gw", "bpa_wind_gw", "bpa_load_gw"]], on="date"))
df["spread"] = df["midc"] - df["sp15"]
df = df.dropna(subset=["spread", "hydro_gw"]).sort_values("date").reset_index(drop=True)
lo, hi = df["spread"].quantile([0.01, 0.99])
df["spread_w"] = df["spread"].clip(lo, hi)

# ---------------------------------------------------------------- 1. stylized facts
month_profile = df.groupby("month").agg(spread=("spread_w", "median"), hydro=("hydro_gw", "mean"))
fig, ax1 = plt.subplots(figsize=(8, 4))
ax1.bar(month_profile.index, month_profile["spread"], color=np.where(month_profile["spread"] < 0, "#2c7fb8", "#d95f0e"))
ax1.axhline(0, color="grey", lw=0.8)
ax1.set_ylabel("Median Mid-C − SP15 ($/MWh)")
ax2 = ax1.twinx(); ax2.plot(month_profile.index, month_profile["hydro"], "k.-", label="BPA hydro (avg GW)")
ax2.set_ylabel("BPA hydro (avg GW)"); ax2.legend(loc="lower right")
ax1.set_xticks(range(1, 13), [pd.Timestamp(2000, m, 1).strftime("%b") for m in range(1, 13)])
ax1.set_title("Mid-C − SP15 on-peak spread by month (2019+)")
fig.tight_layout(); fig.savefig(OUT / "seasonal_spread.png", dpi=150); plt.close(fig)

df["anom_bin"] = pd.qcut(df["hydro_anom_gw"], 5, labels=["Very dry", "Dry", "Normal", "Wet", "Very wet"])
by_bin = df.groupby("anom_bin", observed=True).agg(
    spread=("spread_w", "median"), p25=("spread_w", lambda s: s.quantile(.25)),
    p75=("spread_w", lambda s: s.quantile(.75)), anom=("hydro_anom_gw", "mean"), days=("spread", "size"))
fig, ax = plt.subplots(figsize=(7, 4))
x = np.arange(len(by_bin))
ax.bar(x, by_bin["spread"], color="#2c7fb8")
ax.errorbar(x, by_bin["spread"], yerr=[by_bin["spread"] - by_bin["p25"], by_bin["p75"] - by_bin["spread"]],
            fmt="none", color="k", capsize=4)
ax.set_xticks(x, [f"{i}\n({a:+.1f} GW)" for i, a in zip(by_bin.index, by_bin["anom"])])
ax.axhline(0, color="grey", lw=0.8); ax.set_ylabel("Mid-C − SP15 ($/MWh), median & IQR")
ax.set_title("Spread by BPA hydro anomaly (vs seasonal norm)")
fig.tight_layout(); fig.savefig(OUT / "spread_by_hydro.png", dpi=150); plt.close(fig)

yearly = df.groupby("year").agg(spread=("spread_w", "median"), anom=("hydro_anom_gw", "mean"))

# ---------------------------------------------------------------- 2. structural regression
reg = smf.ols("spread_w ~ hydro_anom_gw + bpa_wind_gw + bpa_load_gw + ciso_solar + ciso_load_gw + gas"
              " + C(month) + C(dow)", df).fit(**HAC)

# ---------------------------------------------------------------- 3. does it help forecast tomorrow's spread?
# Known on the trade date: yesterday's BPA hydro/wind and the last cleared spread.
lag = bpa[["date", "hydro_gw", "bpa_wind_gw", "month"]].rename(
    columns={"date": "lag_date", "hydro_gw": "hydro_lag", "bpa_wind_gw": "wind_lag", "month": "lag_month"})
fc = df.assign(lag_date=df["trade_date"] - pd.Timedelta("1D")).merge(lag, on="lag_date", how="left")
fc["spread_lag"] = fc["spread"].shift(1)
fc = fc.dropna(subset=["hydro_lag", "wind_lag", "spread_lag"])

rows = []
for year in sorted(fc["year"].unique()):
    if year < 2022:
        continue
    train, test = fc[fc["year"] < year].copy(), fc[fc["year"] == year].copy()
    clim = train.groupby("lag_month")["hydro_lag"].mean()          # past-years-only seasonal norm
    for part in (train, test):
        part["hydro_anom_lag"] = part["hydro_lag"] - part["lag_month"].map(clim)
    feats = ["hydro_anom_lag", "wind_lag", "spread_lag", "gas"]
    ct = ColumnTransformer([("n", StandardScaler(), feats),
                            ("c", OneHotEncoder(handle_unknown="ignore"), ["month"])])
    m = make_pipeline(ct, RidgeCV(alphas=np.logspace(-2, 3, 20)))
    m.fit(train[feats + ["month"]], train["spread"] - train["spread_lag"])
    test["ridge"] = test["spread_lag"] + m.predict(test[feats + ["month"]])
    rows.append(test[["date", "year", "spread", "spread_lag", "ridge", "hydro_anom_lag"]])
bt = pd.concat(rows)
mae = lambda c: (bt[c] - bt["spread"]).abs().mean()
fc_scores = pd.DataFrame({
    "MAE persistence": bt.groupby("year").apply(lambda g: (g["spread_lag"] - g["spread"]).abs().mean(), include_groups=False),
    "MAE hydro model": bt.groupby("year").apply(lambda g: (g["ridge"] - g["spread"]).abs().mean(), include_groups=False),
})
fc_scores.loc["All"] = [mae("spread_lag"), mae("ridge")]

# Simple rule: is the spread lower on days after a wet-anomaly day than after a dry one?
wet = bt[bt["hydro_anom_lag"] > 0]["spread"].median()
dry = bt[bt["hydro_anom_lag"] <= 0]["spread"].median()

# ---------------------------------------------------------------- write-up
b = reg.params["hydro_anom_gw"]; ci = reg.conf_int().loc["hydro_anom_gw"]
improve = 1 - fc_scores.loc["All", "MAE hydro model"] / fc_scores.loc["All", "MAE persistence"]
spring = month_profile.loc[[4, 5, 6], "spread"].mean()
winter = month_profile.loc[[11, 12, 1], "spread"].mean()
season_note = (
    "Counter-intuitively, Mid-C is *above* SP15 in the runoff months on average: CAISO solar crushes "
    "spring SP15 prices even harder than PNW hydro crushes Mid-C. Seasonality alone is the wrong "
    "signal. The hydro *anomaly* (wetter or drier than normal for the month) is what moves the spread."
    if spring > winter else
    "The spread is lowest in the runoff months, as the hydro story predicts.")
recent = yearly.loc[yearly.index >= 2023, "spread"].mean()
early = yearly.loc[yearly.index <= 2022, "spread"].mean()
structural = b < 0 and reg.pvalues["hydro_anom_gw"] < 0.05
verdict = ("**Supported** on the structural test" if structural else "**Not supported** on the structural test") + \
    (f", and the hydro signal improves next-day spread forecasts by {improve:.0%} over persistence."
     if improve > 0.02 else f", but it adds little to next-day forecasting ({improve:+.0%} vs persistence).")

report = f"""# T02 - The Mid-C vs SP15 spread is a hydro story

**Thesis.** The Mid-C minus SP15 on-peak spread is driven by Pacific Northwest hydro. Above-normal
BPA hydro pushes Mid-C further below SP15, and that signal is usable on the trade date.

**Verdict.** {verdict}

## Evidence

- **Seasonality:** median spread is {spring:+.1f} $/MWh in Apr-Jun (runoff) vs {winter:+.1f} in Nov-Jan.
  {season_note}
- **Regression** (controls: BPA wind and load, CAISO solar and load, gas, month and weekday fixed
  effects; HAC s.e.): each +1 GW of BPA hydro above its seasonal norm moves the spread by
  **{b:+.2f} $/MWh** (95% CI {ci[0]:+.2f} to {ci[1]:+.2f}), n={int(reg.nobs)}, R²={reg.rsquared:.2f}.
- **By hydro quintile:**

{by_bin[['anom', 'spread', 'p25', 'p75', 'days']].round(2).to_markdown()}

![](seasonal_spread.png)
![](spread_by_hydro.png)

## Year by year

{yearly.round(2).to_markdown()}

Regime shift: the median spread averaged {early:+.1f} $/MWh in 2019-2022 and {recent:+.1f} in 2023+.
Mid-C went from trading at a discount to SP15 to trading at a premium. Two likely drivers, not yet
separated: below-normal water in 2023-2025, and SP15's solar-driven decline (T01), with SP15
falling out from under Mid-C. Splitting the two is a good follow-up.

## Forecasting tomorrow's spread (walk-forward, trade-date information only)

{fc_scores.round(2).to_markdown()}

Days after an above-normal hydro day: median spread {wet:+.1f} $/MWh; after a below-normal day: {dry:+.1f}.

## Trade expression (hypothesis, not advice)

The Mid-C/SP15 spread is a relative-value position that strips out most of the shared western gas
exposure. A wet water year (high snowpack forecasts from NOAA's Northwest River Forecast Center
in Jan-Apr) argues for **long SP15 / short Mid-C on-peak for Q2**, with the position sized to the
hydro anomaly. Dry years argue for the opposite or flat.

## Caveats

- The seasonal norm is built from 2019-2026, a short and drought-heavy history.
- Transmission limits on the California-Oregon Intertie cap how far the spread can blow out,
  and their outages are not in EIA data.
- Both hubs share Henry Hub as the gas control; their *regional* gas prices (Sumas, SoCal) differ
  and are not available from EIA daily.
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
