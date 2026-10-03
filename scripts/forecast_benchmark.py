"""Walk-forward benchmark: can fundamentals beat 'tomorrow = today' for next-day on-peak prices?

Uses only KNOWN features (information available on the trade date). Run per hub:
    python scripts/forecast_benchmark.py --hub SP15
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from powerml.config import HUBS, REPORTS
from powerml.features import CALENDAR, KNOWN, build_panel
from powerml.models import GBM, Backtest, HeatRateRidge, OnPersistence, Persistence, walk_forward

ap = argparse.ArgumentParser()
ap.add_argument("--hub", default="SP15", choices=list(HUBS))
ap.add_argument("--first-test-year", type=int, default=2022)
args = ap.parse_args()

feats = KNOWN + CALENDAR
df = build_panel(args.hub)
models = {
    "persistence": Persistence,
    "ridge_heat_rate": lambda: HeatRateRidge(feats),
    "lightgbm_level": lambda: GBM(feats),
    "lightgbm": lambda: OnPersistence(GBM(feats, objective="huber")),
    "lgbm_p10": lambda: OnPersistence(GBM(feats, objective="quantile", alpha=0.1)),
    "lgbm_p90": lambda: OnPersistence(GBM(feats, objective="quantile", alpha=0.9)),
}
bt = walk_forward(df, models, feats, first_test_year=args.first_test_year)

point = bt.preds.drop(columns=["lgbm_p10", "lgbm_p90"])
scores = Backtest(point).scores()
coverage = ((bt.preds["y"] >= bt.preds["lgbm_p10"]) & (bt.preds["y"] <= bt.preds["lgbm_p90"])).mean()
model_cols = [c for c in point.columns if c not in ("date", "year", "y", "price_lag")]
by_year = point[model_cols].sub(point["y"], axis=0).abs().groupby(point["year"]).mean()

out = REPORTS / f"forecast_{args.hub}"
out.mkdir(parents=True, exist_ok=True)
fig, ax = plt.subplots(figsize=(11, 4))
last = bt.preds[bt.preds["year"] == bt.preds["year"].max()]
ax.fill_between(last["date"], last["lgbm_p10"], last["lgbm_p90"], alpha=0.25, label="LightGBM P10-P90")
ax.plot(last["date"], last["y"], "k.", ms=3, label="Actual")
ax.plot(last["date"], last["lightgbm"], lw=1, label="LightGBM")
ax.set_ylabel("$/MWh"); ax.set_title(f"{args.hub} next-day on-peak forecast, {int(last['year'].iloc[0])} (out of sample)")
ax.legend(); fig.tight_layout(); fig.savefig(out / "forecast.png", dpi=150); plt.close(fig)

md = (f"# {args.hub} next-day on-peak price forecast\n\n"
      f"Walk-forward, expanding window, test years {args.first_test_year}+, n={len(point)} days.\n\n"
      f"## Overall\n\n{scores.round(2).to_markdown()}\n\n"
      f"P10-P90 band coverage: **{coverage:.0%}** (target 80%).\n\n"
      f"## MAE by test year ($/MWh)\n\n{by_year.round(2).to_markdown()}\n\n![](forecast.png)\n")
(out / "report.md").write_text(md, encoding="utf-8")
print(md)
