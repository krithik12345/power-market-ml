# Heat Rate Lab: testing power-market theses with EIA data

An ML research project that turns free public EIA data into **testable power-trading theses**.
Each thesis is stated as a falsifiable claim, tested with interpretable and nonlinear models,
and written up with a trade expression and the evidence that would kill it.

The core move is to model the **implied market heat rate** (on-peak power price ÷ gas price,
MMBtu/MWh) instead of raw $/MWh. That strips out the gas level, which otherwise dominates every
power regression, and isolates what the grid itself is doing: solar, wind, hydro, load.

## Data (all EIA, all free)

| Source | What | Granularity |
|---|---|---|
| [EIA wholesale markets (ICE)](https://www.eia.gov/electricity/wholesale/) | Day-ahead on-peak prices: SP15, Mid-C, Palo Verde, PJM West, Mass Hub | Daily, 2017+ |
| [EIA natural gas spot (RNGWHHD)](https://www.eia.gov/dnav/ng/hist/rngwhhdd.htm) | Henry Hub spot | Daily, 1997+ |
| [EIA-930 via API v2](https://www.eia.gov/opendata/) | Demand, day-ahead demand forecast, generation by fuel per balancing authority | Daily, 2019+ |

Hub → balancing authority: SP15→CISO, Mid-C→BPAT, Palo Verde→AZPS+SRP, PJM West→PJM, Mass Hub→ISNE.

## Thesis pipeline

| # | Thesis | Hub | Status |
|---|---|---|---|
| T01 | Solar is compressing the on-peak heat rate, most in spring | SP15 | **First pass done**: [report](reports/T01_sp15_solar/report.md) |
| T01b | Batteries are blunting solar's *marginal* cannibalization | SP15 | Next: add EIA-930 `BAT` |
| T02 | Mid-C trades at a hydro-driven discount; BPAT hydro + wind predict the Mid-C – SP15 spread | Mid-C | Needs API key |
| T03 | PJM West heat rate is convex in load; upper-tail risk is underpriced in summer | PJM West | Needs API key, quantile models |
| T04 | Mass Hub winter heat rate spikes are a gas-constraint regime, not a load regime | Mass Hub | Needs API key, regime clustering |
| F01 | Next-day on-peak price forecast: can fundamentals beat persistence? | all | **SP15 done**: [report](reports/forecast_SP15/report.md) |

### Early findings (SP15, as of Oct 2026)

- Spring median on-peak heat rate fell from **10.3 (2019) to 2.1 (2026)** as spring solar share rose from 15% to 25%.
- Pooled: +10pp solar share ≈ **−7.9 MMBtu/MWh**. But the *within-year* slope has **flattened since 2023**,
  which is consistent with storage absorbing the midday surplus. That becomes T01b.
- Forecasting: LightGBM trained on the *day-over-day change* beats persistence in every test year
  2022–2026 (MAE 10.1 vs 11.0 $/MWh, 69% directional accuracy). The same model trained on price
  *levels* loses badly, because trees can't extrapolate into a new price regime like 2022.

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
pytest -q
```

## Known limitations

- ICE on-peak is a daily HE7–22 block, so it blends the solar trough with the evening ramp.
- Henry Hub is the gas denominator everywhere. Regional basis (SoCal, Algonquin) matters a lot in
  western and New England winters and isn't in EIA's free daily data.
- ERCOT North dropped out of EIA's ICE files after 2018, so ERCOT isn't covered.
