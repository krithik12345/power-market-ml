"""Thesis E3 - ERCOT batteries are shrinking evening real-time price spikes (the DA/RT spread).

Every hour clears twice: in the day-ahead market (DA) the day before, and in real time (RT).
DART = RT price - DA price. Virtual traders take positions on exactly this gap:
  * a "dec" (decrement) buys in DA and sells back in RT, so it profits when RT > DA;
  * an "inc" (increment) sells in DA and buys back in RT, so it profits when DA > RT.
(ERCOT allows the same trade through day-ahead energy-only offers and bids.)

Evening real-time spikes happen when the evening turns out tighter than the day-ahead market
expected: a wind lull, a forecast miss, a plant trip. Batteries respond in seconds, so a bigger
fleet should catch more of those surprises before they become RT spikes.

Claim: as ERCOT's battery fleet grew, evening RT spikes above DA became smaller and rarer.
Prediction: the evening upside DART (average of max(RT - DA, 0) over HE19-22, in heat-rate units)
falls with the battery fleet, holding the evening ramp, grid tightness, wind and season fixed;
and the effect survives a time trend and the 2023+ window.

Outputs land in reports/E3_ercot_dart/.
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
from powerml.ercot import EVENING, daily_panel, dam_hub_prices, rtm_hub_prices

OUT = REPORTS / "E3_ercot_dart"
OUT.mkdir(parents=True, exist_ok=True)
HAC = dict(cov_type="HAC", cov_kwds={"maxlags": 5})
HUB = "HB_HUBAVG"
CONTROLS = "ramp_gw + netload_peak_gw + wind_share + C(month) + C(dow)"

# ---------------------------------------------------------------- data: hourly DA vs RT
da = dam_hub_prices().query("point == @HUB")[["date", "he", "price"]].rename(columns={"price": "da"})
rt = rtm_hub_prices().query("point == @HUB")[["date", "he", "price"]].rename(columns={"price": "rt"})
h = da.merge(rt, on=["date", "he"])
h["dart"] = h["rt"] - h["da"]
h = h[~h["date"].between("2021-02-10", "2021-02-20")]          # Winter Storm Uri
h["year"] = h["date"].dt.year

eve = h[h["he"].isin(EVENING)]
day = eve.groupby("date").agg(dart_eve=("dart", "mean"),
                              up_eve=("dart", lambda s: s.clip(lower=0).mean()),   # RT spikes above DA only
                              spike_hours=("dart", lambda s: (s > 50).sum())).reset_index()
panel = daily_panel(HUB)
day = day.merge(panel, on="date").dropna(subset=["gas", "batt_fleet_gw", "ramp_gw"])
day = day[~day["uri"]].copy()
day["up_eve_hr"] = day["up_eve"] / day["gas"]                    # heat-rate units, like E2
lo, hi = day["up_eve_hr"].quantile([0.01, 0.99])
day["up_eve_w"] = day["up_eve_hr"].clip(lo, hi)

# ---------------------------------------------------------------- 1. the pattern
by_year = eve.groupby("year").agg(
    mean_dart=("dart", "mean"),
    p95_dart=("dart", lambda s: s.quantile(0.95)),
    share_rt_spike=("dart", lambda s: (s > 50).mean()),
    std_dart=("dart", "std"),
)
by_year = by_year.join(day.groupby("year")["batt_fleet_gw"].mean())
# "Always dec the evening": buy HE19-22 in DA, sell in RT. Average $/MWh earned per hour, before fees.
by_year["evening_dec_pnl"] = by_year["mean_dart"]

shape = h.pivot_table(index="he", columns="year", values="dart", aggfunc=lambda s: s.clip(lower=0).mean())
years = sorted(shape.columns)
cmap = plt.get_cmap("viridis", len(years))
fig, ax = plt.subplots(figsize=(9, 4.3))
for i, y in enumerate(years):
    ax.plot(shape.index, shape[y], color=cmap(i), lw=1.6, label=str(y))
ax.set_xlabel("Hour ending (Central)"); ax.set_ylabel("Average max(RT - DA, 0), $/MWh")
ax.set_xticks([1, 6, 12, 17, 20, 24]); ax.legend(fontsize=7, ncol=2)
ax.set_title("ERCOT: how much real time spikes above day-ahead, by hour")
fig.tight_layout(); fig.savefig(OUT / "rt_spikes_by_hour.png", dpi=150); plt.close(fig)

fig, ax1 = plt.subplots(figsize=(8.5, 4.2))
ax1.plot(by_year.index, by_year["share_rt_spike"] * 100, "o-", color="#8c2f2b", label="Evening hours with RT > DA + $50 (%)")
ax1.set_ylabel("% of evening hours")
ax2 = ax1.twinx()
ax2.bar(by_year.index, by_year["batt_fleet_gw"], alpha=0.25, color="#5a6b38", label="Battery fleet (GW)")
ax2.set_ylabel("GW")
ax1.set_zorder(ax2.get_zorder() + 1); ax1.patch.set_visible(False)
h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
ax1.set_title("Evening real-time spikes vs the battery fleet")
fig.tight_layout(); fig.savefig(OUT / "spikes_vs_fleet.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 2. regressions
def fit(data, rhs):
    return smf.ols(f"up_eve_w ~ {rhs} + {CONTROLS}", data).fit(**HAC)


m_main = fit(day, "batt_fleet_gw")
m_trend = fit(day, "batt_fleet_gw + trend_yrs")                       # battery vs plain time
m_ex22 = fit(day[day["year"] != 2022], "batt_fleet_gw")
m_post = fit(day[day["year"] >= 2023], "batt_fleet_gw")
# Tail check: the 90th percentile of evening upside, not just the average.
m_q90 = smf.quantreg(f"up_eve_w ~ batt_fleet_gw + {CONTROLS}", day).fit(q=0.9, max_iter=10000)

K = "batt_fleet_gw"
table = pd.DataFrame([
    {"model": "Main (OLS)", "battery (per GW)": m_main.params[K], "s.e.": m_main.bse[K], "p-value": m_main.pvalues[K], "n": int(m_main.nobs)},
    {"model": "+ time trend", "battery (per GW)": m_trend.params[K], "s.e.": m_trend.bse[K], "p-value": m_trend.pvalues[K], "n": int(m_trend.nobs)},
    {"model": "Excluding 2022", "battery (per GW)": m_ex22.params[K], "s.e.": m_ex22.bse[K], "p-value": m_ex22.pvalues[K], "n": int(m_ex22.nobs)},
    {"model": "2023+ only", "battery (per GW)": m_post.params[K], "s.e.": m_post.bse[K], "p-value": m_post.pvalues[K], "n": int(m_post.nobs)},
    {"model": "90th percentile (quantile reg.)", "battery (per GW)": m_q90.params[K], "s.e.": m_q90.bse[K], "p-value": m_q90.pvalues[K], "n": int(m_q90.nobs)},
]).set_index("model")

neg = (table["battery (per GW)"] < 0) & (table["p-value"] < 0.05)
if neg.all():
    verdict = "**Supported.** The battery coefficient is negative and significant in every specification, including the tail."
elif neg["Main (OLS)"] and neg.sum() >= 3:
    verdict = f"**Mostly supported.** Negative and significant in most specifications; not in: {', '.join(table.index[~neg])}."
elif neg["Main (OLS)"]:
    verdict = f"**Partly supported.** Negative in the main model but not in: {', '.join(table.index[~neg])}."
else:
    verdict = "**Not supported.** The battery coefficient is not negative and significant in the main model."

mean_gas = day.loc[day["year"] == day["year"].max(), "gas"].mean()
first_y, last_y = by_year.index.min(), by_year.index.max()
peak_y = by_year["std_dart"].idxmax()
story = (
    f"- **Day-ahead usually priced the evening above real time.** Average RT - DA was negative in "
    f"{int((by_year['mean_dart'] < 0).sum())} of {len(by_year)} years, so mechanically buying day-ahead and "
    f"selling in real time ('always dec') lost money on average.\n"
    f"- **That gap peaked in {peak_y} and has nearly closed:** {by_year.loc[peak_y, 'mean_dart']:+.2f} $/MWh "
    f"in {peak_y} vs {by_year.loc[last_y, 'mean_dart']:+.2f} in {last_y}.\n"
    f"- **Spikes got much smaller, but only somewhat rarer.** The spread of evening RT - DA (standard "
    f"deviation) fell from {by_year.loc[peak_y, 'std_dart']:.0f} to {by_year.loc[last_y, 'std_dart']:.0f} $/MWh, "
    f"while the share of hours with RT more than $50 above DA only went from "
    f"{by_year.loc[peak_y, 'share_rt_spike']:.1%} to {by_year.loc[last_y, 'share_rt_spike']:.1%}."
)
b = m_main.params[K]
bt = by_year.copy()
bt["share_rt_spike"] = (bt["share_rt_spike"] * 100).round(1).astype(str) + "%"

report = f"""# E3 - ERCOT batteries are shrinking evening real-time price spikes

**Thesis.** Evening real-time (RT) prices spike above day-ahead (DA) when the evening turns out
tighter than expected. Batteries respond in seconds, so a bigger fleet should absorb more of those
surprises: evening RT spikes above DA should get smaller as the fleet grows.

**Why it matters for trading.** The DA/RT gap (DART = RT - DA) is what virtual traders trade. A *dec*
(buy DA, sell RT) wins when RT spikes above DA; an *inc* (sell DA, buy RT) wins when it doesn't. If
batteries are removing evening RT spikes, the payoff to holding evening RT exposure changes.

**Verdict.** {verdict}

Data: ERCOT hourly DA prices and 15-minute RT prices (averaged to hourly) at {HUB}, 2019 on,
excluding Winter Storm Uri; battery fleet, ramp and controls from the E2 daily panel.

## 1. The pattern (evening hours, HE19-22)

{bt.round(2).to_markdown()}

- `mean_dart`: average RT - DA, $/MWh. This is also the per-MWh result of mechanically buying every
  evening hour in DA and selling in RT ("always dec"), before fees.
- `p95_dart`: the size of the worst 5% of RT surprises.
- `share_rt_spike`: how often RT came in more than $50 above DA.

![](rt_spikes_by_hour.png)
![](spikes_vs_fleet.png)

## 2. Regressions

Outcome: the day's evening upside DART, the average of max(RT - DA, 0) over HE19-22, divided by gas
(heat-rate units). Controls: evening ramp, net-load peak, wind share, month and weekday (HAC s.e.).

{table.round(4).to_markdown()}

Main model: each extra GW of battery fleet lowers evening upside DART by {abs(b):.3f} heat-rate units,
about ${abs(b) * mean_gas:.2f}/MWh at {int(day['year'].max())}'s average gas price.

## What the pattern says

{story}

## Trading implication (hypothesis, not advice)

Evening day-ahead prices used to carry an insurance premium: on average they cleared above real time,
because buyers paid up in day-ahead to avoid being exposed to rare, violent real-time spikes. Evening
incs (sell day-ahead, buy back in real time) collected that premium; evening decs were the insurance,
losing small amounts most days and paying off in the spikes. With storage absorbing the spikes, the
insurance is worth less and the market has priced that in: the premium has nearly disappeared. A
virtual book built on 2022-2023 evening behavior would expect a premium and a tail that are no longer
there.

## Caveats

- **Fees and collateral are ignored.** Real virtual trades carry ERCOT fees and credit costs that
  would eat into the small average spreads.
- **Hourly averages smooth 15-minute spikes.** The sharpest RT spikes last one or two intervals.
- **Battery growth tracks time.** The time-trend and 2023+ rows check this, but other things also
  improved, such as forecasting and ERCOT's new ancillary products (ECRS from mid-2023).
- **Same ERCOT battery-measure seam as E2** (EIA's reporting change in Nov 2024).
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
