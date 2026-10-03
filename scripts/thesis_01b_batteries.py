"""Thesis 01b - Are batteries blunting solar's marginal cannibalization at SP15?

T01 found that the within-year solar slope on SP15 heat rates has flattened since 2023.
Claim tested here: the flattening is explained by CAISO's battery fleet, which soaks up
midday solar and discharges into the evening ramp that sits inside the HE7-22 on-peak block.

Prediction if true: in   IHR ~ solar + battery + solar x battery,
the solar x battery term is POSITIVE (more storage -> each point of solar hurts less), and it
survives a competing solar x time trend.

Outputs land in reports/T01b_sp15_batteries/.
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
from powerml.data import caiso_storage
from powerml.features import build_panel

OUT = REPORTS / "T01b_sp15_batteries"
OUT.mkdir(parents=True, exist_ok=True)
HAC = dict(cov_type="HAC", cov_kwds={"maxlags": 5})
CONTROLS = "wind_pp + hydro_pp + demand_gw + C(month) + C(dow)"

df = build_panel("SP15").merge(caiso_storage(), on="date", how="left")
df = df.dropna(subset=["ihr", "solar_share", "demand_gw", "batt_fleet_gwh"])
df = df[df["year"] >= 2019]
lo, hi = df["ihr"].quantile([0.01, 0.99])
df = df.assign(
    ihr_w=df["ihr"].clip(lo, hi),
    solar_pp=df["solar_share"] * 100,
    wind_pp=df["wind_share"] * 100,
    hydro_pp=df["hydro_share"] * 100,
    # Battery fleet as % of daily demand, so it's comparable to the solar share.
    batt_pp=df["batt_fleet_gwh"] / (df["demand_gw"] * 24) * 100,
)


def fit(data, rhs):
    return smf.ols(f"ihr_w ~ {rhs} + {CONTROLS}", data).fit(**HAC)


def solar_effect(m, b):
    """Marginal effect of +10pp solar at battery level b (pp), with a delta-method s.e."""
    V = m.cov_params()
    eff = m.params["solar_pp"] + b * m.params["solar_pp:batt_pp"]
    var = V.loc["solar_pp", "solar_pp"] + b ** 2 * V.loc["solar_pp:batt_pp", "solar_pp:batt_pp"] \
        + 2 * b * V.loc["solar_pp", "solar_pp:batt_pp"]
    return eff * 10, np.sqrt(var) * 10


# ---------------------------------------------------------------- models
yr = smf.ols(f"ihr_w ~ solar_pp:C(year) + C(year) + {CONTROLS}", df).fit(**HAC)
slopes = pd.DataFrame({
    "year": [int(k.split("[")[1].rstrip("]")) for k in yr.params.index if k.startswith("solar_pp:")],
    "slope": [v * 10 for k, v in yr.params.items() if k.startswith("solar_pp:")],
    "se": [v * 10 for k, v in yr.bse.items() if k.startswith("solar_pp:")],
}).merge(df.groupby("year")["batt_pp"].mean().rename("batt_pp").reset_index(), on="year")

m_batt = fit(df, "solar_pp * batt_pp")
m_race = fit(df, "solar_pp * batt_pp + solar_pp:trend_yrs + trend_yrs")      # battery vs plain time
clean = df[~df["year"].isin([2022, 2023])]                                     # drop western gas crisis
m_clean = fit(clean, "solar_pp * batt_pp")


def row(name, m):
    k = "solar_pp:batt_pp"
    return {"model": name, "solar x battery": m.params[k], "s.e.": m.bse[k], "p-value": m.pvalues[k],
            "n": int(m.nobs), "R²": m.rsquared}


table = pd.DataFrame([
    row("Solar x battery", m_batt),
    row("+ solar x time trend", m_race),
    row("Excluding 2022-23", m_clean),
]).set_index("model")

# ---------------------------------------------------------------- chart: does the battery line explain the yearly dots?
grid = np.linspace(0, df["batt_pp"].max(), 50)
eff = np.array([solar_effect(m_batt, b) for b in grid])
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.plot(grid, eff[:, 0], color="#2c7fb8", label="Model: solar effect given battery fleet")
ax.fill_between(grid, eff[:, 0] - 1.96 * eff[:, 1], eff[:, 0] + 1.96 * eff[:, 1], color="#2c7fb8", alpha=0.2)
ax.errorbar(slopes["batt_pp"], slopes["slope"], yerr=1.96 * slopes["se"], fmt="o", color="#d95f0e",
            capsize=3, label="Estimated separately each year")
for _, r in slopes.iterrows():
    ax.annotate(int(r["year"]), (r["batt_pp"], r["slope"]), textcoords="offset points", xytext=(6, 4), fontsize=8)
ax.axhline(0, color="grey", lw=0.8)
ax.set_xlabel("Battery fleet (daily discharge capability, % of demand)")
ax.set_ylabel("Δ IHR per +10pp solar share")
ax.set_title("Does a bigger battery fleet weaken solar's price impact at SP15?")
ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(OUT / "solar_effect_vs_batteries.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(8, 3.5))
fleet = df.set_index("date")["batt_fleet_gwh"]
ax.plot(fleet.index, fleet.values, color="#2c7fb8")
ax.set_ylabel("GWh / day"); ax.set_title("CAISO battery fleet proxy (trailing 90-day P95 evening discharge)")
fig.tight_layout(); fig.savefig(OUT / "battery_fleet.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- write-up
k = "solar_pp:batt_pp"
b_now = df[df["year"] == df["year"].max()]["batt_pp"].mean()
e0, s0 = solar_effect(m_batt, 0)
e1, s1 = solar_effect(m_batt, b_now)
positive_everywhere = all(m.params[k] > 0 and m.pvalues[k] < 0.05 for m in (m_batt, m_race, m_clean))
positive_main = m_batt.params[k] > 0 and m_batt.pvalues[k] < 0.05
if positive_everywhere:
    verdict = ("**Supported.** The solar x battery term is positive and significant in all three "
               "specifications, including against a plain time trend and without the 2022-23 gas crisis.")
elif positive_main:
    verdict = ("**Partly supported.** The solar x battery term is positive in the main model but does not "
               "survive every robustness check, so batteries and other time-varying changes can't be fully separated yet.")
else:
    verdict = "**Not supported.** The solar x battery term is not positive and significant in the main model."

if positive_main:
    implication = """## Trade implication (hypothesis, not advice)

The short spring SP15 heat-rate view from T01 decays as storage grows. The useful forward
indicator is no longer solar build alone but **solar build minus storage build**. A year where
battery additions outpace solar is one where the cannibalization short should be smaller."""
else:
    implication = """## What this means

The flattening T01 saw is not explained by batteries. The per-year slopes are noisy, and the
steepest ones (2022-23) are the years Henry Hub most understated western gas, so the
"flattening" is largely the gas-crisis years falling out of the sample, not a trend.

There is also a structural reason batteries shouldn't show up here: the ICE on-peak product is
one average over HE7-22. A battery that charges at noon and discharges at 8pm moves energy
*within* that block, which lowers the evening price and raises the midday price but barely moves
the block average. Batteries should matter a lot for **intraday shape** (midday vs evening
spreads), which daily on-peak prices can't see.

## Trade implication (hypothesis, not advice)

T01's level effect stands: solar keeps pushing the spring on-peak heat rate down, and storage
build so far has not visibly slowed that at the daily-block level. Storage risk to the view
belongs in **shaped** products (evening ramp, super-peak), not the standard on-peak block.
Testing that needs hourly prices, which EIA doesn't publish; CAISO OASIS does, for free."""

report = f"""# T01b - Are batteries blunting solar cannibalization at SP15?

**Thesis.** CAISO's battery fleet absorbs midday solar and discharges into the evening ramp,
so each additional point of solar compresses the SP15 on-peak heat rate less than it used to.

**Verdict.** {verdict}

## How storage is measured

CAISO doesn't report batteries as their own EIA-930 fuel; they sit inside "Other". The hourly
shape gives them away: the "Other" series swings from roughly zero in 2019 to about
-7 GW at midday (charging) and +7.6 GW in the evening (discharging) in 2026. The fleet-size
proxy is the trailing 90-day 95th percentile of daily evening discharge. It measures what the
fleet *can* do, not what it did today, because batteries discharge more on high-price days and
using same-day dispatch would bias the result.

![](battery_fleet.png)

## Results

{table.round(4).to_markdown()}

- Solar's effect with **no batteries**: {e0:+.2f} MMBtu/MWh per +10pp solar (s.e. {s0:.2f}).
- At the **{int(df['year'].max())} battery fleet** ({b_now:.1f}% of demand): {e1:+.2f} (s.e. {s1:.2f}).

![](solar_effect_vs_batteries.png)

If batteries explain the flattening, the orange per-year dots should sit along the blue line.

{implication}

## Caveats

- Battery fleet growth and time are almost perfectly correlated, so "batteries" may be picking
  up anything else that changed steadily (new transmission, more exports, demand response).
  The solar x time-trend row is the test for that.
- "Other" also includes small non-storage resources, but its 2019 hourly profile is near zero,
  so the swing since then is dominated by storage.
- On-peak is a daily HE7-22 block, so this measures the blended effect, not midday vs evening.
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
