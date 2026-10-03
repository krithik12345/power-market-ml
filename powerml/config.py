"""Project-wide constants: paths, hub definitions, and the hub -> balancing-authority map."""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"

for _p in (RAW, CACHE, PROCESSED, REPORTS):
    _p.mkdir(parents=True, exist_ok=True)

ICE_FIRST_YEAR = 2017  # first year EIA publishes as .xlsx (earlier years are .xls / zip)
EIA930_FIRST_DAY = "2019-01-01"  # daily EIA-930 routes start here


@dataclass(frozen=True)
class Hub:
    key: str            # short id used throughout the project
    ice_name: str       # "Price hub" string in the EIA/ICE files
    bas: tuple          # EIA-930 balancing authorities that represent the hub's load pocket
    timezone: str       # EIA-930 daily-aggregation timezone facet


# Only hubs with near-daily ICE coverage 2017+ are listed. ERCOT North dropped out of the
# EIA/ICE files after 2018, and NP15 / Indiana trade too thinly for daily modeling.
HUBS = {
    "SP15": Hub("SP15", "SP15 EZ Gen DA LMP Peak", ("CISO",), "Pacific"),
    "MIDC": Hub("MIDC", "Mid C Peak", ("BPAT",), "Pacific"),
    "PALOVERDE": Hub("PALOVERDE", "Palo Verde Peak", ("AZPS", "SRP"), "Arizona"),
    "PJMW": Hub("PJMW", "PJM WH Real Time Peak", ("PJM",), "Eastern"),
    "MASS": Hub("MASS", "Nepool MH DA LMP Peak", ("ISNE",), "Eastern"),
}

# EIA-930 energy-source codes we pull. Everything else is folded into "other" by subtraction.
FUELS = ("SUN", "WND", "WAT", "NG", "NUC", "COL")
REGION_TYPES = ("D", "DF")  # actual demand, day-ahead demand forecast
