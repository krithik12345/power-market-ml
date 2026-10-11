"""Thesis D1 - Storage is reshaping the duck curve, and CAISO is further along than ERCOT.

The "duck curve" is the daily shape of net load (demand minus solar and wind): a deep midday
belly when solar peaks, then a steep evening neck when the sun sets but demand is still high.
Batteries charge in the belly and discharge into the neck, so the load that thermal plants
actually have to follow - the RESIDUAL load, net load minus storage output - should have a
flatter neck than net load itself.

Claim, in three testable parts:
  1. In both markets, storage is shaving a growing share of the evening net-load ramp.
  2. CAISO, which built storage earlier, is further along than ERCOT.
  3. Evening prices respond to the residual (storage-adjusted) ramp, not the raw ramp:
     once storage matters, the residual ramp explains the evening premium better.

Data: CAISO's own 5-minute load and fuel mix (via gridstatus; batteries reported directly) and
EIA-930 hourly data for ERCOT (2019+); hourly day-ahead prices from ERCOT (HB_HUBAVG, 2019+) and
CAISO OASIS (SP15, mid-2023+ only). EIA-930's CAISO hourly series is NOT used: its timestamps
drift by up to 1.5 hours between mid-2022 and 2025 (see the report's caveats).
Outputs land in reports/D1_duck_curve/.
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

from powerml import caiso, ercot
from powerml.config import REPORTS
from powerml.data import henry_hub, hourly_grid

OUT = REPORTS / "D1_duck_curve"
OUT.mkdir(parents=True, exist_ok=True)
MARKETS = ("CAISO", "ERCOT")
BELLY, NECK = range(9, 17), range(17, 24)         # midday trough window, evening peak window
MIDDAY, EVENING = range(10, 16), range(19, 23)    # price windows (same as E2)


def daily_shape(h: pd.DataFrame) -> pd.DataFrame:
    """Collapse hourly grid data to one row per day of duck-curve measurements (GW)."""
    h = h.assign(residual=h["net_load"] - h["storage"])
    belly, neck = h[h["he"].isin(BELLY)], h[h["he"].isin(NECK)]
    g = h.groupby("date")
    d = pd.DataFrame({
        "hours": g.size(),
        "demand_peak": g["demand"].max() / 1000,
        "belly_net": belly.groupby("date")["net_load"].min() / 1000,
        "neck_net": neck.groupby("date")["net_load"].max() / 1000,
        "belly_res": belly.groupby("date")["residual"].min() / 1000,
        "neck_res": neck.groupby("date")["residual"].max() / 1000,
        "solar_share": g["solar"].sum() / g["demand"].sum(),
    })
    d["ramp_net"] = d["neck_net"] - d["belly_net"]      # the duck's neck, before storage
    d["ramp_res"] = d["neck_res"] - d["belly_res"]      # the neck thermal plants actually face
    # Belly depth: how far midday net load sinks relative to the day's peak demand (0 = no belly).
    d["belly_depth"] = 1 - d["belly_net"] / d["demand_peak"]
    return d[d["hours"] >= 23].reset_index()


# ---------------------------------------------------------------- 1. grid shapes, both markets
hourly, days = {}, {}
GRIDS = {"CAISO": caiso.hourly_grid, "ERCOT": lambda: hourly_grid("ERCO", "US/Central")}
for m in MARKETS:
    h = GRIDS[m]()
    h = h[h["date"] >= "2019-01-01"]
    hourly[m] = h
    days[m] = daily_shape(h).assign(market=m, year=lambda x: x["date"].dt.year)

yearly = []
for m, d in days.items():
    y = d.groupby("year").agg(ramp_net=("ramp_net", "mean"), ramp_res=("ramp_res", "mean"),
                              belly_depth=("belly_depth", "mean"), solar_share=("solar_share", "mean"))
    y["storage_shave"] = 1 - y["ramp_res"] / y["ramp_net"]   # share of the neck absorbed by storage
    yearly.append(y.assign(market=m).reset_index())
yearly = pd.concat(yearly)

years = sorted(set(hourly["CAISO"]["date"].dt.year))
cmap = plt.get_cmap("viridis", len(years))
fig, axes = plt.subplots(2, 2, figsize=(12, 7.5), sharex=True)
for col, m in enumerate(MARKETS):
    h = hourly[m].assign(year=hourly[m]["date"].dt.year, residual=hourly[m]["net_load"] - hourly[m]["storage"])
    net = h.pivot_table(index="he", columns="year", values="net_load", aggfunc="mean") / 1000
    res = h.pivot_table(index="he", columns="year", values="residual", aggfunc="mean") / 1000
    for i, y in enumerate(years):
        if y in net:
            axes[0, col].plot(net.index, net[y], color=cmap(i), lw=1.6, label=str(y))
            axes[1, col].plot(res.index, res[y], color=cmap(i), lw=1.6, label=str(y))
    axes[0, col].set_title(f"{m}: net load (demand - solar - wind)")
    axes[1, col].set_title(f"{m}: residual load (net load - storage output)")
    for r in (0, 1):
        axes[r, col].set_ylabel("GW"); axes[r, col].set_xticks([1, 6, 12, 17, 20, 24])
axes[1, 0].set_xlabel("Hour ending (local)"); axes[1, 1].set_xlabel("Hour ending (local)")
axes[0, 1].legend(fontsize=7, ncol=2)
fig.suptitle("The duck curve, before and after storage", y=1.0)
fig.tight_layout(); fig.savefig(OUT / "duck_evolution.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(8.5, 4.3))
for m, c in (("CAISO", "#8c2f2b"), ("ERCOT", "#5a6b38")):
    y = yearly[yearly["market"] == m]
    ax.plot(y["year"], y["ramp_net"], "o-", color=c, label=f"{m} net-load ramp")
    ax.plot(y["year"], y["ramp_res"], "o--", color=c, alpha=0.6, label=f"{m} after storage")
ax.set_ylabel("Average evening ramp (GW)"); ax.legend(fontsize=8)
ax.set_title("The duck's neck: raw vs storage-adjusted evening ramp")
fig.tight_layout(); fig.savefig(OUT / "ramp_vs_residual.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 2. prices: which ramp do they follow?
gas = henry_hub()


def premium_days(prices: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    """Daily evening premium (heat-rate units) joined to that market's daily duck measurements."""
    mid = prices[prices["he"].isin(MIDDAY)].groupby("date")["price"].mean()
    eve = prices[prices["he"].isin(EVENING)].groupby("date")["price"].mean()
    p = pd.DataFrame({"mid": mid, "eve": eve}).dropna().reset_index()
    p["trade_date"] = p["date"] - pd.Timedelta("1D")       # day-ahead trades the prior day
    p = pd.merge_asof(p.sort_values("trade_date"), gas.sort_values("trade_date"), on="trade_date",
                      direction="backward", tolerance=pd.Timedelta("5D"))
    p["premium"] = (p["eve"] - p["mid"]) / p["gas"]
    p = p.merge(d, on="date").dropna(subset=["premium"])
    lo, hi = p["premium"].quantile([0.01, 0.99])
    p["premium_w"] = p["premium"].clip(lo, hi)
    p["month"], p["dow"] = p["date"].dt.month, p["date"].dt.dayofweek
    return p[~p["date"].between("2021-02-10", "2021-02-20")]   # Winter Storm Uri


ep = ercot.dam_hub_prices()
prem = {"ERCOT": premium_days(ep[ep["point"] == "HB_HUBAVG"], days["ERCOT"])}
try:
    prem["CAISO"] = premium_days(caiso.dam_hub_prices(), days["CAISO"])
except Exception as e:                                       # OASIS down: run ERCOT-only
    print("CAISO prices unavailable:", e)

# Horse race per market and year: does the evening premium follow the raw ramp or the residual
# ramp? Same controls in both; compare R² (higher = better single explanation).
race = []
for m, p in prem.items():
    for y, g in p.groupby("year"):
        if len(g) < 120:
            continue
        r_net = smf.ols("premium_w ~ ramp_net + demand_peak + C(month) + C(dow)", g).fit()
        r_res = smf.ols("premium_w ~ ramp_res + demand_peak + C(month) + C(dow)", g).fit()
        race.append({"market": m, "year": y, "days": len(g), "R² raw ramp": r_net.rsquared,
                     "R² residual ramp": r_res.rsquared})
race = pd.DataFrame(race)
race["residual advantage"] = race["R² residual ramp"] - race["R² raw ramp"]

fig, ax = plt.subplots(figsize=(8.5, 4))
for m, c in (("CAISO", "#8c2f2b"), ("ERCOT", "#5a6b38")):
    r = race[race["market"] == m]
    ax.plot(r["year"], r["residual advantage"], "o-", color=c, label=m)
ax.axhline(0, color="grey", lw=0.8)
ax.set_ylabel("R² residual ramp minus R² raw ramp")
ax.set_title("Do evening prices follow the storage-adjusted ramp?")
ax.legend(); fig.tight_layout(); fig.savefig(OUT / "which_ramp_prices_follow.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- write-up
yl = yearly.set_index(["market", "year"])
last = int(yearly["year"].max())
shave = {m: yl.loc[m]["storage_shave"] for m in MARKETS}
grows = {m: shave[m].iloc[-1] - shave[m].iloc[0] > 0.05 for m in MARKETS}
ahead = shave["CAISO"].iloc[-1] > shave["ERCOT"].iloc[-1]
recent = race[race["year"] >= last - 1]
follows = {m: bool((recent[recent["market"] == m]["residual advantage"] > 0).all()) for m in prem}
part1, part2, part3 = grows["CAISO"] and grows["ERCOT"], ahead, all(follows.values())
says = lambda ok: "supported" if ok else "not supported"
verdict = (f"Part 1 (storage shaving a growing share of the ramp): **{says(part1)}**. "
           f"Part 2 (CAISO further along): **{says(part2)}**. "
           f"Part 3 (prices follow the storage-adjusted ramp): **{says(part3)}**"
           + ("" if part3 else ", but that test is biased against the idea; see section 2") + ".")

ytab = yearly.copy()
for c in ("storage_shave", "belly_depth", "solar_share"):
    ytab[c] = (ytab[c] * 100).round(0).astype(int).astype(str) + "%"
ytab = ytab.set_index(["market", "year"])[["solar_share", "belly_depth", "ramp_net", "ramp_res", "storage_shave"]]

report = f"""# D1 - Storage is reshaping the duck curve, and CAISO is further along than ERCOT

**Thesis.** In both CAISO and ERCOT, batteries are absorbing a growing share of the evening
net-load ramp (the duck's neck). CAISO, which built storage earlier, is further along. And once
storage matters, evening prices follow the storage-adjusted ramp rather than the raw one.

**Verdict.** {verdict}

## How the duck is measured

- **Net load** = demand - solar - wind, hourly, local time (CAISO's own data for CAISO, EIA-930 for ERCOT).
- **Residual load** = net load - storage output. It's what gas plants and imports actually have to
  follow. CAISO reports battery charging and discharging directly in its own fuel-mix data. For ERCOT,
  storage comes from EIA-930's 'Other' and 'Battery' series, the same way as E2.
- **Evening ramp** = the day's evening (HE17-23) peak minus its midday (HE9-16) trough, in GW,
  computed separately for net load and residual load.
- **Storage shave** = the share of the net-load ramp that storage removes: 1 - residual ramp / net ramp.
- **Belly depth** = how far midday net load sinks below the day's peak demand. Above 100% means
  midday solar and wind exceeded demand that day, so the surplus had to be exported, stored or curtailed.

## 1. The duck, year by year

{ytab.round(2).to_markdown()}

Part 1 (storage shave growing): CAISO {'yes' if grows['CAISO'] else 'no'}
({shave['CAISO'].iloc[0]:.0%} -> {shave['CAISO'].iloc[-1]:.0%}), ERCOT {'yes' if grows['ERCOT'] else 'no'}
({shave['ERCOT'].iloc[0]:.0%} -> {shave['ERCOT'].iloc[-1]:.0%}).
Part 2 (CAISO further along in {last}): {'yes' if ahead else 'no'}.

![](duck_evolution.png)
![](ramp_vs_residual.png)

## 2. Which ramp do evening prices follow?

Evening premium = (HE19-22 price - HE10-15 price) / Henry Hub, as in E2. For each market and year, two
regressions with the same controls (peak demand, month, weekday): one on the raw net-load ramp, one on
the residual ramp. A positive 'residual advantage' means the storage-adjusted ramp explains prices better.

{race.round(3).to_markdown(index=False)}

Part 3 (residual ramp explains prices better in the two most recent years):
{', '.join(f'{m} {"yes" if v else "no"}' for m, v in follows.items())}.

**Why this test is biased, and what to trust instead.** Residual load subtracts what batteries actually
did that day, and batteries discharge *more* on days when evening prices are high, because that's when
it pays. So on the most expensive evenings the residual ramp looks smaller than it would otherwise,
which weakens its link to price. Same-day dispatch is partly *caused by* the premium it's being used to
explain: the reverse-causality problem E2 avoided by measuring fleet *capability* instead. The clean
version of this question is E2 (and, for real-time spikes, E3), not this R² comparison. Part 3 is kept
here because it's an instructive way for a test to mislead.

![](which_ramp_prices_follow.png)

## Trade and asset implications (hypothesis, not advice)

The duck's neck is what sets evening scarcity prices, but the neck that matters is the one left
*after* storage. Forecasting evening prices off gross solar build overstates the ramp in both
markets, and by more in CAISO. The useful forward indicator is the residual ramp: solar and load
growth minus the storage fleet's discharge capability. CAISO is a preview of where ERCOT's evening
shape is heading.

## Caveats

- **CAISO hourly prices only go back to mid-2023** in the free CAISO archive (OASIS keeps about three
  years). Earlier CAISO years are covered for the grid shape but not for part 3. Gridstatus's
  historical archive would fill that gap.
- **ERCOT storage reporting changed in Nov 2024.** Before that, EIA shows only evening discharge
  (charging is netted into demand); after, a separate battery series with charging. Residual load is
  computed consistently with each regime's accounting, but it is a seam in the data.
- **Why CAISO's own data instead of EIA's.** EIA-930's hourly CAISO series has a timing error: its
  solar output peaks about an hour too late from mid-2022 through 2025, which would bend the duck.
  CAISO's published fuel mix doesn't have the problem. ERCOT's EIA timing was checked the same way and
  is stable (solar centered at hour-ending 13.8-14.1 every year).
- For ERCOT, 'Other' includes small non-storage resources, which slightly blurs the storage measure.
- Imports matter a lot in CAISO (the Pacific Northwest and Southwest), and net load as defined here ignores them.
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
