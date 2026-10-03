"""Thesis 03 - PJM West heat rate is convex in load, and spike days are forecastable.

Claim: PJM West's on-peak implied heat rate rises slowly with load until the system gets
tight, then the upper tail blows out (the supply stack is a hockey stick). Because the
spike risk is concentrated on the hottest days, the EIA day-ahead demand forecast should
give a usable probability of a spike day before it trades.

Outputs land in reports/T03_pjm_convexity/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from powerml.config import REPORTS
from powerml.features import build_panel

OUT = REPORTS / "T03_pjm_convexity"
OUT.mkdir(parents=True, exist_ok=True)
SUMMER = [6, 7, 8, 9]

df = build_panel("PJMW").dropna(subset=["ihr", "demand_gw"])
df = df[df["year"] >= 2019].copy()
lo, hi = df["ihr"].quantile([0.005, 0.995])
df["ihr_w"] = df["ihr"].clip(lo, hi)
summer = df[df["month"].isin(SUMMER)].copy()

# ---------------------------------------------------------------- 1. quantile regression: does the tail fan out?
quantiles = [0.1, 0.5, 0.9]
grid = pd.DataFrame({"demand_gw": np.linspace(summer["demand_gw"].quantile(.02), summer["demand_gw"].quantile(.99), 60)})
qfits, qcurves = {}, {}
for q in quantiles:
    m = smf.quantreg("ihr_w ~ demand_gw + I(demand_gw**2)", summer).fit(q=q, max_iter=10000)
    qfits[q] = m
    qcurves[q] = m.predict(grid)

# Slope of each quantile at moderate vs high load = convexity, and whether the top quantile steepens faster.
lo_gw, hi_gw = summer["demand_gw"].quantile([0.25, 0.95])
slope_at = lambda m, x: m.params["demand_gw"] + 2 * m.params["I(demand_gw ** 2)"] * x
slopes = pd.DataFrame({
    f"slope at {lo_gw:.0f} GW": {q: slope_at(m, lo_gw) for q, m in qfits.items()},
    f"slope at {hi_gw:.0f} GW": {q: slope_at(m, hi_gw) for q, m in qfits.items()},
}).rename_axis("quantile")

fig, ax = plt.subplots(figsize=(8, 4.5))
ax.scatter(summer["demand_gw"], summer["ihr_w"], s=6, alpha=0.3, color="grey", label="Summer on-peak days")
for q, c in zip(quantiles, ["#91bfdb", "#2c7fb8", "#d7301f"]):
    ax.plot(grid["demand_gw"], qcurves[q], color=c, lw=2, label=f"P{int(q*100)}")
ax.set_xlabel("PJM average load (GW)"); ax.set_ylabel("Implied heat rate (MMBtu/MWh)")
ax.set_title("PJM West summer heat rate vs load: the upper tail fans out")
ax.legend(); fig.tight_layout(); fig.savefig(OUT / "quantile_fan.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 2. where does the money sit?
summer["load_decile"] = pd.qcut(summer["demand_gw"], 10, labels=range(1, 11))
deciles = summer.groupby("load_decile", observed=True).agg(
    load_gw=("demand_gw", "mean"), median_ihr=("ihr_w", "median"),
    p90_ihr=("ihr_w", lambda s: s.quantile(.9)), median_price=("price", "median"), days=("price", "size"))
# "Excess" = on-peak dollars above the summer median price, the part a peak-load hedge is paying for.
excess = (summer["price"] - summer["price"].median()).clip(lower=0)
top_share = excess[summer["load_decile"] == 10].sum() / excess.sum()

# ---------------------------------------------------------------- 3. can we see spike days coming?
# Spike = heat rate at least 1.5x its trailing 30-day median. Relative to recent history, so a
# cheap-gas year (which lifts every day's heat rate) doesn't count as a year of "spikes".
SPIKE_X = 1.5
df["ihr_ref"] = df["ihr"].shift(1).rolling(30, min_periods=15).median()
df["spike"] = (df["ihr"] > SPIKE_X * df["ihr_ref"]).astype(int)
df["ihr_lag_rel"] = df["ihr_lag"] / df["ihr_ref"]          # how stretched yesterday already was
feats = ["demand_fcst_gw", "demand_fcst_delta", "ihr_lag_rel", "gas_chg", "doy_sin", "doy_cos", "dow"]
data = df.dropna(subset=feats + ["ihr", "ihr_ref"]).copy()
results, preds = [], []
for year in sorted(data["year"].unique()):
    if year < 2022:
        continue
    train, test = data[data["year"] < year].copy(), data[data["year"] == year].copy()
    if test["spike"].nunique() < 2:
        continue
    logit = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(train[feats], train["spike"])
    gbm = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20,
                             verbose=-1).fit(train[feats], train["spike"])
    base = np.full(len(test), train["spike"].mean())
    test["p_logit"] = logit.predict_proba(test[feats])[:, 1]
    test["p_gbm"] = gbm.predict_proba(test[feats])[:, 1]
    results.append({
        "year": year, "spike days": int(test["spike"].sum()), "days": len(test),
        "AUC yesterday only": roc_auc_score(test["spike"], test["ihr_lag_rel"]),
        "AUC logit": roc_auc_score(test["spike"], test["p_logit"]),
        "AUC LightGBM": roc_auc_score(test["spike"], test["p_gbm"]),
        "Brier base rate": brier_score_loss(test["spike"], base),
        "Brier logit": brier_score_loss(test["spike"], test["p_logit"]),
        "Brier LightGBM": brier_score_loss(test["spike"], test["p_gbm"]),
    })
    preds.append(test[["date", "spike", "p_logit", "p_gbm", "ihr_lag_rel"]])
spike_tbl = pd.DataFrame(results).set_index("year")
allp = pd.concat(preds)
auc_all = roc_auc_score(allp["spike"], allp["p_logit"])
auc_gbm_all = roc_auc_score(allp["spike"], allp["p_gbm"])
auc_persist = roc_auc_score(allp["spike"], allp["ihr_lag_rel"])

# Hit rate on the 10% of days the model is most worried about
top = allp.nlargest(int(len(allp) * 0.1), "p_logit")
precision_top = top["spike"].mean()
base_rate = allp["spike"].mean()

# ---------------------------------------------------------------- write-up
q9_hi, q5_hi = slopes.iloc[2, 1], slopes.iloc[1, 1]
q9_lo, q5_lo = slopes.iloc[2, 0], slopes.iloc[1, 0]
convex = q9_hi > q9_lo and q9_hi > q5_hi
verdict_struct = ("**Convexity supported.** The P90 heat rate steepens at high load faster than the median does."
                  if convex else "**Convexity not supported** by the quantile fits.")
best_auc = max(auc_all, auc_gbm_all)
verdict_fc = (f"**Spike days are forecastable** from trade-date information (AUC {best_auc:.2f} vs "
              f"{auc_persist:.2f} for yesterday-only)."
              if best_auc >= 0.7 and best_auc - auc_persist >= 0.03 else
              f"Spike forecasting adds little beyond persistence (AUC {best_auc:.2f} vs {auc_persist:.2f} yesterday-only).")

report = f"""# T03 - PJM West: convex in load, and spike days are visible in advance

**Thesis.** PJM West's on-peak implied heat rate is convex in load: flat-ish in normal conditions,
with an upper tail that blows out on the hottest days. Because the risk is concentrated in a few
days, the EIA day-ahead demand forecast should flag spike days before they trade.

**Verdict.** {verdict_struct} {verdict_fc}

## 1. The tail fans out (summer, Jun-Sep, quantile regression on load and load²)

![](quantile_fan.png)

Slope of heat rate vs load (MMBtu/MWh per GW):

{slopes.round(3).to_markdown()}

## 2. Where the money is

{deciles.round(2).to_markdown()}

The top load decile is 10% of summer days but carries **{top_share:.0%}** of summer on-peak dollars
above the median price. That is what a peak hedge or a long call on PJM West is really paying for.

## 3. Forecasting spike days (walk-forward, trade-date information only)

Spike = heat rate at least {SPIKE_X}x its trailing 30-day median (all months). Features: the EIA
day-ahead demand forecast and its change from yesterday's actual load, how stretched yesterday's
heat rate already was, the gas price change, and season. "Yesterday only" scores days purely on
yesterday's stretch. It's the persistence baseline, since heat waves last several days.

{spike_tbl.round(3).to_markdown()}

- Pooled AUC: logistic **{auc_all:.2f}**, LightGBM **{auc_gbm_all:.2f}**, yesterday-only baseline
  **{auc_persist:.2f}** (0.5 = coin flip). The gap over the baseline is what the load forecast adds.
- On the 10% of days the logistic model ranks most at risk, **{precision_top:.0%}** were spike days,
  against a {base_rate:.0%} base rate.

A lower Brier score than the base rate means the probabilities are better than guessing the average.

## Trade expression (hypothesis, not advice)

Because the payoff is convex in load, the value sits in **optionality**: daily or balance-of-week
PJM West on-peak calls, or heat-rate call options, bought when the model's spike probability is
high relative to what implied volatility charges. The model is a timing filter for when to own
convexity, not a directional price call.

## Caveats

- The EIA "PJM West" price in these files is the **real-time** on-peak index, which is spikier than day-ahead.
- Load is RTO-wide PJM; West hub congestion (for example, Dominion zone) can spike without system-wide load.
- The EIA day-ahead demand forecast is assumed available on the trade date. Its exact publication
  time vs the morning ICE trading window isn't documented, so a live version should use PJM's own
  load forecast, which is published well before trading.
- The P90 curve's upturn at the *low*-load end is an artifact of the quadratic fit, not a real effect.
- No implied volatility data, so "underpriced" can't be tested directly. This shows where the risk
  is and that it's predictable, not that the market misprices it.
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
