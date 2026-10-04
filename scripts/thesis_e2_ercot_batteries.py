"""Thesis E2 - ERCOT's battery fleet is flattening the evening price premium.

This is the test T01b could not run. T01b found no battery effect on CAISO's DAILY on-peak price
and argued that batteries act on the SHAPE of the day (charge at noon, discharge at 8pm), which a
daily block price can't see. ERCOT publishes hourly prices, so the shape is visible here.

Claim: the evening premium (HE19-22 price minus HE10-15 price, in heat-rate units) is driven up
by the size of the evening net-load ramp, and a bigger battery fleet makes each GW of ramp cost
less. Prediction: ramp coefficient > 0, battery coefficient < 0, ramp x battery < 0, and this
survives a competing ramp x time trend.

Outputs land in reports/E2_ercot_batteries/.
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
from powerml.ercot import daily_panel

OUT = REPORTS / "E2_ercot_batteries"
OUT.mkdir(parents=True, exist_ok=True)
HAC = dict(cov_type="HAC", cov_kwds={"maxlags": 5})
CONTROLS = "netload_peak_gw + wind_share + C(month) + C(dow)"

day = daily_panel("HB_HUBAVG")
day = day[~day["uri"]].dropna(subset=["price_eve", "price_mid", "gas", "ramp_gw", "batt_fleet_gw"]).copy()
day["premium"] = (day["price_eve"] - day["price_mid"]) / day["gas"]       # MMBtu/MWh
lo, hi = day["premium"].quantile([0.01, 0.99])
day["premium_w"] = day["premium"].clip(lo, hi)

# ---------------------------------------------------------------- 1. the stylized fact
yearly = day.groupby("year").agg(
    premium=("premium_w", "median"), ramp_gw=("ramp_gw", "mean"),
    batt_fleet_gw=("batt_fleet_gw", "mean"), solar_share=("solar_share", "mean"))
yearly["premium_per_gw_ramp"] = yearly["premium"] / yearly["ramp_gw"]

fig, ax1 = plt.subplots(figsize=(8.5, 4.3))
ax1.plot(yearly.index, yearly["premium"], "o-", color="#8c2f2b", label="Median evening premium (heat-rate units)")
ax1.set_ylabel("Evening minus midday price / gas")
ax2 = ax1.twinx()
ax2.bar(yearly.index, yearly["batt_fleet_gw"], alpha=0.25, color="#5a6b38", label="Battery fleet proxy (GW)")
ax2.plot(yearly.index, yearly["ramp_gw"], "s--", color="#6b625a", label="Evening net-load ramp (GW)")
ax2.set_ylabel("GW")
ax1.set_zorder(ax2.get_zorder() + 1); ax1.patch.set_visible(False)
h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
ax1.set_title("ERCOT: the ramp keeps growing, the evening premium doesn't")
fig.tight_layout(); fig.savefig(OUT / "premium_vs_fleet.png", dpi=150); plt.close(fig)

fleet = day.set_index("date")["batt_fleet_gw"]
fig, ax = plt.subplots(figsize=(8.5, 3.3))
ax.plot(fleet.index, fleet.values, color="#5a6b38")
ax.axvline(pd.Timestamp("2024-11-06"), color="grey", ls=":", lw=0.8)
ax.text(pd.Timestamp("2024-11-20"), fleet.max() * 0.08, "EIA starts reporting BAT", fontsize=7, color="grey")
ax.set_ylabel("GW"); ax.set_title("ERCOT battery fleet proxy (trailing 90-day P95 evening discharge)")
fig.tight_layout(); fig.savefig(OUT / "battery_fleet.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 2. regressions
def fit(data, rhs):
    return smf.ols(f"premium_w ~ {rhs} + {CONTROLS}", data).fit(**HAC)


m_base = fit(day, "ramp_gw + batt_fleet_gw")
m_int = fit(day, "ramp_gw * batt_fleet_gw")
m_race = fit(day, "ramp_gw * batt_fleet_gw + ramp_gw:trend_yrs + trend_yrs")
m_ex22 = fit(day[day["year"] != 2022], "ramp_gw * batt_fleet_gw")           # 2022: gas at $6-9
m_post = fit(day[day["year"] >= 2023], "ramp_gw * batt_fleet_gw")           # only the battery build-out years

K = "ramp_gw:batt_fleet_gw"


def row(name, m):
    return {"model": name, "ramp (per GW)": m.params["ramp_gw"],
            "battery (per GW)": m.params["batt_fleet_gw"],
            "ramp x battery": m.params.get(K, np.nan), "s.e.": m.bse.get(K, np.nan),
            "p-value": m.pvalues.get(K, np.nan), "n": int(m.nobs), "R²": m.rsquared}


table = pd.DataFrame([row("No interaction", m_base), row("Ramp x battery", m_int),
                      row("+ ramp x time trend", m_race), row("Excluding 2022", m_ex22),
                      row("2023+ only", m_post)]).set_index("model")


def ramp_effect(m, b):
    """Premium per extra GW of ramp at battery fleet b (GW), with delta-method s.e."""
    V = m.cov_params()
    eff = m.params["ramp_gw"] + b * m.params[K]
    var = V.loc["ramp_gw", "ramp_gw"] + b ** 2 * V.loc[K, K] + 2 * b * V.loc["ramp_gw", K]
    return eff, np.sqrt(var)


# Per-year ramp slope, to plot against the battery fleet (same picture as T01b)
yr = smf.ols(f"premium_w ~ ramp_gw:C(year) + C(year) + {CONTROLS}", day).fit(**HAC)
slopes = pd.DataFrame({
    "year": [int(k.split("[")[1].rstrip("]")) for k in yr.params.index if k.startswith("ramp_gw:")],
    "slope": [v for k, v in yr.params.items() if k.startswith("ramp_gw:")],
    "se": [v for k, v in yr.bse.items() if k.startswith("ramp_gw:")],
}).merge(yearly["batt_fleet_gw"].reset_index(), on="year")

grid = np.linspace(0, day["batt_fleet_gw"].max(), 50)
eff = np.array([ramp_effect(m_int, b) for b in grid])
fig, ax = plt.subplots(figsize=(8.5, 4.5))
ax.plot(grid, eff[:, 0], color="#5a6b38", label="Model: ramp effect given battery fleet")
ax.fill_between(grid, eff[:, 0] - 1.96 * eff[:, 1], eff[:, 0] + 1.96 * eff[:, 1], color="#5a6b38", alpha=0.18)
ax.errorbar(slopes["batt_fleet_gw"], slopes["slope"], yerr=1.96 * slopes["se"], fmt="o", color="#8c2f2b",
            capsize=3, label="Estimated separately each year")
for _, r in slopes.iterrows():
    ax.annotate(int(r["year"]), (r["batt_fleet_gw"], r["slope"]), textcoords="offset points", xytext=(6, 4), fontsize=8)
ax.axhline(0, color="grey", lw=0.8)
ax.set_xlabel("Battery fleet proxy (GW)"); ax.set_ylabel("Extra evening premium per GW of ramp")
ax.set_title("Does a bigger battery fleet make the evening ramp cheaper?")
ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(OUT / "ramp_effect_vs_batteries.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- write-up
neg = lambda m: m.params[K] < 0 and m.pvalues[K] < 0.05
checks = {"main": neg(m_int), "vs time trend": neg(m_race), "ex-2022": neg(m_ex22), "2023+": neg(m_post)}
if all(checks.values()):
    verdict = ("**Supported, with a caution.** The ramp x battery term is negative and significant in every "
               "specification, including against a competing ramp x time trend. The caution: the evidence really comes "
               "from 2023 onward, which is only four years (see 'Reading the per-year picture').")
elif checks["main"] and sum(checks.values()) >= 3:
    failed = ", ".join(k for k, v in checks.items() if not v)
    verdict = (f"**Mostly supported.** The ramp x battery term is negative and significant in most specifications; "
               f"it does not hold in: {failed}.")
elif checks["main"]:
    failed = ", ".join(k for k, v in checks.items() if not v)
    verdict = (f"**Partly supported.** Negative and significant in the main model, but not in: {failed}. Batteries and "
               "other steady changes over time can't be fully separated yet.")
else:
    verdict = "**Not supported.** The ramp x battery term is not negative and significant in the main model."

b_last = yearly["batt_fleet_gw"].iloc[-1]
e0, s0 = ramp_effect(m_int, 0)
e1, s1 = ramp_effect(m_int, b_last)
peak = yearly["premium"].idxmax()
sl = slopes.set_index("year")["slope"]
pre = sl[sl.index <= 2022].mean()
s23, last_year = sl.get(2023, np.nan), int(sl.index.max())
slast = sl.loc[last_year]
b23 = yearly.loc[2023, "batt_fleet_gw"]
post_k, post_p = m_post.params[K], m_post.pvalues[K]
race_ramp = m_race.params["ramp_gw"]

report = f"""# E2 - ERCOT's battery fleet is flattening the evening price premium

**Thesis.** The evening premium (HE19-22 price minus HE10-15 price, divided by gas) is driven by how
steeply net load climbs after sunset. A bigger battery fleet, charging on midday solar and discharging
into the ramp, should make each GW of ramp cost less.

**Why this test exists.** T01b found no battery effect on CAISO's *daily* on-peak price and argued that
batteries act on the shape of the day, which a single daily block price can't show. ERCOT publishes
hourly prices, so here the shape is visible.

**Verdict.** {verdict}

## The pattern

{yearly.round(2).to_markdown()}

The ramp roughly {yearly['ramp_gw'].iloc[-1] / yearly['ramp_gw'].iloc[0]:.1f}x'd since {yearly.index[0]}, yet the median
premium peaked in {peak} and has fallen since, as the battery fleet grew from {yearly.loc[peak, 'batt_fleet_gw']:.1f} to
{b_last:.1f} GW.

![](premium_vs_fleet.png)

## How the battery fleet is measured

EIA-930 shows ERCOT storage in two different ways over time. Until November 2024 it appears only as
evening *discharge* inside the "Other" category (charging is netted into demand). From November 2024,
EIA reports a separate battery series that shows charging too. Evening discharge is visible in both,
so the proxy is the day's peak evening storage output above the overnight baseline, taken as a
trailing 90-day 95th percentile and lagged a day. That measures what the fleet *can* do, which today's
prices can't influence, the same reverse-causality fix used in T01b.

![](battery_fleet.png)

## Regressions (HAC s.e.; controls: net-load peak, wind share, month and weekday fixed effects)

{table.round(4).to_markdown()}

- Extra premium per GW of ramp with **no batteries**: {e0:+.3f} (s.e. {s0:.3f}).
- At the **{int(yearly.index[-1])} fleet** ({b_last:.1f} GW): {e1:+.3f} (s.e. {s1:.3f}).

![](ramp_effect_vs_batteries.png)

## Reading the per-year picture

The per-year dots don't sit on one straight line, and that is informative:

- **2019-2022 (ramp slope {pre:+.2f} on average):** the evening ramp didn't drive the evening premium at all.
  E1 shows why: the most expensive hour was still HE17, so the evening wasn't where scarcity lived yet.
- **2023 ({s23:+.2f} per GW):** solar pushed the net-load peak into the evening and the ramp suddenly became the
  price-setter. Each GW of ramp was expensive and there were few batteries to meet it.
- **2023 to {last_year} ({s23:+.2f} -> {slast:+.2f} per GW):** the ramp kept growing, but each GW of it cost
  steadily less as the fleet grew from {b23:.1f} to {b_last:.1f} GW.

So the claim really rests on the 2023-onward window (the "2023+ only" row: {post_k:+.3f}, p = {post_p:.4f}). That's
strong within those years, but it is four years of a single build-out, during which other things also changed.

One warning sign in the table: adding a ramp x time trend flips the plain ramp coefficient to
{race_ramp:+.2f}, which isn't physically sensible on its own. That happens when two regressors (battery fleet and
time) move almost together; the model can't cleanly split credit between them. The battery interaction stays
negative and significant, but treat its exact size in that row with suspicion.

## Trade expression (hypothesis, not advice)

E1 showed ERCOT scarcity moved to the evening. E2 says that evening premium is now being competed away by
storage. Evening-shaped positions (long HE19-22 vs midday) priced off 2023's spreads are too rich if the
battery build continues; the forward indicator is **battery GW added relative to the growth in the evening
ramp**. For a battery developer, it's the classic cannibalization loop: every new battery earns less
from the spread the previous ones already narrowed.

## Caveats

- The battery proxy changes source in November 2024 (from "Other" to a dedicated BAT series). The chart
  shows no obvious jump there, but it is a seam in the data.
- Battery fleet size grows steadily over time, so it is hard to separate from anything else that grew
  steadily (more gas peakers, demand response, transmission). The time-trend row is the check.
- Day-ahead prices only. Batteries also earn heavily in real-time and ancillary services, which this ignores.
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
