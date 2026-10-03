"""Thesis 01 - Solar cannibalization at SP15.

Claim: As CAISO solar penetration grows, the SP15 on-peak implied heat rate (power / gas)
falls, the effect is concentrated in spring, and the per-unit effect is getting stronger.

Outputs land in reports/T01_sp15_solar/.
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
from sklearn.inspection import partial_dependence

from powerml.config import REPORTS
from powerml.features import build_panel
from powerml.models import GBM

OUT = REPORTS / "T01_sp15_solar"
OUT.mkdir(parents=True, exist_ok=True)
SPRING = [3, 4, 5]

df = build_panel("SP15").dropna(subset=["ihr", "solar_share", "demand_gw"])
df = df[df["year"] >= 2019]
lo, hi = df["ihr"].quantile([0.01, 0.99])
df["ihr_w"] = df["ihr"].clip(lo, hi)  # Henry Hub understates western gas in crises (e.g. Dec-2022)

# ---------------------------------------------------------------- 1. the stylized fact
by_year = df.groupby("year").agg(
    ihr=("ihr_w", "median"), solar=("solar_share", "mean"), days=("ihr", "size"))
spring = df[df["month"].isin(SPRING)].groupby("year").agg(
    spring_ihr=("ihr_w", "median"), spring_solar=("solar_share", "mean"))
summary = by_year.join(spring)
heat = df.pivot_table(index="year", columns="month", values="ihr_w", aggfunc="median")

fig, ax1 = plt.subplots(figsize=(8, 4.5))
ax1.plot(summary.index, summary["spring_ihr"], "o-", color="#c0392b", label="Spring median IHR")
ax1.plot(summary.index, summary["ihr"], "o--", color="#e67e22", alpha=0.7, label="All-year median IHR")
ax1.set_ylabel("Implied heat rate (MMBtu/MWh)")
ax2 = ax1.twinx()
ax2.bar(summary.index, summary["spring_solar"] * 100, alpha=0.25, color="#f1c40f", label="Spring solar share")
ax2.set_ylabel("Solar share of demand (%)")
ax1.set_zorder(ax2.get_zorder() + 1); ax1.patch.set_visible(False)
ax1.legend(loc="upper left"); ax2.legend(loc="upper right")
ax1.set_title("SP15 on-peak implied heat rate vs CAISO solar share")
fig.tight_layout(); fig.savefig(OUT / "ihr_vs_solar.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(9, 4))
im = ax.imshow(heat.values, aspect="auto", cmap="RdYlBu_r")
ax.set_xticks(range(12), [pd.Timestamp(2000, m, 1).strftime("%b") for m in heat.columns])
ax.set_yticks(range(len(heat)), heat.index)
for i in range(heat.shape[0]):
    for j in range(heat.shape[1]):
        v = heat.values[i, j]
        if np.isfinite(v):
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=7)
fig.colorbar(im, label="Median IHR"); ax.set_title("SP15 median on-peak implied heat rate by month")
fig.tight_layout(); fig.savefig(OUT / "ihr_heatmap.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 2. structural regression
# Shares are in percentage points so coefficients read "MMBtu/MWh per +1pp of share".
reg = df.assign(solar_pp=df["solar_share"] * 100, wind_pp=df["wind_share"] * 100,
                hydro_pp=df["hydro_share"] * 100)
base = smf.ols("ihr_w ~ solar_pp + wind_pp + hydro_pp + demand_gw + C(month) + C(dow)", reg) \
    .fit(cov_type="HAC", cov_kwds={"maxlags": 5})
by_yr = smf.ols("ihr_w ~ solar_pp:C(year) + C(year) + wind_pp + hydro_pp + demand_gw + C(month) + C(dow)", reg) \
    .fit(cov_type="HAC", cov_kwds={"maxlags": 5})
slopes = pd.DataFrame({
    "year": [int(k.split("[")[1].rstrip("]")) for k in by_yr.params.index if k.startswith("solar_pp:")],
    "coef": [v for k, v in by_yr.params.items() if k.startswith("solar_pp:")],
    "se": [v for k, v in by_yr.bse.items() if k.startswith("solar_pp:")],
})

fig, ax = plt.subplots(figsize=(7, 4))
ax.errorbar(slopes["year"], slopes["coef"] * 10, yerr=1.96 * slopes["se"] * 10, fmt="o", capsize=4)
ax.axhline(0, color="grey", lw=0.8)
ax.set_ylabel("Δ IHR per +10pp solar share"); ax.set_title("Solar's marginal effect on SP15 heat rate, by year (95% CI)")
fig.tight_layout(); fig.savefig(OUT / "solar_slope_by_year.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 3. nonlinear check (GBM)
feats = ["solar_share", "wind_share", "hydro_share", "demand_gw", "doy_sin", "doy_cos", "dow", "trend_yrs"]
gbm = GBM(feats).fit(df, df["ihr_w"])
pd_res = partial_dependence(gbm.model, df[feats], ["solar_share"], grid_resolution=30)
grid, curve = pd_res["grid_values"][0], pd_res["average"][0]
fig, ax = plt.subplots(figsize=(7, 4))
ax.plot(grid * 100, curve)
ax.set_xlabel("Solar share of demand (%)"); ax.set_ylabel("Partial dependence: IHR")
ax.set_title("GBM partial dependence - is cannibalization nonlinear?")
fig.tight_layout(); fig.savefig(OUT / "gbm_partial_dependence.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 4. write-up
b = base.params["solar_pp"] * 10
ci = base.conf_int().loc["solar_pp"] * 10
first, last = slopes.iloc[0], slopes.iloc[-1]
trend = np.polyfit(slopes["year"], slopes["coef"] * 10, 1)[0]
steepening = trend < 0
verdict = (
    "**steepening** - each point of solar is doing more damage than it used to, consistent with saturation."
    if steepening else
    "**flattening** - the *level* of cannibalization keeps rising with penetration, but the marginal "
    "point of solar now bites less. The leading suspect is battery storage shifting midday solar into "
    "the evening ramp, which supports on-peak prices. That is thesis T01b."
)
s0, s1 = summary.iloc[0], summary.iloc[-1]
report = f"""# T01 - Solar cannibalization at SP15

**Thesis.** Rising CAISO solar penetration is compressing the SP15 on-peak implied heat rate,
most visibly in spring. Open question tested below: is each extra point of solar worth *more*
compression over time (saturation) or *less* (storage absorbing the midday surplus)?

## Evidence

| | {int(summary.index[0])} | {int(summary.index[-1])} |
|---|---|---|
| Median on-peak IHR (MMBtu/MWh) | {s0['ihr']:.1f} | {s1['ihr']:.1f} |
| Spring median IHR | {s0['spring_ihr']:.1f} | {s1['spring_ihr']:.1f} |
| Spring solar share of demand | {s0['spring_solar']:.0%} | {s1['spring_solar']:.0%} |

- **Pooled regression** (month + weekday fixed effects, controls for wind, hydro, demand; HAC s.e.):
  +10pp solar share -> **{b:+.2f} MMBtu/MWh** IHR (95% CI {ci[0]:+.2f} to {ci[1]:+.2f}), n={int(base.nobs)}, R²={base.rsquared:.2f}.
- **Slope by year**: {int(first['year'])}: {first['coef']*10:+.2f} -> {int(last['year'])}: {last['coef']*10:+.2f} per +10pp
  (linear trend {trend:+.2f}/yr). The marginal effect is {verdict}
- The pooled slope is much larger than any single year's because it also absorbs the
  *between-year* drop in IHR as the fleet changed. The by-year slopes isolate the within-year effect.
- **Nonlinearity**: GBM partial dependence moves from {curve[0]:.1f} at {grid[0]:.0%} solar to {curve[-1]:.1f} at {grid[-1]:.0%}.

![](ihr_vs_solar.png)
![](ihr_heatmap.png)
![](solar_slope_by_year.png)
![](gbm_partial_dependence.png)

## Trade expression (hypothesis, not advice)

The level effect argues for structurally lower spring SP15 on-peak heat rates than history implies:
short spring on-peak heat rate (short SP15 power / long gas) when the solar build is on schedule
and hydro is normal-to-wet. The flattening slope is the risk to that view: if storage keeps
absorbing the midday surplus, the *next* GW of solar compresses heat rates less than the last,
and the short gets less attractive each year. Size accordingly.

## Caveats

- On-peak is HE7-22, which straddles the solar trough and the evening ramp; the daily ICE
  product blends both, so true midday cannibalization is larger than shown here.
- Henry Hub, not SoCal Citygate, is the gas denominator. Western gas basis blew out in winter
  2022-23, so IHR is winsorized at the 1st/99th percentile ({lo:.1f}-{hi:.1f}). The 2022-23 slopes
  (and the 2023 IHR spike) are inflated by that basis blowout, which flatters the "flattening" story;
  rerun with 2022-23 excluded before leaning on it.
- Next test (T01b): add EIA-930 battery discharge (fuel type BAT) as a regressor and an
  interaction with solar share. If storage explains the flattening, the solar x battery
  term should be positive and the residual year-trend should disappear.
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
print(base.summary().tables[1])
