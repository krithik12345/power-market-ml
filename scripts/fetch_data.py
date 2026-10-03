"""Download/cache every raw input: ICE prices, Henry Hub, and EIA-930 for each hub's BAs."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from powerml import data
from powerml.config import HUBS

ap = argparse.ArgumentParser()
ap.add_argument("--refresh", action="store_true", help="re-pull EIA-930 even if cached")
args = ap.parse_args()

prices = data.ice_power_prices()
print(f"ICE prices: {len(prices):,} hub-days")
print(f"Henry Hub: {len(data.henry_hub()):,} days")
for key in HUBS:
    f = data.fundamentals(key, refresh=args.refresh)
    print(f"EIA-930 {key}: {len(f):,} days, {f['date'].min():%Y-%m-%d} -> {f['date'].max():%Y-%m-%d}")
