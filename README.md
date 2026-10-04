# Heat Rate Lab: testing power-market theses with EIA and ERCOT data

An ML research project that turns free public EIA and ERCOT data into **testable power-trading theses**.
Each thesis is stated as a falsifiable claim, tested with interpretable and nonlinear models,
and written up with a trade expression and the evidence that would kill it.

The core move is to model the **implied market heat rate** (on-peak power price ÷ gas price,
MMBtu/MWh) instead of raw $/MWh. That strips out the gas level, which otherwise dominates every
power regression, and isolates what the grid itself is doing: solar, wind, hydro, load.

**New to power markets or to the methods here?** Start with the
[learning guide (PDF)](docs/Power_Market_ML_Learning_Guide.pdf). It teaches every concept used in the repo
(supply stacks, heat rates, look-ahead bias, HAC errors, quantile regression, walk-forward backtests and more),
ties each one to the code and the results, and ends with review questions. Rebuild it with
`python docs/build_guide.py` (needs `reportlab`).

## Data (all public, all free)

| Source | What | Granularity |
|---|---|---|
| [EIA wholesale markets (ICE)](https://www.eia.gov/electricity/wholesale/) | Day-ahead on-peak prices: SP15, Mid-C, Palo Verde, PJM West, Mass Hub | Daily, 2017+ |
| [EIA natural gas spot (RNGWHHD)](https://www.eia.gov/dnav/ng/hist/rngwhhdd.htm) | Henry Hub spot | Daily, 1997+ |
| [EIA-930 via API v2](https://www.eia.gov/opendata/) | Demand, day-ahead demand forecast, generation by fuel per balancing authority | Daily and hourly, 2019+ |
| [ERCOT NP4-180-ER](https://www.ercot.com/mp/data-products/data-product-details?id=NP4-180-ER) | Day-ahead prices at ERCOT's trading hubs (HB_NORTH, HB_HOUSTON, HB_SOUTH, HB_WEST, HB_PAN, HB_HUBAVG) | **Hourly**, 2019+ |

Hub → balancing authority: SP15→CISO, Mid-C→BPAT, Palo Verde→AZPS+SRP, PJM West→PJM, Mass Hub→ISNE, ERCOT hubs→ERCO.

## Thesis pipeline

| # | Thesis | Hub | Status |
|---|---|---|---|
| T01 | Solar is compressing the on-peak heat rate, most in spring | SP15 | **First pass done**: [report](reports/T01_sp15_solar/report.md) |
| T01b | Batteries are blunting solar's *marginal* cannibalization | SP15 | **Not supported**: [report](reports/T01b_sp15_batteries/report.md) |
| T02 | BPA hydro drives the Mid-C – SP15 spread | Mid-C | **Supported**: [report](reports/T02_midc_hydro/report.md) |
| T03 | PJM West heat rate is convex in load; spike days are forecastable | PJM West | **Supported**: [report](reports/T03_pjm_convexity/report.md) |
| E1 | ERCOT scarcity has moved from the demand peak to the evening net-load peak | ERCOT hub avg | **Supported**: [report](reports/E1_ercot_netload_peak/report.md) |
| E2 | ERCOT's battery fleet is flattening the evening price premium | ERCOT hub avg | **Supported, with a caution**: [report](reports/E2_ercot_batteries/report.md) |
| T04 | Mass Hub winter heat rate spikes are a gas-constraint regime, not a load regime | Mass Hub | Parked |
| F01 | Next-day on-peak price forecast: can fundamentals beat persistence? | all | **All 5 hubs done**: `reports/forecast_*/` |

### Early findings (SP15, as of Oct 2026)

- Spring median on-peak heat rate fell from **10.3 (2019) to 2.1 (2026)** as spring solar share rose from 15% to 25%.
- Pooled: +10pp solar share ≈ **−7.9 MMBtu/MWh**. The within-year slope looked like it was flattening
  since 2023; T01b tested whether batteries explain that, and they don't (see below).
- Forecasting: LightGBM trained on the *day-over-day change* beats persistence in every test year
  2022–2026 (MAE 10.1 vs 11.0 $/MWh, 69% directional accuracy). The same model trained on price
  *levels* loses badly, because trees can't extrapolate into a new price regime like 2022.

### Thesis findings

- **T01b, batteries (not supported).** CAISO batteries are hidden in EIA-930's "Other" fuel, but the
  hourly shape exposes them: about −7 GW charging at midday and +7.6 GW discharging in the evening in 2026.
  A bigger fleet does *not* measurably weaken solar's effect on the daily on-peak heat rate. Likely
  reason: batteries move energy *within* the HE7–22 block, so the block average barely moves. T01's
  apparent "flattening" was mostly the 2022–23 western gas crisis.
- **T02, Mid-C hydro (supported).** +1 GW of BPA hydro above its seasonal norm moves Mid-C − SP15 by
  about **−$6/MWh**. From the driest to the wettest fifth of days, the median spread swings from +$17 to −$8.
  Mid-C flipped from a discount (−$4.6, 2019–22) to a premium (+$15, 2023+). The hydro signal improves
  next-day spread forecasts by 4%.
- **T03, PJM convexity (supported).** The P90 heat rate steepens sharply at high load. The top load
  decile carries **39%** of summer on-peak dollars above the median. Spike days (≥1.5× the trailing
  30-day heat rate) are predictable from trade-date data: AUC **0.93**, vs 0.84 for a yesterday-only baseline.

### ERCOT findings (hourly prices)

ERCOT publishes hourly prices, which makes the *shape* of the day testable. That's exactly what T01b said
was needed to see batteries.

- **E1, the expensive hour moved (supported).** ERCOT's highest-priced hour moved from HE17 (the demand peak)
  to HE20 (the net-load peak, after sunset) in 2023. Days whose price peak sits within an hour of the demand
  peak fell from **74% (2019) to 13% (2026)**. Net load's explanatory edge over demand widened by +0.087 per
  year (p = 0.004), mostly because demand alone stopped explaining price spikes.
- **E2, batteries are eating the evening premium (supported, with a caution).** The evening net-load ramp grew
  from 11 to 27 GW, but the premium paid per GW of ramp fell from **+2.21 (2023) to +0.13 (2026)** as the battery
  fleet grew to about 9 GW. Ramp × battery is negative and significant in every specification. Caution: the
  evidence comes from 2023 onward, because before then the evening wasn't where scarcity lived (E1).

### Forecast results across hubs (MAE $/MWh, test years 2022+)

| Hub | Persistence | Best model | Best MAE | Improvement |
|---|---|---|---|---|
| PJM West | 15.12 | Ridge on heat rate | 12.07 | 20% |
| Mass Hub | 15.16 | Ridge on heat rate | 13.12 | 13% |
| SP15 | 11.04 | LightGBM on change | 10.12 | 8% |
| Palo Verde | 15.20 | LightGBM on change | 14.75 | 3% |
| Mid-C | 20.21 | LightGBM on change | 19.71 | 2% |

East vs West split: in gas-and-load-driven eastern markets, a simple heat-rate model works well.
In the West, prices hinge on hydro, solar and *regional* gas basis that Henry Hub doesn't capture,
so fundamentals barely beat persistence. That gap is the case for adding western gas and hydro data.

## Model zoo

- **Persistence**: tomorrow = today. The bar to clear.
- **Ridge on heat rate**: interpretable linear baseline, forecasts IHR × gas.
- **LightGBM** (level and change-on-persistence): nonlinear interactions.
- **Quantile LightGBM** (P10/P90): tail bands for risk sizing.
- **OLS with HAC errors + year interactions**: for structural thesis tests (does an effect change over time?).

All forecasts are walk-forward with an expanding window and use only information available on the
trade date. `tests/` guards both leakage paths.

## Run it

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
cp .env.example .env            # add your free EIA key
python scripts/fetch_data.py    # caches everything under data/
python scripts/thesis_01_solar_cannibalization.py
python scripts/forecast_benchmark.py --hub SP15
python scripts/thesis_e1_ercot_netload_peak.py   # downloads ERCOT prices on first run
python scripts/thesis_e2_ercot_batteries.py
pytest -q
```

## Known limitations

- ICE on-peak is a daily HE7–22 block, so it blends the solar trough with the evening ramp.
- Henry Hub is the gas denominator everywhere. Regional basis (SoCal, Algonquin) matters a lot in
  western and New England winters and isn't in EIA's free daily data.
- ERCOT North dropped out of EIA's ICE files after 2018, so ERCOT prices come from ERCOT directly. They're
  day-ahead only; real-time prices and ancillary services, where batteries also earn, aren't modeled.
