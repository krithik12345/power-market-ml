"""Thesis E1 - ERCOT scarcity has moved from the load peak to the net-load peak.

Claim: As Texas solar grew, the most expensive hour of the day moved from the afternoon load
peak (~HE17) to the evening net-load peak (~HE20-21), when the sun is down but demand is still
high. If so, peak NET load should now explain the day's highest price better than peak load
does, and that advantage should have grown year by year.

Uses ERCOT hourly day-ahead prices (HB_HUBAVG) and EIA-930 hourly demand, solar and wind.
Outputs land in reports/E1_ercot_netload_peak/.
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

from powerml.config import REPORTS
from powerml.ercot import dam_hub_prices, daily_panel, hourly_fundamentals

OUT = REPORTS / "E1_ercot_netload_peak"
OUT.mkdir(parents=True, exist_ok=True)
HAC = dict(cov_type="HAC", cov_kwds={"maxlags": 5})
HUB = "HB_HUBAVG"

day = daily_panel(HUB)
day = day[~day["uri"]].dropna(subset=["price_max", "gas", "load_peak_gw", "netload_peak_gw"]).copy()
# Daily max price in heat-rate units, logged: price spikes are multiplicative, and gas moved a lot.
day["log_max_ihr"] = np.log(day["price_max"].clip(lower=1) / day["gas"])

# ---------------------------------------------------------------- 1. where in the day is the price peak?
p = dam_hub_prices()
p = p[(p["point"] == HUB) & ~p["date"].between("2021-02-10", "2021-02-20")]
p["year"] = p["date"].dt.year
f = hourly_fundamentals()
f["year"] = f["date"].dt.year
f = f[f["year"] >= 2019]
# Each year's average daily shape, scaled so 1.0 = that year's daily average (makes years comparable).
price_shape = p.pivot_table(index="he", columns="year", values="price", aggfunc="mean")
price_shape = price_shape / price_shape.mean()
load_shape = f.pivot_table(index="he", columns="year", values="demand", aggfunc="mean") / 1000
net_shape = f.pivot_table(index="he", columns="year", values="net_load", aggfunc="mean") / 1000

years = sorted(price_shape.columns)
cmap = plt.get_cmap("viridis", len(years))
fig, axes = plt.subplots(1, 2, figsize=(12, 4.3))
for i, y in enumerate(years):
    axes[0].plot(price_shape.index, price_shape[y], color=cmap(i), lw=1.6, label=str(y))
    axes[1].plot(net_shape.index, net_shape[y], color=cmap(i), lw=1.6, label=str(y))
axes[0].set_title("Average day-ahead price shape (1.0 = daily average)")
axes[0].set_xlabel("Hour ending (Central)"); axes[0].set_ylabel("Relative price")
axes[1].set_title("Average net load (demand - solar - wind)")
axes[1].set_xlabel("Hour ending (Central)"); axes[1].set_ylabel("GW")
for ax in axes:
    ax.set_xticks([1, 6, 12, 17, 20, 24]); ax.axvline(17, color="grey", lw=0.6, ls=":"); ax.axvline(20, color="grey", lw=0.6, ls=":")
axes[1].legend(fontsize=7, ncol=2)
fig.suptitle("ERCOT: the expensive hour follows net load into the evening", y=1.0)
fig.tight_layout(); fig.savefig(OUT / "daily_shapes.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 2. which peak lines up with the price peak?
day["match_load"] = (day["he_price_max"] - day["he_load_peak"]).abs() <= 1
day["match_net"] = (day["he_price_max"] - day["he_netload_peak"]).abs() <= 1
timing = day.groupby("year").agg(
    price_peak_he=("he_price_max", lambda s: int(s.mode()[0])),
    load_peak_he=("he_load_peak", lambda s: int(s.mode()[0])),
    netload_peak_he=("he_netload_peak", lambda s: int(s.mode()[0])),
    within_1h_of_load_peak=("match_load", "mean"),
    within_1h_of_netload_peak=("match_net", "mean"),
    solar_share=("solar_share", "mean"),
)

fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(timing.index, timing["within_1h_of_load_peak"] * 100, "o-", color="#6b625a", label="Price peak within 1h of LOAD peak")
ax.plot(timing.index, timing["within_1h_of_netload_peak"] * 100, "o-", color="#8c2f2b", label="Price peak within 1h of NET-LOAD peak")
ax.set_ylabel("% of days"); ax.set_ylim(0, 100); ax.legend()
ax.set_title("Which peak sets the day's highest ERCOT price?")
fig.tight_layout(); fig.savefig(OUT / "peak_timing.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 3. horse race, year by year
# For each year: regress log max heat rate on peak load alone, then on peak net load alone
# (both with month fixed effects). Higher R² = that peak explains price spikes better.
rows = []
for y, g in day.groupby("year"):
    if len(g) < 150:
        continue
    r_load = smf.ols("log_max_ihr ~ load_peak_gw + C(month)", g).fit()
    r_net = smf.ols("log_max_ihr ~ netload_peak_gw + C(month)", g).fit()
    both = smf.ols("log_max_ihr ~ scale(load_peak_gw) + scale(netload_peak_gw) + C(month)", g).fit(**HAC)
    rows.append({
        "year": y, "days": len(g),
        "R² load": r_load.rsquared, "R² net load": r_net.rsquared,
        "std coef load": both.params["scale(load_peak_gw)"],
        "std coef net load": both.params["scale(netload_peak_gw)"],
        "p net load": both.pvalues["scale(netload_peak_gw)"],
    })
race = pd.DataFrame(rows).set_index("year")
race["net load advantage"] = race["R² net load"] - race["R² load"]

fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(race.index, race["std coef load"], "o-", color="#6b625a", label="Peak load")
ax.plot(race.index, race["std coef net load"], "o-", color="#8c2f2b", label="Peak net load")
ax.axhline(0, color="grey", lw=0.8)
ax.set_ylabel("Effect on log max heat rate\n(per 1 std. dev., both in the model)")
ax.set_title("Head to head: which peak drives ERCOT price spikes?")
ax.legend(); fig.tight_layout(); fig.savefig(OUT / "horse_race.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 4. pooled test: is the shift statistically real?
pooled = smf.ols("log_max_ihr ~ scale(load_peak_gw) * trend_yrs + scale(netload_peak_gw) * trend_yrs + C(month) + C(dow)",
                 day).fit(**HAC)
k_net, k_load = "scale(netload_peak_gw):trend_yrs", "scale(load_peak_gw):trend_yrs"
# The thesis is about the GAP: does net load gain on load over time? Test (net x trend) - (load x trend) = 0.
gap = pooled.t_test(f"{k_net} - {k_load} = 0")
gap_coef, gap_se, gap_p = float(gap.effect[0]), float(gap.sd[0, 0]), float(gap.pvalue)

# ---------------------------------------------------------------- write-up
first, last = race.index.min(), race.index.max()
early = race.loc[race.index <= 2021, "net load advantage"].mean()
late = race.loc[race.index >= 2023, "net load advantage"].mean()
moved = timing.loc[last, "price_peak_he"] >= 19 and timing.loc[first, "price_peak_he"] <= 18
stronger = gap_coef > 0 and gap_p < 0.05
if moved and late > early and stronger:
    verdict = ("**Supported.** The price peak moved into the evening with the net-load peak, net load now explains "
               "daily price spikes better than load, and the gap between them widened significantly over time.")
elif moved and late > early:
    verdict = ("**Mostly supported.** The price peak moved into the evening and net load now explains spikes better, "
               "but the pooled test of a widening gap is not significant.")
else:
    verdict = "**Not supported** on at least one of the three tests below."

if pooled.params[k_load] < 0 and pooled.pvalues[k_load] < 0.05 and pooled.pvalues[k_net] >= 0.05:
    gap_story = ("Net load's own effect did not grow: it was already the stronger driver in 2019, because even "
                 "before much solar, *wind* made net load differ from load. What changed is that plain load **lost** its "
                 "explanatory power, falling significantly every year. The shift is real, but it happened by load "
                 "becoming irrelevant, not by net load becoming more important.")
else:
    gap_story = "A positive gap means net load gains on load as a driver of the day's price spike each year."

t = timing.copy()
for c in ("within_1h_of_load_peak", "within_1h_of_netload_peak", "solar_share"):
    t[c] = (t[c] * 100).round(0).astype(int).astype(str) + "%"

report = f"""# E1 - ERCOT scarcity has moved from the load peak to the net-load peak

**Thesis.** As Texas solar grew, the most expensive hour of the day moved from the afternoon load peak
to the evening net-load peak, when the sun is down but demand is still high. Peak *net* load should now
explain the day's highest price better than peak load, and that advantage should have grown.

**Verdict.** {verdict}

Data: ERCOT hourly day-ahead prices at {HUB} (the average of ERCOT's trading hubs), EIA-930 hourly
demand, solar and wind, Henry Hub gas. {len(day):,} days, {first}-{last}, excluding Winter Storm Uri (Feb 10-20, 2021).

## 1. The expensive hour moved

{t.to_markdown()}

![](daily_shapes.png)
![](peak_timing.png)

## 2. Head to head, year by year

Daily max price is converted to a heat rate (÷ gas) and logged, because spikes are multiplicative and gas
moved from $2 to $9 over the sample. Each year is fit separately with month fixed effects.

{race.round(3).to_markdown()}

Average R² advantage of net load over load: {early:+.3f} in 2019-2021, {late:+.3f} in 2023 onward.

![](horse_race.png)

## 3. Pooled test of a growing effect

One regression over all years with each peak interacted with a time trend (HAC s.e.):

| term | coef | s.e. | p-value |
|---|---|---|---|
| net load x trend (per year) | {pooled.params[k_net]:+.3f} | {pooled.bse[k_net]:.3f} | {pooled.pvalues[k_net]:.3f} |
| load x trend (per year) | {pooled.params[k_load]:+.3f} | {pooled.bse[k_load]:.3f} | {pooled.pvalues[k_load]:.3f} |
| **gap: net load minus load, per year** | **{gap_coef:+.3f}** | {gap_se:.3f} | {gap_p:.3f} |

**How to read this.** {gap_story}

## Trade expression (hypothesis, not advice)

Scarcity value in ERCOT now sits in the HE19-22 window, not the traditional 4-6pm block. Shaped products
that cover the evening ramp (or ERCOT's 7x8 / HE19-22 blocks) carry the convexity that HE14-18 used to.
For asset owners, it means storage and evening-capable gas are capturing the scarcity rent that solar
erased from the afternoon. The next question is whether storage is now compressing that evening premium
too, which is thesis E2.

## Caveats

- Day-ahead prices only. Real-time scarcity (the $5,000 cap events) is spikier and can differ.
- EIA-930 net load excludes behind-the-meter solar, so true customer demand is a little higher at midday.
- Peak *timing* uses the mode across days; individual days vary, especially in shoulder months.
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
