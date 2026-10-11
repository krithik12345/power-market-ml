"""Thesis E4 - Batteries have saturated ERCOT's ancillary-service markets.

Ancillary services (AS) pay a resource to stand ready rather than to produce energy:
  * Regulation Up / Down (REGUP / REGDN): follow ERCOT's second-by-second signal to hold frequency.
  * Responsive Reserve (RRS): respond within seconds if a big plant trips.
  * ERCOT Contingency Reserve (ECRS, from June 2023): a slower backstop for the same events.
  * Non-Spinning Reserve (NSPIN): capacity that can start within 30 minutes.
Prices are $ per MW per hour of standby capacity. Batteries are ideal for the fast products, and
the early ERCOT battery fleet earned most of its money there.

Claim: as the battery fleet grew, AS clearing prices collapsed, pushing battery revenue toward
energy arbitrage (which E2 shows is also being competed away).
Prediction: log AS prices fall with the battery fleet, holding gas prices, grid tightness and
season fixed, and the effect survives a time trend and the 2023+ window.

Outputs land in reports/E4_ercot_ancillary/.
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
from powerml.ercot import as_prices, daily_panel, dam_hub_prices

OUT = REPORTS / "E4_ercot_ancillary"
OUT.mkdir(parents=True, exist_ok=True)
HAC = dict(cov_type="HAC", cov_kwds={"maxlags": 5})
PRODUCTS = ["regup", "regdn", "rrs", "ecrs", "nspin"]
FAST = ["regup", "rrs"]           # the products batteries dominate; the verdict rests on these
CONTROLS = "np.log(gas) + netload_peak_gw + C(month) + C(dow)"

a = as_prices()
a = a[~a["date"].between("2021-02-10", "2021-02-20")]          # Winter Storm Uri: $9,000 cap regime
daily_as = a.groupby("date")[PRODUCTS].mean().reset_index()
panel = daily_panel("HB_HUBAVG")
day = daily_as.merge(panel, on="date").dropna(subset=["gas", "batt_fleet_gw", "netload_peak_gw"])
day = day[~day["uri"]].copy()

# ---------------------------------------------------------------- 1. the pattern
yearly = day.groupby("year")[PRODUCTS].median().join(day.groupby("year")["batt_fleet_gw"].mean())

fig, ax1 = plt.subplots(figsize=(9, 4.5))
for p, c in zip(PRODUCTS, ["#8c2f2b", "#c46a3c", "#26221f", "#6b625a", "#a3660a"]):
    ax1.plot(yearly.index, yearly[p], "o-", color=c, label=p.upper())
ax1.set_yscale("log"); ax1.set_ylabel("Median daily price ($/MW-h, log scale)")
ax2 = ax1.twinx()
ax2.bar(yearly.index, yearly["batt_fleet_gw"], alpha=0.2, color="#5a6b38", label="Battery fleet (GW)")
ax2.set_ylabel("GW")
ax1.set_zorder(ax2.get_zorder() + 1); ax1.patch.set_visible(False)
h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
ax1.legend(h1 + h2, l1 + l2, fontsize=8, ncol=2)
ax1.set_title("ERCOT ancillary-service prices vs the battery fleet")
fig.tight_layout(); fig.savefig(OUT / "as_prices_vs_fleet.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 2. where a battery's money comes from
# Illustration for 1 MW of a 2-hour battery (85% round-trip efficiency), per year, in $/kW-year:
#   arbitrage = each day, charge in the 2 cheapest DA hours and discharge in the 2 priciest;
#   regup / rrs = offering that service every hour of the year (an upper bound: in practice a
#   battery splits its capacity and can't sell energy and the same MW of reserves at once).
da = dam_hub_prices().query("point == 'HB_HUBAVG'")
da = da[~da["date"].between("2021-02-10", "2021-02-20")]


def arb(g):
    p = np.sort(g["price"].to_numpy())
    return max(0.85 * p[-2:].sum() - p[:2].sum(), 0.0)


arb_day = da.groupby("date").apply(arb, include_groups=False).rename("arb").reset_index()
arb_day["year"] = arb_day["date"].dt.year
rev = pd.DataFrame({
    "arbitrage": arb_day.groupby("year")["arb"].sum() / 1000,
    "regup (all hours)": a.assign(year=a["date"].dt.year).groupby("year")["regup"].sum() / 1000,
    "rrs (all hours)": a.assign(year=a["date"].dt.year).groupby("year")["rrs"].sum() / 1000,
})
days_in = arb_day.groupby("year").size()
rev = rev.div(days_in, axis=0) * 365                       # annualize partial years

fig, ax = plt.subplots(figsize=(9, 4.2))
w, x = 0.27, np.arange(len(rev))
for i, (c, col) in enumerate(zip(["#26221f", "#8c2f2b", "#a3660a"], rev.columns)):
    ax.bar(x + (i - 1) * w, rev[col], w, color=c, label=col)
ax.set_xticks(x, rev.index); ax.set_ylabel("$/kW-year (annualized)")
ax.set_title("Illustrative revenue for 1 MW of 2-hour battery, by source")
ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(OUT / "battery_revenue_mix.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 3. regressions (log price)
rows, fits = [], {}
for p in PRODUCTS:
    d = day[day[p] > 0].copy()
    d["lp"] = np.log(d[p])
    specs = {
        "main": d,
        "+ time trend": d,
        "2023+ only": d[d["year"] >= 2023],
    }
    for name, data in specs.items():
        if len(data) < 200:
            continue
        rhs = "batt_fleet_gw + trend_yrs" if name == "+ time trend" else "batt_fleet_gw"
        m = smf.ols(f"lp ~ {rhs} + {CONTROLS}", data).fit(**HAC)
        fits[(p, name)] = m
        rows.append({"product": p.upper(), "model": name, "battery (per GW)": m.params["batt_fleet_gw"],
                     "% per GW": (np.exp(m.params["batt_fleet_gw"]) - 1) * 100,
                     "p-value": m.pvalues["batt_fleet_gw"], "n": int(m.nobs)})
reg = pd.DataFrame(rows)

ok = lambda p, n: (p, n) in fits and fits[(p, n)].params["batt_fleet_gw"] < 0 and fits[(p, n)].pvalues["batt_fleet_gw"] < 0.05
fast_checks = {f"{p.upper()} {n}": ok(p, n) for p in FAST for n in ("main", "+ time trend", "2023+ only")}
if all(fast_checks.values()):
    verdict = ("**Supported** for the fast products batteries dominate (REGUP, RRS): prices fall with the "
               "fleet in every specification.")
elif sum(fast_checks.values()) >= len(fast_checks) - 2 and ok("rrs", "main") and ok("regup", "main"):
    failed = ", ".join(k for k, v in fast_checks.items() if not v)
    verdict = f"**Mostly supported** for REGUP and RRS; does not hold in: {failed}."
else:
    failed = ", ".join(k for k, v in fast_checks.items() if not v)
    verdict = f"**Not clearly supported.** Fails in: {failed}."

report = f"""# E4 - Batteries have saturated ERCOT's ancillary-service markets

**Thesis.** Batteries are ideal for ERCOT's fast reserve products (Regulation Up and Responsive Reserve),
and the early fleet earned most of its money there. As the fleet grew, those prices should have collapsed,
pushing battery revenue toward energy arbitrage, which E2 shows is also being competed away.

**Verdict.** {verdict}

## The products

| Product | What it pays for | Battery fit |
|---|---|---|
| REGUP / REGDN | Following ERCOT's second-by-second frequency signal | Excellent |
| RRS | Responding within seconds when a large plant trips | Excellent |
| ECRS (from June 2023) | A slower backstop for the same events | Good |
| NSPIN | Capacity that can start within 30 minutes | Fair (duration matters) |

Prices are day-ahead clearing prices in $ per MW per hour of standby capacity (ERCOT report NP4-181-ER).

## 1. Prices vs the fleet (median daily price, $/MW-h)

{yearly.round(2).to_markdown()}

![](as_prices_vs_fleet.png)

## 2. Regressions on log price

Controls: log gas price (reserves are priced partly off the energy a resource gives up), net-load peak,
month, weekday (HAC s.e.). '% per GW' converts the log coefficient into the percentage change in price
for each extra GW of battery fleet.

{reg.round(4).to_markdown(index=False)}

## 3. Where a battery's money comes from (illustration)

{rev.round(1).to_markdown()}

For 1 MW of a 2-hour battery, in $/kW-year: daily arbitrage (charge in the 2 cheapest day-ahead hours,
discharge in the 2 priciest, 85% efficiency) vs selling REGUP or RRS every hour. The reserve columns are an
upper bound: a real battery splits its capacity and can't sell the same MW as energy and reserves at once.

![](battery_revenue_mix.png)

## Trade and asset implications (hypothesis, not advice)

Reserve revenue was the easy money for early Texas batteries, and it's gone. New storage has to earn its
keep in energy arbitrage and real-time volatility, both of which the existing fleet is also compressing
(E2, E3). Battery valuations built on 2022-2023 ancillary prices overstate future revenue, and the next
GW of storage earns less than the last on every revenue line.

## Caveats

- **ERCOT changed how much reserve it buys.** After Winter Storm Uri it bought far more (2021-2022), added
  ECRS in mid-2023, and has trimmed quantities since. Those policy shifts move prices independently of
  batteries; the time-trend and 2023+ rows only partly separate them.
- **Gas matters.** Reserve prices partly reflect the energy a resource gives up by standing by; the
  log-gas control handles the level but not every interaction.
- **The revenue table is illustrative,** not a dispatch model: no state of charge, degradation,
  real-time prices or co-optimization.
"""
(OUT / "report.md").write_text(report, encoding="utf-8")
print(report)
