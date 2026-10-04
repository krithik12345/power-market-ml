"""Builds docs/Power_Market_ML_Learning_Guide.pdf.

Run from the repo root:  python docs/build_guide.py
Needs reportlab and the Windows fonts Palatino Linotype, Segoe UI and Consolas.
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "reports"
OUT = ROOT / "docs" / "Power_Market_ML_Learning_Guide.pdf"
OUT.parent.mkdir(exist_ok=True)

F = r"C:\Windows\Fonts"
for name, file in [("Serif", "pala.ttf"), ("Serif-Bold", "palab.ttf"), ("Serif-Italic", "palai.ttf"),
                   ("Serif-BoldItalic", "palabi.ttf"), ("Sans", "segoeui.ttf"), ("Sans-Semi", "seguisb.ttf"),
                   ("Mono", "consola.ttf")]:
    pdfmetrics.registerFont(TTFont(name, f"{F}\\{file}"))
from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily("Serif", normal="Serif", bold="Serif-Bold", italic="Serif-Italic", boldItalic="Serif-BoldItalic")

INK = colors.HexColor("#26221f")       # warm near-black
MUTED = colors.HexColor("#6b625a")     # warm grey for captions and labels
HAIR = colors.HexColor("#d8d0c4")      # hairline rules
ACCENT = colors.HexColor("#8c2f2b")    # oxblood
OLIVE = colors.HexColor("#5a6b38")
AMBER = colors.HexColor("#a3660a")
ACC = "#8c2f2b"

S = {
    "title": ParagraphStyle("title", fontName="Serif", fontSize=34, leading=40, textColor=INK),
    "sub": ParagraphStyle("sub", fontName="Serif-Italic", fontSize=13, leading=19, textColor=MUTED),
    "meta": ParagraphStyle("meta", fontName="Sans", fontSize=9.5, leading=13, textColor=MUTED),
    "h1": ParagraphStyle("h1", fontName="Sans-Semi", fontSize=21, leading=26, textColor=INK, spaceBefore=2, spaceAfter=6),
    "h2": ParagraphStyle("h2", fontName="Sans-Semi", fontSize=13, leading=17, textColor=INK, spaceBefore=12, spaceAfter=5),
    "h3": ParagraphStyle("h3", fontName="Sans-Semi", fontSize=10.5, leading=14, textColor=ACCENT, spaceBefore=6, spaceAfter=2),
    "p": ParagraphStyle("p", fontName="Serif", fontSize=10, leading=15, textColor=INK, spaceAfter=6),
    "b": ParagraphStyle("b", fontName="Serif", fontSize=10, leading=14.6, textColor=INK, leftIndent=15, bulletIndent=2, spaceAfter=3,
                        bulletFontName="Serif-Bold", bulletColor=ACCENT),
    "box": ParagraphStyle("box", fontName="Serif", fontSize=9.7, leading=14.2, textColor=INK, spaceAfter=5),
    "boxlabel": ParagraphStyle("boxlabel", fontName="Sans-Semi", fontSize=7.6, leading=10, textColor=ACCENT, spaceAfter=3),
    "code": ParagraphStyle("code", fontName="Mono", fontSize=8.6, leading=11.6, textColor=INK),
    "cap": ParagraphStyle("cap", fontName="Serif-Italic", fontSize=8.8, leading=12.5, textColor=MUTED, spaceBefore=3, spaceAfter=10),
    "cell": ParagraphStyle("cell", fontName="Serif", fontSize=8.8, leading=12, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Sans-Semi", fontSize=8.4, leading=11.5, textColor=INK),
}

story = []
_fig = [0]


def _numbered(t):
    """Set the leading section number ('2.' or '2.4') in the accent colour."""
    head, _, rest = t.partition(" ")
    if head.rstrip(".").replace(".", "").isdigit() and rest:
        return f'<font color="{ACC}">{head.rstrip(".")}</font>&nbsp;&nbsp;{rest}'
    return t


def H1(t):
    story.append(Paragraph(_numbered(t), S["h1"]))
    rule = Table([[""]], colWidths=[6.7 * inch], rowHeights=[2])
    rule.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, INK)]))
    story.append(rule); story.append(Spacer(1, 8))


H2 = lambda t: story.append(Paragraph(_numbered(t), S["h2"]))
H3 = lambda t: story.append(Paragraph(t, S["h3"]))
P = lambda t: story.append(Paragraph(t, S["p"]))


def B(*items):
    for t in items:
        story.append(Paragraph(t, S["b"], bulletText="–"))
    story.append(Spacer(1, 3))


def _callout(label, body, color, style):
    lines = body if isinstance(body, list) else [body]
    lab = ParagraphStyle("lab", parent=S["boxlabel"], textColor=color)
    inner = [Paragraph(label.upper(), lab)]
    for line in lines:
        if style == "list":
            inner.append(Paragraph(line, ParagraphStyle("bl", parent=S["box"], leftIndent=11, bulletIndent=0,
                                                  bulletFontName="Serif", bulletColor=color),
                                   bulletText="–"))
        else:
            inner.append(Paragraph(line, S["box"]))
    t = Table([[inner]], colWidths=[6.7 * inch])
    if style == "rules":
        st = [("LINEABOVE", (0, 0), (-1, 0), 1.2, color), ("LINEBELOW", (0, 0), (-1, -1), 0.4, color),
              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]
    else:
        st = [("LINEBEFORE", (0, 0), (0, -1), 2.4, color),
              ("LEFTPADDING", (0, 0), (-1, -1), 13), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    st += [("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
    t.setStyle(TableStyle(st))
    story.append(Spacer(1, 4)); story.append(KeepTogether([t])); story.append(Spacer(1, 9))


KEY = lambda body: _callout("The key idea", body, ACCENT, "bar")
YOU = lambda body: _callout("Check yourself: can you explain", body, OLIVE, "list")
WATCH = lambda body: _callout("Caution", body, AMBER, "rules")


def code(text):
    t = Table([[Preformatted(text.strip("\n"), S["code"])]], colWidths=[6.7 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f4ef")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.append(t); story.append(Spacer(1, 8))


def table(rows, widths, header=True):
    scale = 6.7 / sum(widths)
    data = [[Paragraph(str(c), S["cellb"] if (header and i == 0) or (not header and j == 0) else S["cell"])
             for j, c in enumerate(r)] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * scale * inch for w in widths], repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
          ("LINEABOVE", (0, 0), (-1, 0), 1.1, INK), ("LINEBELOW", (0, -1), (-1, -1), 1.1, INK)]
    if header:
        st.append(("LINEBELOW", (0, 0), (-1, 0), 0.6, INK))
        st.append(("LINEBELOW", (0, 1), (-1, -2), 0.25, HAIR))
    else:
        st.append(("LINEBELOW", (0, 0), (-1, -2), 0.25, HAIR))
    t.setStyle(TableStyle(st))
    story.append(KeepTogether([t]) if len(rows) <= 8 else t); story.append(Spacer(1, 10))


def fig(path, caption, width=6.0):
    from reportlab.lib.utils import ImageReader
    _fig[0] += 1
    w, h = ImageReader(str(path)).getSize()
    cap = f'<font name="Sans-Semi" color="{ACC}">Figure {_fig[0]}.</font>&nbsp; {caption}'
    story.append(KeepTogether([Image(str(path), width=width * inch, height=width * inch * h / w, hAlign="LEFT"),
                               Paragraph(cap, S["cap"])]))


def footer(c, doc):
    c.saveState()
    c.setFont("Sans-Semi", 8.5); c.setFillColor(MUTED)
    c.drawRightString(7.6 * inch, 0.52 * inch, f"{doc.page}")
    c.restoreState()


# =====================================================================================
# COVER
# =====================================================================================
cover_rule = Table([[""]], colWidths=[1.1 * inch], rowHeights=[4])
cover_rule.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 3, ACCENT)]))
cover_rule.hAlign = "LEFT"
story += [Spacer(1, 1.3 * inch), cover_rule, Spacer(1, 14),
          Paragraph("Power Market ML", S["title"]), Spacer(1, 8),
          Paragraph("A learning guide to the market concepts, data work, statistics and machine learning "
                    "behind the project, and how each result was tested.", S["sub"]),
          Spacer(1, 16),
          Paragraph("Companion to github.com/krithik12345/power-market-ml", S["meta"]),
          Spacer(1, 0.9 * inch),
          Paragraph("CONTENTS", ParagraphStyle("c", parent=S["boxlabel"], textColor=MUTED)), Spacer(1, 2)]
table([
    ["Part", "What it covers"],
    ["0. How to use this guide", "Who it is for, what you need to know first, and how to run the code yourself"],
    ["1. The big picture", "What the project does, end to end, in one page"],
    ["2. Power market concepts", "Hubs, on-peak, day-ahead vs real-time, supply stack, heat rate, spark spread, net load, basis, storage"],
    ["3. Data engineering", "The three EIA sources, the API, joining by trade date vs delivery date, units, time zones, look-ahead bias"],
    ["4. Statistics for testing theses", "OLS, fixed effects, HAC standard errors, interactions, delta method, quantile regression, confounding"],
    ["5. Machine learning models", "Persistence, ridge, LightGBM, modeling the change, loss functions, classifiers, partial dependence"],
    ["6. Evaluation", "Walk-forward backtests, leakage, MAE/RMSE, coverage, AUC, Brier, fair baselines"],
    ["7. The theses, walked through", "T01, T01b, T02, T03 and the forecast benchmark: method, result, limits"],
    ["8. Research lessons", "The three times a first result was wrong, and how it was caught"],
    ["9. Code map", "Which file does what, and which concepts it uses"],
    ["10. Review questions", "Questions to test your understanding, with short answers"],
    ["11. Glossary and study plan", "Terms and what to learn next"],
], [1.9, 4.6])
story.append(PageBreak())

# =====================================================================================
# 0. HOW TO USE
# =====================================================================================
H1("0. How to use this guide")
P("This guide teaches the ideas behind the <b>power-market-ml</b> repository: how wholesale electricity markets work, how to turn "
  "public EIA data into a clean modeling dataset, and how to test market claims and forecasts without fooling yourself. "
  "Every concept is tied to a specific file and a real result from the repo, so you can read an idea here and then see it running in code.")
H2("Who it is for")
B("Students and engineers who know some Python and want to understand how power markets work.",
  "People who already know power markets and want to see how statistics and machine learning are used to test trading ideas.",
  "Anyone reading the repo who wants to understand <i>why</i> each design choice was made, not just what the code does.")
H2("What you should know first")
B("<b>Python and pandas:</b> reading a DataFrame, filtering, merging, and groupby. You don't need to know any modeling libraries.",
  "<b>Basic statistics:</b> mean, median, percentiles, and what a linear regression line is. Everything beyond that is explained here.",
  "<b>No power-market background needed.</b> Part 2 starts from zero.")
H2("How to read it")
P("Parts 1 to 6 build up the concepts in order: markets, data, statistics, models, evaluation. Part 7 applies all of them to the four studies "
  "in the repo, and Part 8 covers what went wrong along the way. If you only have an hour, read Part 1, the 'key idea' notes, and Part 7. "
  "Each part ends with a <font color='#5a6b38'><b>Check yourself</b></font> list. If you can explain every item out loud without looking, you've got that part.")
H2("Run it yourself")
P("Reading is good; changing the code and predicting what happens is better. Setup takes about ten minutes:")
code("""
git clone https://github.com/krithik12345/power-market-ml
cd power-market-ml
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
copy .env.example .env                          # macOS/Linux: cp
                                                # then paste a free key from
                                                # eia.gov/opendata/register.php
python scripts/fetch_data.py                    # downloads and caches all data
python scripts/thesis_03_pjm_convexity.py       # reproduces one study
""")
story.append(PageBreak())

# =====================================================================================
# 1. BIG PICTURE
# =====================================================================================
H1("1. The big picture")
P("The project takes free public data from the U.S. Energy Information Administration (EIA) and uses it to do two "
  "different jobs. Keep these two jobs separate in your head; most of the design decisions follow from the difference.")
table([
    ["", "Job A: Thesis testing", "Job B: Forecasting"],
    ["Question", "<i>Why</i> do prices behave the way they do? Is a market claim true?", "<i>What</i> will tomorrow's price be?"],
    ["Example", "Does more solar push SP15 prices down relative to gas?", "Predict tomorrow's SP15 on-peak price this morning"],
    ["Allowed information", "Anything about the delivery day, including what actually happened", "Only what a trader knows on the trade date"],
    ["Main tools", "Regression with controls, standard errors, interaction terms, quantile regression", "Persistence, ridge, LightGBM, walk-forward backtests"],
    ["Success looks like", "A coefficient with the right sign, a tight confidence interval, and robustness checks it survives", "Lower error than a simple baseline on years the model never saw"],
    ["Scripts", "thesis_01, 01b, 02, 03", "forecast_benchmark.py (and part of T02 and T03)"],
], [1.25, 2.6, 2.65])
H2("The pipeline in five steps")
B("<b>Download</b> daily power prices for five trading hubs, daily Henry Hub gas prices, and daily grid data "
  "(demand, demand forecast, generation by fuel) for the grid operator behind each hub. Cache everything locally.",
  "<b>Align</b> them into one table per hub, one row per delivery day.",
  "<b>Engineer features</b>: the implied heat rate, fuel shares, net load, calendar terms, and lagged values that a trader would actually know.",
  "<b>Test theses</b> with regressions designed to isolate one effect at a time, then try to break each result with robustness checks.",
  "<b>Forecast</b> with several models, graded only on years they never trained on, against a hard baseline.")
KEY("The single most important modeling choice: the project studies the <b>implied market heat rate</b> "
    "(power price divided by gas price) instead of the raw power price. Gas prices swing a lot and drag power "
    "prices with them, which hides everything else. Dividing by gas removes most of that, so what's left is what "
    "the grid itself is doing: solar, wind, hydro and load.")
H2("What was found")
table([
    ["Study", "Result", "Status"],
    ["T01 Solar at SP15", "Spring median heat rate fell from 10.3 (2019) to 2.1 (2026) as spring solar share rose from 15% to 25%. +10 points of solar is about -7.9 heat-rate units, pooled.", "Supported"],
    ["T01b Batteries", "A bigger battery fleet does not measurably weaken solar's effect on the daily on-peak price. The batteries were found hidden inside EIA's 'Other' category.", "Not supported"],
    ["T02 Mid-C hydro", "+1 GW of Northwest hydro above normal moves Mid-C about $6/MWh lower vs SP15. Mid-C flipped from a discount to a premium after 2022.", "Supported"],
    ["T03 PJM spikes", "Heat rate is convex in load; the top 10% of load days carry 39% of summer upside. Spike days are predictable a day ahead (AUC 0.93 vs 0.84 baseline).", "Supported"],
    ["F01 Forecasts", "Models beat 'tomorrow = today' at all five hubs: 20% better at PJM West, 2% at Mid-C.", "Done"],
], [1.35, 4.15, 1.0])
story.append(PageBreak())

# =====================================================================================
# 2. POWER MARKET CONCEPTS
# =====================================================================================
H1("2. Power market concepts")
H2("2.1 Hubs, ISOs and balancing authorities")
P("Electricity is traded at <b>hubs</b>: named pricing points that stand in for a region. A hub price is usually an average "
  "of locational prices at many nodes. The five hubs in this project:")
table([
    ["Hub", "Region", "Grid operator (EIA-930 code)", "What drives it"],
    ["SP15", "Southern California", "CAISO (CISO)", "Solar, gas, imports"],
    ["Mid-C", "Pacific Northwest (Mid-Columbia river)", "Bonneville Power (BPAT)", "Hydro, wind"],
    ["Palo Verde", "Arizona", "APS + SRP (AZPS, SRP)", "Solar, gas, nuclear"],
    ["PJM West", "Mid-Atlantic", "PJM (PJM)", "Gas, coal, load"],
    ["Mass Hub", "New England", "ISO-NE (ISNE)", "Gas (pipeline-constrained in winter)"],
], [1.0, 1.9, 1.8, 1.8])
P("An <b>ISO/RTO</b> (Independent System Operator / Regional Transmission Organization) runs the grid and the wholesale market "
  "in its region. A <b>balancing authority (BA)</b> is any entity responsible for keeping supply and demand balanced in an area; "
  "every ISO is a BA, but some BAs (like BPA or APS) are utilities. EIA's Form 930 reports data by BA, which is why the project "
  "maps each hub to one or more BAs.")
H2("2.2 Day-ahead, real-time, and the on-peak block")
B("<b>Day-ahead (DA):</b> power for tomorrow, traded today. Most hedging happens here.",
  "<b>Real-time (RT):</b> the price that actually clears in the moment. Spikier, because surprises (a plant trips, a heat wave arrives early) show up here.",
  "<b>On-peak block:</b> a standard product covering hour-ending 7 through 22 (7am-10pm) on weekdays. The EIA/ICE files give one price per hub per day for this block. "
  "That means every price in the project is an <i>average over 16 hours</i>, which matters a lot in T01b.",
  "<b>Trade date vs delivery date:</b> a day-ahead trade on Monday is for delivery on Tuesday. The project keys every row by delivery date, "
  "but uses the trade date to decide what information was available. Friday trades usually cover Monday delivery; multi-day weekend packages were dropped.")
H2("2.3 The supply stack (merit order)")
P("Power plants are dispatched cheapest-first. Picture all plants lined up by their cost to produce one more MWh: renewables and nuclear "
  "(near zero), then coal and efficient gas, then older gas plants, then peakers that run only a few hours a year. Demand is a vertical "
  "line on this chart; the <b>last plant needed to meet demand sets the price</b> for everyone.")
B("The stack is flat for a long stretch and then turns sharply upward at the end. This is a <b>hockey stick</b>, or <b>convex</b> shape.",
  "Consequence: a 5 GW rise in load on a mild day barely moves the price, but the same 5 GW on the hottest day of the year can double it. This is exactly what T03 measures.",
  "Solar and wind sit at the cheap end. Adding them shifts the whole stack right, so a given load is met further down the curve. This is the mechanism behind T01.")
H2("2.4 Heat rate and spark spread")
P("<b>Physical heat rate</b> is how much fuel a plant burns per MWh it produces, in MMBtu/MWh. Lower is more efficient. A modern combined-cycle "
  "gas plant is about 6.5-7.5; an old peaker can be 10-14.")
P("<b>Implied market heat rate (IHR)</b> turns this around: it asks what heat rate the <i>market price</i> implies.")
code("""
IHR = power price ($/MWh) / gas price ($/MMBtu)        units: MMBtu/MWh

Example: power $45/MWh, gas $3.00/MMBtu  ->  IHR = 45 / 3 = 15
""")
P("An IHR of 15 says the market is paying as if a fairly inefficient plant is setting the price, so the system is tight. An IHR of 3 says power "
  "is cheap relative to its fuel, so something other than gas (solar, hydro) is setting the price.")
P("<b>Spark spread</b> is the gross margin of a gas plant: power price minus fuel cost.")
code("""
spark spread = power price - (plant heat rate x gas price)

Example: $45 - (7 x $3.00) = $45 - $21 = $24/MWh margin for a 7-heat-rate plant
""")
KEY("A trader who is 'short heat rate' profits if power gets cheaper <i>relative to gas</i>, whatever gas itself does. "
    "That's why heat rate is the natural unit for the theses: it's the unit a power trader actually takes a view on.")
H2("2.5 Net load, the duck curve, and solar cannibalization")
P("<b>Net load</b> = demand minus wind minus solar. It's the load the rest of the fleet (gas, hydro, imports) must cover, and it's usually a better "
  "price driver than raw demand. In California, net load collapses at midday when solar peaks and then shoots up at sunset. Plotted over a day, this looks "
  "like a duck (the <b>duck curve</b>).")
P("<b>Cannibalization</b>: each new solar plant produces at the same hours as every existing one, pushing midday prices down and reducing the value of "
  "all solar. T01 measures this at the daily on-peak level.")
H2("2.6 Basis and spreads")
P("<b>Basis</b> is the price difference between two locations (or a location and a benchmark). The Mid-C minus SP15 spread in T02 is a basis. "
  "Trading a spread (long one hub, short another) removes the exposure the two share, such as western gas prices, and leaves a bet on what differs "
  "between them, such as Northwest hydro.")
P("<b>Gas basis</b> matters too. Henry Hub (Louisiana) is the national benchmark, but western power plants buy gas at regional hubs (SoCal Citygate, "
  "Sumas, PG&amp;E Citygate). In winter 2022-23, western gas spiked to several times Henry Hub. Since the project divides by Henry Hub, western IHRs in those "
  "months look absurdly high. This is why the analyses <b>winsorize</b> outliers and flag 2022-23 everywhere.")
H2("2.7 Storage and intraday shape")
P("Batteries charge when power is cheap (midday solar) and discharge when it is expensive (the evening ramp). This narrows the gap between midday and "
  "evening prices: the <b>intraday shape</b>. Because the on-peak block contains both midday and evening hours, a battery moving energy from noon to 8pm mostly "
  "reshuffles value <i>inside</i> the block. That's the key insight from T01b.")
H2("2.8 Hydro")
P("Northwest hydro output depends on snowpack and spring runoff. It peaks around May-June. What matters for prices is not the season itself "
  "(the market already expects spring runoff) but the <b>anomaly</b>: how much more or less water there is than normal for that month.")
YOU(["Why a heat rate of 15 means a tight market, and how to compute it from a price and a gas price.",
     "Why the supply stack makes prices convex in load.",
     "What net load is and why it predicts price better than demand.",
     "Why a spread trade isolates one driver.",
     "Why dividing by Henry Hub distorted the western numbers in 2022-23."])
story.append(PageBreak())

# =====================================================================================
# 3. DATA ENGINEERING
# =====================================================================================
H1("3. Data engineering")
H2("3.1 The three sources")
table([
    ["Source", "What one row is", "How it's fetched", "Code"],
    ["EIA wholesale (ICE) power", "One hub, one trade date, one delivery period: weighted average price, high, low, volume, trades", "Yearly Excel files, 2017-2026, downloaded once and cached", "ice_power_prices()"],
    ["Henry Hub spot (RNGWHHD)", "One trade date, one $/MMBtu price", "One Excel file covering 1997 to today, refreshed daily", "henry_hub()"],
    ["EIA-930 grid data", "One BA, one day (or hour), one series: demand, demand forecast, or generation by fuel", "EIA API v2 with a free key, paginated, cached as Parquet", "eia930_daily(), eia930_hourly()"],
], [1.35, 2.15, 1.85, 1.15])
P("Findings during data collection that shaped the project: ERCOT North stopped appearing in the ICE files after 2018, so Texas is out. NP15 and Indiana "
  "trade too thinly for daily modeling. The regional gas files EIA used to post are no longer available, so Henry Hub is the only gas benchmark. "
  "CAISO does not report batteries as their own fuel type.")
H2("3.2 Working with an API")
B("<b>Routes and facets:</b> EIA API v2 is organized by routes (e.g. <font face='Mono'>electricity/rto/daily-fuel-type-data</font>). "
  "Facets are filters: <font face='Mono'>respondent=CISO</font>, <font face='Mono'>fueltype=SUN</font>, <font face='Mono'>timezone=Pacific</font>.",
  "<b>Pagination:</b> the API returns at most 5,000 rows per request. The client loops, increasing <font face='Mono'>offset</font> by 5,000 until it has <font face='Mono'>total</font> rows.",
  "<b>Rate limits and retries:</b> HTTP 429 means 'too many requests'. The client waits and retries with <b>exponential backoff</b> (5s, 10s, 20s, 40s). "
  "EIA's public DEMO_KEY is too rate-limited to download everything, so you need your own free key (Part 0).",
  "<b>Secrets:</b> the key lives in <font face='Mono'>.env</font>, loaded with python-dotenv, and <font face='Mono'>.gitignore</font> keeps it out of git.",
  "<b>Caching:</b> every download is saved (Excel in data/raw, API results as Parquet in data/cache). Re-runs are instant, offline, and don't burn API quota. "
  "Parquet is a compressed columnar format that loads much faster than CSV and keeps data types.")
H2("3.3 Lining the data up")
P("This is where most real-world bugs live. Four alignment problems were solved:")
B("<b>Keys:</b> power rows are keyed by delivery date; gas rows by trade date. Gas is joined on the power trade date because both are next-day products "
  "traded the same morning.",
  "<b>Missing days:</b> Henry Hub doesn't print on some holidays. <font face='Mono'>pd.merge_asof(direction='backward')</font> takes the most recent "
  "earlier gas price (up to 5 days back) instead of leaving a gap.",
  "<b>Time zones:</b> hourly EIA-930 data is in UTC. To compute a California 'day', the battery code converts to US/Pacific before grouping by date; "
  "otherwise the evening discharge would land on the wrong day.",
  "<b>Units:</b> daily grid totals are MWh per day. Dividing by 24 and by 1000 gives <b>average GW</b>, a number people can picture (CAISO averages roughly 25-35 GW).")
H2("3.4 Feature engineering")
table([
    ["Feature", "Formula", "Why"],
    ["ihr", "price / gas", "Gas-neutral price (section 2.4)"],
    ["solar_share, wind_share, hydro_share", "generation by fuel / demand", "Scale-free: comparable across years as demand grows"],
    ["net_load_gw", "(demand - solar - wind) / 24 / 1000", "What the rest of the fleet must cover"],
    ["doy_sin, doy_cos", "sin and cos of 2 pi x day-of-year / 365.25", "Encodes season smoothly: Dec 31 and Jan 1 end up next to each other, which a 1-365 number can't do"],
    ["dow, month", "calendar", "Weekday and seasonal patterns; used as categories (one-hot or fixed effects)"],
    ["trend_yrs", "years since 2019-01-01", "Lets models capture slow structural change"],
    ["price_lag, ihr_lag", "previous delivery day's value", "The persistence signal"],
    ["price_lag_5d_mean", "rolling 5-day mean of past prices", "Smoother recent level"],
    ["demand_fcst_delta", "tomorrow's demand forecast - yesterday's actual demand", "Expected change in load: the most useful signal in T03"],
    ["gas_chg", "gas today - gas on previous price day", "Fuel-cost shock"],
    ["*_lag (fuel shares)", "values from the day before the trade date", "What was actually knowable at trade time"],
], [1.75, 2.35, 2.4])
H2("3.5 Look-ahead bias: 'explain' vs 'known' features")
P("A forecast that uses information from the future looks brilliant in a backtest and fails in real life. This is called <b>look-ahead bias</b> or "
  "<b>leakage</b>. The project prevents it by splitting features into two lists in <font face='Mono'>features.py</font>:")
B("<b>EXPLAIN</b>: what actually happened on the delivery day (actual solar, actual demand). Used only for thesis testing, where the question is 'why'.",
  "<b>KNOWN</b>: what a trader has on the trade-date morning: the demand <i>forecast</i> for tomorrow, yesterday's realized mix, today's gas, the last cleared price. Used for every forecast.")
WATCH("Even 'known' features rest on an assumption: that EIA's day-ahead demand forecast is published before the morning trading window. "
      "EIA doesn't document the exact time. A live system should use the ISO's own forecast, which is published well before trading.")
H2("3.6 Recovering hidden batteries (T01b)")
P("CAISO doesn't report a BAT fuel type to EIA-930. A query for every storage code returned nothing, but the 'Other' (OTH) category had a slightly "
  "<i>negative</i> daily total. That's a clue, since storage loses energy on each charge-discharge cycle. Pulling OTH <b>hourly</b> and averaging by hour of day showed it:")
table([
    ["Hour (Pacific)", "2019 average MW", "2026 average MW", "Meaning"],
    ["12 (noon)", "-3", "-7,163", "Charging on midday solar"],
    ["20 (8pm)", "+5", "+7,595", "Discharging into the evening ramp"],
], [1.4, 1.5, 1.5, 2.1])
P("The daily battery features are the sum of positive hours (discharge) and of negative hours (charge). The fleet-size proxy is the "
  "<b>trailing 90-day 95th percentile</b> of daily discharge, shifted by a day. Section 4.9 explains why it's built this way.")
YOU(["Why the API client paginates and backs off, and why results are cached.",
     "What merge_asof does and why gas is joined on the trade date.",
     "Why sin/cos encode season better than day number.",
     "The difference between EXPLAIN and KNOWN features, and what leakage would look like.",
     "How the batteries were found in data that doesn't label them."])
story.append(PageBreak())

# =====================================================================================
# 4. STATISTICS
# =====================================================================================
H1("4. Statistics for testing theses")
H2("4.1 Ordinary least squares (OLS) regression")
P("OLS fits a straight-line relationship by minimizing the sum of squared errors. The T01 model:")
code("""
ihr = b0 + b1*solar_pp + b2*wind_pp + b3*hydro_pp + b4*demand_gw
      + month effects + weekday effects + error
""")
P("<b>Reading a coefficient:</b> b1 is the expected change in IHR for a 1-point increase in solar share, <i>holding everything else in the model "
  "constant</i>. T01 got b1 = -0.785, reported per 10 points as -7.85. Shares were converted to percentage points (x100) precisely so the coefficient "
  "reads naturally. <b>R²</b> is the fraction of variation explained (0.41 in T01): useful for comparing models on the same data, but not a measure of whether a "
  "coefficient is right.")
H2("4.2 Controls and fixed effects")
P("Solar is high in spring, and spring also has mild load and high hydro. Without controls, the solar coefficient would absorb all of that. Adding wind, "
  "hydro and demand as <b>controls</b> means the solar effect is estimated after accounting for them.")
P("<font face='Mono'>C(month)</font> and <font face='Mono'>C(dow)</font> are <b>fixed effects</b>: a separate intercept for each month and weekday. "
  "They absorb anything that is typical of 'April' or 'Monday'. The solar coefficient is then identified from days that had <i>more or less solar than usual "
  "for that month</i>, which is a much cleaner comparison.")
H2("4.3 Standard errors, confidence intervals, p-values")
B("The <b>standard error (s.e.)</b> measures how much a coefficient would bounce around if you had a different sample of days.",
  "A <b>95% confidence interval</b> is roughly coefficient ± 1.96 x s.e. T01: -7.85 with CI -9.39 to -6.31. Since the whole interval is below zero, the effect is clearly negative.",
  "The <b>p-value</b> is the probability of seeing an effect this large if the true effect were zero. Below 0.05 is the usual threshold for 'significant'. "
  "It is <i>not</i> the probability the thesis is true.")
H2("4.4 HAC (Newey-West) standard errors")
P("Ordinary standard errors assume each day's error is independent. Market days are not independent: a heat wave or a gas squeeze lasts several days, so errors "
  "are <b>autocorrelated</b>. Ignoring that makes standard errors too small and results look more certain than they are.")
P("<b>HAC</b> (heteroskedasticity- and autocorrelation-consistent) standard errors, also called Newey-West, correct for this. Every regression in the project uses "
  "<font face='Mono'>cov_type='HAC', maxlags=5</font>, allowing correlation across about a trading week.")
H2("4.5 Interaction terms")
P("An interaction lets one variable's effect depend on another. Two were used:")
B("<b>solar x year</b> (T01): estimates a separate solar slope for each year, so you can see if the effect is changing over time.",
  "<b>solar x battery</b> (T01b): asks whether solar's effect depends on how big the battery fleet is.")
code("""
ihr = b1*solar + b2*battery + b3*(solar x battery) + ...

marginal effect of solar = b1 + b3*battery
   b3 > 0  ->  more batteries make solar's (negative) effect smaller
""")
H2("4.6 The delta method")
P("To put a confidence band around 'the effect of solar at battery level b', you need the standard error of a <i>combination</i> of coefficients. "
  "The delta method gives it from the coefficient covariance matrix V:")
code("""
Var(b1 + b*b3) = V[1,1] + b^2 * V[3,3] + 2*b*V[1,3]
""")
P("That's the blue shaded band in the T01b chart (<font face='Mono'>solar_effect()</font> in the script).")
H2("4.7 Pooled vs within-year variation")
P("T01 found a pooled slope of -7.85 but per-year slopes between about 0 and -11. Both are right; they answer different questions. The pooled slope also picks up the "
  "<b>between-year</b> pattern (years with more solar had lower heat rates overall, partly for other reasons such as gas prices and new transmission). The per-year slopes "
  "only use <b>within-year</b> day-to-day variation, which is a cleaner estimate of solar's direct effect. When the two differ a lot, something else is changing over time.")
H2("4.8 Outliers and winsorizing")
P("<b>Winsorizing</b> caps extreme values at a percentile instead of deleting them (T01: 1st and 99th; T03: 0.5th and 99.5th). One absurd day from the 2022-23 gas "
  "crisis can't then dominate a regression that minimizes <i>squared</i> errors, since squaring makes big misses count far more.")
H2("4.9 Confounding, reverse causality and collinearity")
P("These are the three ways a regression can mislead you, and T01b ran into all three:")
B("<b>Confounding:</b> something else drives both variables. Battery fleet size grows steadily over time, as do transmission, exports and demand response. "
  "Any of them could be what the 'battery' term picks up. The fix was a competing <b>solar x time trend</b> term to see if batteries still mattered after accounting for time.",
  "<b>Reverse causality:</b> batteries discharge <i>more</i> on high-price days, so same-day discharge is partly caused by price. Using it as a regressor would bias the result. "
  "The fix was to measure fleet <i>capability</i> (trailing 90-day 95th percentile, shifted one day), which today's price can't affect.",
  "<b>Collinearity:</b> when two regressors move almost together (battery fleet and time), the model can't tell them apart, and standard errors blow up. That's why the "
  "'+ time trend' row in T01b has a much larger s.e. (0.095 vs 0.023).")
H2("4.10 Robustness checks")
P("A result you believe should survive reasonable changes to how it's estimated. T01b ran three versions: main model, plus a time trend, and excluding 2022-23. "
  "The verdict logic in the script requires the effect to hold up across these before calling it 'supported'.")
H2("4.11 Quantile regression (T03)")
P("OLS models the <b>average</b>. Quantile regression models a chosen <b>percentile</b>: the median (P50), the bad days (P90), the quiet days (P10). "
  "It minimizes a tilted absolute error called the pinball loss:")
code("""
pinball loss for quantile q:   q * (y - pred)      if y > pred   (under-predicted)
                              (1-q) * (pred - y)   if y < pred   (over-predicted)

For q = 0.9, under-predicting costs 9x more than over-predicting,
so the fitted line sits where about 90% of points fall below it.
""")
P("T03 fits <font face='Mono'>ihr ~ load + load²</font> at P10, P50 and P90. The <b>squared term</b> allows curvature, and the slope at any load is the derivative "
  "b1 + 2 x b2 x load. If the P90 line steepens faster than the P50 as load rises, the risk is concentrated in the tail: <b>convexity</b>.")
WATCH("A quadratic must curve the same way everywhere, so the P90 curve also bends up at the <i>low</i>-load end of the chart. That's a fitting artifact, not a real effect. "
      "Splines or binned estimates would avoid it.")
H2("4.12 Anomalies vs climatology (T02)")
P("<b>Climatology</b> is the normal value for a time of year (here, average hydro output for each calendar month). The <b>anomaly</b> is actual minus normal. "
  "Regressing on the anomaly instead of the raw level avoids confusing 'it's spring' with 'it's a wet spring'. In the forecast test, climatology is rebuilt from "
  "<i>past years only</i> for each test year, so the 'normal' never includes the future.")
YOU(["How to read a coefficient in its units, and what 'holding constant' means.",
     "What month fixed effects do.",
     "Why HAC standard errors are needed for daily market data.",
     "How an interaction term changes the interpretation, and how the delta method builds the CI.",
     "Why pooled and per-year slopes differ.",
     "Confounding vs reverse causality vs collinearity, each with the T01b example.",
     "What quantile regression measures that OLS can't."])
story.append(PageBreak())

# =====================================================================================
# 5. MACHINE LEARNING
# =====================================================================================
H1("5. Machine learning models")
H2("5.1 Persistence: the baseline")
P("<b>Persistence</b> predicts that tomorrow equals today. It sounds naive, but power prices are strongly autocorrelated, so it's very hard to beat. "
  "Any model that can't beat persistence has learned nothing useful. Every result in the project is reported against it.")
H2("5.2 Ridge regression")
P("Ridge is linear regression with a penalty on large coefficients:")
code("""
minimize   sum (y - Xb)^2   +   alpha * sum b^2
""")
B("The penalty (<b>regularization</b>) shrinks coefficients toward zero, which reduces overfitting when features are correlated, as these are.",
  "<font face='Mono'>RidgeCV</font> picks <font face='Mono'>alpha</font> from 20 values between 0.01 and 1000 by internal cross-validation.",
  "<b>Standardization</b> (<font face='Mono'>StandardScaler</font>) rescales each feature to mean 0, standard deviation 1. Without it, the penalty would punish features "
  "measured in large units differently from ones in small units.",
  "<b>One-hot encoding</b> turns month and weekday into 0/1 columns so the model doesn't treat December (12) as 'more' than January (1).",
  "A <b>Pipeline</b> plus <b>ColumnTransformer</b> bundles scaling, encoding and the model, so the scaler is fit only on training data. Fitting it on all data would be a subtle leak.")
H2("5.3 Target transformation: predicting heat rate, then multiplying by gas")
P("<font face='Mono'>HeatRateRidge</font> learns to predict IHR, then multiplies the prediction by the known gas price to get $/MWh. Gas levels moved from about $2 to "
  "$9 during the sample; a linear model in dollars would need different coefficients in each gas regime, but heat rate is far more stable. This model won at PJM West "
  "and Mass Hub, where prices really are gas-linked.")
H2("5.4 Gradient-boosted trees (LightGBM)")
P("A <b>decision tree</b> splits the data with yes/no questions (Is demand forecast above 110 GW? Is it July?) and predicts the average of each leaf. "
  "<b>Gradient boosting</b> builds hundreds of small trees in sequence; each one is fit to the errors the previous trees still make. LightGBM is a fast implementation.")
table([
    ["Setting used", "Value", "What it controls"],
    ["n_estimators", "300-400", "Number of trees"],
    ["learning_rate", "0.03", "How much each tree contributes. Small + many trees = steadier"],
    ["num_leaves", "15", "Tree complexity. Small = less overfitting"],
    ["min_child_samples", "20", "Smallest allowed leaf; stops fitting to a handful of days"],
    ["subsample / colsample_bytree", "0.8 / 0.8", "Each tree sees 80% of rows and features: adds randomness that reduces overfitting"],
], [1.9, 1.0, 3.6])
P("Trees capture <b>nonlinearities</b> and <b>interactions</b> automatically (e.g., high load matters more in summer), which linear models need to be told about.")
H2("5.5 Why trees can't extrapolate, and the fix")
KEY(["A tree predicts the average of training examples in a leaf, so it <b>can never predict a value outside the range it was trained on</b>. "
     "A LightGBM model trained through 2021 had never seen 2022's gas-crisis prices, so it kept predicting 2021-sized prices. "
     "On price levels it lost badly to persistence (MAE 18.97 vs 11.04 at SP15).",
     "The fix (<font face='Mono'>OnPersistence</font>): train the model on the <b>change</b> from the last price (y - price_lag), then add the last price back. "
     "Persistence becomes the floor, and the model only learns adjustments, which stay in a stable range in every regime. The same model then beat persistence in "
     "every test year (MAE 10.12). This is often called <b>residual modeling</b> or <b>modeling on a baseline</b>."])
H2("5.6 Loss functions")
table([
    ["Loss", "Penalizes", "Used for"],
    ["Squared error (L2)", "Big misses heavily", "Ridge, LightGBM on levels. Predicts the mean"],
    ["Huber", "Like L2 for small errors, like absolute error for large ones", "LightGBM on change. Robust to spike days dominating the fit"],
    ["Quantile (pinball)", "Asymmetric (section 4.11)", "P10 and P90 forecast bands"],
    ["Log loss", "Confident wrong probabilities", "Logistic regression and LightGBM classifier (T03)"],
], [1.5, 2.6, 2.4])
H2("5.7 Classification for spike days (T03)")
B("<b>Logistic regression</b> is a linear model passed through the S-shaped logistic function, so it outputs a probability between 0 and 1.",
  "<b>LightGBM classifier</b> is the boosted-tree version, also outputting a probability.",
  "Both used the same known features. Logistic won slightly (AUC 0.93 vs 0.91). On a small, low-noise problem, a simple model often matches or beats a complex one.")
H2("5.8 Partial dependence")
P("A partial dependence plot shows a model's average prediction as one feature changes while the others keep their actual values. T01 used it to check whether solar's "
  "effect is curved: the GBM's predicted IHR fell from 20.0 at 8% solar to 12.6 at 29%. It shows what the <i>model</i> learned, which is a tool for interpretation, not "
  "proof of cause.")
YOU(["Why persistence is a strong baseline for power prices.",
     "What regularization does and why features are standardized before ridge.",
     "How gradient boosting works in two sentences.",
     "Why a tree model can't forecast a price regime it hasn't seen, and how modeling the change fixes it.",
     "When you'd pick Huber or quantile loss over squared error."])
story.append(PageBreak())

# =====================================================================================
# 6. EVALUATION
# =====================================================================================
H1("6. Evaluation")
H2("6.1 Walk-forward (expanding-window) backtests")
code("""
Test 2022:  train on 2017-2021            -> predict 2022
Test 2023:  train on 2017-2022            -> predict 2023
Test 2024:  train on 2017-2023            -> predict 2024
...
""")
P("Random k-fold cross-validation shuffles days, so a model could train on July 15 and be tested on July 14. With autocorrelated market data that leaks the "
  "answer. Walk-forward respects time: every prediction uses only the past, mimicking real deployment. It also shows how performance changes by year, which is how "
  "the 2022 regime problem became visible.")
H2("6.2 Automated leakage tests")
P("<font face='Mono'>tests/test_pipeline.py</font> builds fake data where each day's demand equals its date number, so you can read off exactly which day a "
  "feature came from. It checks two things:")
B("Every lagged fundamental comes from a day <b>strictly before</b> the trade date.",
  "The backtest never trains on data from the year it's testing (a 'spy' model records the latest training year it saw).")
P("Testing for leakage with synthetic data, instead of trusting the code, is a habit worth copying in any forecasting project.")
H2("6.3 Point-forecast metrics")
table([
    ["Metric", "Definition", "Reads as"],
    ["MAE", "average of |prediction - actual|", "Typical miss in $/MWh. Robust, easy to explain"],
    ["RMSE", "square root of average squared error", "Like MAE but punishes big misses more. RMSE much larger than MAE means a few huge misses"],
    ["Bias", "average of (prediction - actual)", "Systematic over- or under-prediction. The level-LightGBM had +9.95: it was stuck too high after 2022"],
    ["Directional accuracy", "% of days the model called the up/down move right", "What a trader using the model to pick direction cares about"],
], [1.4, 2.4, 2.7])
H2("6.4 Interval coverage (calibration of bands)")
P("If the P10-P90 band is honest, 80% of actual prices should fall inside it. Results were 67-75% at all hubs: the bands are <b>too narrow</b>, meaning the model is "
  "overconfident. Fixes include conformal prediction or widening bands using recent errors. You shouldn't size risk off these bands until they're calibrated.")
H2("6.5 Classification metrics (T03)")
B("<b>Base rate:</b> how often spikes happen at all (11%). Every result should be compared to it.",
  "<b>AUC (ROC area):</b> the probability that a randomly chosen spike day gets a higher score than a randomly chosen normal day. 0.5 is a coin flip, 1.0 perfect. "
  "It measures <i>ranking</i>, not whether the probabilities are correct.",
  "<b>Brier score:</b> average squared difference between predicted probability and outcome (0 or 1). Lower is better. Compared against always predicting the base rate.",
  "<b>Precision in the top 10%:</b> of the days the model is most worried about, how many were spikes. 66% vs an 11% base rate. This is the most trader-friendly "
  "number: 'when it warns you, it's right two times out of three'.")
H2("6.6 Choosing a fair baseline and a fair label")
KEY(["A good result needs a baseline that's genuinely hard to beat. For spike days, 'yesterday was stretched' alone scored AUC 0.84 because heat waves last several "
     "days. The model's real contribution is the gap: 0.93 vs 0.84.",
     "Label definitions can quietly create fake results. The first spike label (heat rate above last year's 90th percentile) flagged 101 of 232 days in 2024. Cheap "
     "gas that year inflated <i>every</i> day's heat rate, so 'spike' just meant 'it's 2024'. The fix was a relative label: at least 1.5x the trailing 30-day median."])
YOU(["Why walk-forward and not random cross-validation.",
     "The difference between MAE and RMSE, and what a large bias tells you.",
     "What 72% coverage on an 80% band means.",
     "What AUC measures and what it doesn't.",
     "Why a 'yesterday-only' baseline was necessary for T03."])
story.append(PageBreak())

# =====================================================================================
# 7. THESES
# =====================================================================================
H1("7. The theses, walked through")
H2("T01: Solar cannibalization at SP15")
table([["Question", "Does more CAISO solar push the SP15 on-peak heat rate down?"],
       ["Method", "Yearly and monthly heat-rate tables; OLS of IHR on solar, wind, hydro, demand with month and weekday fixed effects and HAC s.e.; solar x year interaction; LightGBM partial dependence"],
       ["Result", "Spring median IHR 10.3 (2019) to 2.1 (2026) while spring solar share rose from 15% to 25%. Pooled: +10 points of solar is -7.85 (CI -9.39 to -6.31), n = 1,366, R² = 0.41"],
       ["Limits", "Henry Hub denominator distorts 2022-23; the on-peak block blends midday and evening, so true midday cannibalization is larger"]],
      [1.0, 5.5], header=False)
fig(REP / "T01_sp15_solar" / "ihr_vs_solar.png", "T01: spring heat rate falls as solar share rises. The 2023 spike is the western gas crisis, not a reversal.", 5.6)
H2("T01b: Do batteries blunt cannibalization?")
table([["Question", "Is solar's per-unit price effect shrinking because batteries absorb the midday surplus?"],
       ["Method", "Recovered CAISO batteries from hourly 'Other' data; fleet-capability proxy; solar x battery interaction; robustness against a time trend and without 2022-23; delta-method marginal-effect chart"],
       ["Result", "Not supported. Interaction -0.012 (p = 0.59); +0.153 with a time trend (p = 0.11); -0.0004 excluding 2022-23 (p = 0.98)"],
       ["Why it matters", "Batteries shift energy from noon to evening, both inside the HE7-22 block, so the block average barely moves. Their effect lives in intraday shape, which needs hourly prices (CAISO OASIS). The apparent 'flattening' in T01 was mostly the 2022-23 gas distortion."]],
      [1.0, 5.5], header=False)
fig(REP / "T01b_sp15_batteries" / "solar_effect_vs_batteries.png", "T01b: if batteries explained the per-year slopes (orange), they would follow the blue line. They scatter around it instead.", 5.6)
H2("T02: The Mid-C vs SP15 spread is a hydro story")
table([["Question", "Does Northwest hydro drive the Mid-C minus SP15 spread, and is it usable on the trade date?"],
       ["Method", "Hydro anomaly vs monthly climatology; OLS with BPA wind and load, CAISO solar and load, gas, fixed effects, HAC; quintile table; walk-forward ridge on the spread change using yesterday's anomaly"],
       ["Result", "+1 GW above normal: -$5.99/MWh (CI -6.82 to -5.17), R² = 0.55. Very dry days +$16.8, very wet days -$8.1. Forecast improvement over persistence: 4%"],
       ["Surprise", "Mid-C is above SP15 in spring on average, because solar crushes SP15 harder. Season alone is the wrong signal; the anomaly is the right one. Mid-C flipped from -$4.6 (2019-22) to +$15.3 (2023+)."],
       ["Limits", "Short, drought-heavy history for 'normal'; intertie transmission limits aren't in EIA data; regional gas differs from Henry Hub"]],
      [1.0, 5.5], header=False)
fig(REP / "T02_midc_hydro" / "spread_by_hydro.png", "T02: the spread falls steadily from very dry to very wet days.", 5.2)
H2("T03: PJM West convexity and spike days")
table([["Question", "Is the heat rate convex in load, and can spike days be seen coming?"],
       ["Method", "Summer quantile regression (P10/P50/P90) on load and load²; load-decile table; 'excess dollars' concentration; walk-forward logistic and LightGBM classifiers with a yesterday-only baseline"],
       ["Result", "P90 slope rises from 1.02 to 1.53 per GW between 94 and 121 GW. Top load decile = 39% of summer upside. AUC 0.93 (logistic), 0.91 (LightGBM), 0.84 baseline; 66% precision in the top 10% vs 11% base rate"],
       ["Limits", "This hub's price is the real-time index; RTO-wide load misses West-zone congestion; no implied-volatility data, so 'underpriced' can't be tested"]],
      [1.0, 5.5], header=False)
fig(REP / "T03_pjm_convexity" / "quantile_fan.png", "T03: the P90 line pulls away from the median as load rises. That is convexity.", 5.6)
H2("F01: Next-day forecast benchmark")
table([
    ["Hub", "Persistence MAE", "Best model", "Best MAE", "Improvement"],
    ["PJM West", "15.12", "Ridge on heat rate", "12.07", "20%"],
    ["Mass Hub", "15.16", "Ridge on heat rate", "13.12", "13%"],
    ["SP15", "11.04", "LightGBM on change", "10.12", "8%"],
    ["Palo Verde", "15.20", "LightGBM on change", "14.75", "3%"],
    ["Mid-C", "20.21", "LightGBM on change", "19.71", "2%"],
], [1.1, 1.3, 1.8, 1.0, 1.3])
P("Interpretation (a hypothesis, not yet tested): eastern prices follow gas and load, which the models see. Western prices depend on hydro, solar and regional gas "
  "prices that Henry Hub misses, so fundamentals add little there.")
story.append(PageBreak())

# =====================================================================================
# 8. LESSONS
# =====================================================================================
H1("8. Research lessons: three times the first answer was wrong")
P("These are worth knowing cold. They show the difference between running models and doing research. Each is a mistake that is easy to make and easy to miss.")
table([
    ["#", "First result", "What was wrong", "Fix", "Lesson"],
    ["1", "LightGBM lost to 'tomorrow = today' at SP15", "Trees can't predict outside their training range; 2022 prices were unseen", "Model the daily change, not the level", "Check whether your model class can represent the regime you're testing on"],
    ["2", "'Solar's effect is flattening, probably batteries'", "The steep 2022-23 slopes came from the gas-basis distortion, and batteries didn't explain the rest", "Ran T01b properly; reported 'not supported'", "A pattern in noisy yearly estimates isn't a trend. Test the explanation; report negatives"],
    ["3", "Spike-day AUC 0.88", "Cheap 2024 gas made 44% of days 'spikes', and heat waves are persistent", "Relative spike label; yesterday-only baseline", "Inspect your label's base rate by year; always compare to the dumbest reasonable model"],
], [0.25, 1.35, 1.75, 1.35, 1.8])
H2("The general workflow")
B("State the thesis as something that could turn out false, with a predicted sign.",
  "Pick the cleanest comparison (fixed effects, anomalies, within-year variation).",
  "Look at the data and the charts before trusting a number.",
  "Try to break it: robustness checks, competing explanations, excluding odd periods.",
  "Let the code write the verdict from the numbers, so the conclusion can't drift from the evidence.",
  "Write down the limits and the trade expression, labeled as a hypothesis.")
story.append(PageBreak())

# =====================================================================================
# 9. CODE MAP
# =====================================================================================
H1("9. Code map")
table([
    ["File", "What it does", "Concepts"],
    ["powerml/config.py", "Paths, hub definitions, hub-to-BA map, fuel codes", "Hubs, BAs"],
    ["powerml/data.py", "Download and cache ICE prices, Henry Hub, EIA-930 daily and hourly; recover CAISO batteries", "APIs, pagination, backoff, caching, time zones"],
    ["powerml/features.py", "Build one panel per hub; implied heat rate, shares, net load, calendar, lags; EXPLAIN vs KNOWN lists", "Feature engineering, merge_asof, look-ahead bias"],
    ["powerml/models.py", "Persistence, HeatRateRidge, GBM, OnPersistence; walk_forward() and Backtest.scores()", "Ridge, LightGBM, residual modeling, walk-forward, metrics"],
    ["scripts/fetch_data.py", "Pull and cache every input", "Pipeline orchestration"],
    ["scripts/forecast_benchmark.py", "Model contest for one hub; scores, coverage, chart, report", "Evaluation, quantile bands"],
    ["scripts/thesis_01_*.py", "Solar cannibalization", "OLS, fixed effects, HAC, interactions, partial dependence"],
    ["scripts/thesis_01b_*.py", "Batteries", "Interactions, delta method, confounding, reverse causality"],
    ["scripts/thesis_02_*.py", "Mid-C hydro spread", "Climatology, anomalies, spreads, walk-forward ridge"],
    ["scripts/thesis_03_*.py", "PJM convexity and spikes", "Quantile regression, classification, AUC, Brier"],
    ["tests/test_pipeline.py", "Two leakage guards on synthetic data", "Testing for leakage"],
], [1.75, 2.85, 1.9])
H2("Running it")
code("""
.venv\\Scripts\\python scripts\\fetch_data.py
.venv\\Scripts\\python scripts\\thesis_03_pjm_convexity.py
.venv\\Scripts\\python scripts\\forecast_benchmark.py --hub PJMW
.venv\\Scripts\\python -m pytest -q
""")
P("Each script writes a <font face='Mono'>report.md</font> and charts into <font face='Mono'>reports/</font>. A good way to learn: change one thing "
  "(the spike threshold, the test years, a feature) and predict what will happen before you rerun.")
story.append(PageBreak())

# =====================================================================================
# 10. INTERVIEW PREP
# =====================================================================================
H1("10. Review questions")
P("Try to answer each question before reading the answer. They mix concepts from every part of the guide.")
qa = [
    ("Summarize the project in three sentences.",
     "It uses free EIA data to test power-market claims and to forecast next-day on-peak prices at five U.S. hubs. It models the implied heat rate "
     "(power over gas) to strip out gas price moves. Its strongest result: PJM West's heat rate is convex in load, and spike days are predictable a day ahead "
     "(AUC 0.93 against 0.84 for a persistence baseline)."),
    ("Why study heat rate instead of price?",
     "Gas sets the marginal price most hours, so raw power prices mostly track gas. Dividing it out isolates grid fundamentals, and heat rate is the unit traders "
     "use for spark-spread and heat-rate positions."),
    ("How does the project avoid look-ahead bias?",
     "Separate 'explain' and 'known' feature sets, with known features using only information dated before the trade date. Walk-forward backtests by year. "
     "And unit tests on synthetic data that check both."),
    ("LightGBM first lost to persistence. Why, and what fixed it?",
     "Trees can't extrapolate beyond their training range, and 2022 prices were unseen. Predicting the change from the last price makes persistence the floor; "
     "with that change it beat persistence every year."),
    ("Which thesis failed, and what does the failure teach?",
     "T01b: batteries were expected to weaken solar's price impact. CAISO battery data was recovered from EIA's 'Other' category, a capability proxy avoided reverse "
     "causality, and the effect wasn't there. Batteries move energy within the on-peak block, so daily block prices can't show their effect; hourly prices could."),
    ("What does an HAC standard error fix?",
     "Autocorrelated errors. Market conditions persist for days, so ordinary standard errors would be too small and overstate significance."),
    ("How could the T03 result be traded?",
     "Because the payoff is convex in load, the value is in optionality: PJM West on-peak calls or heat-rate calls when the model's spike probability is high "
     "relative to implied volatility. Testing whether that is actually profitable needs implied-volatility data the repo doesn't have."),
    ("What are the most valuable next extensions?",
     "Hourly prices from CAISO OASIS to test batteries on intraday shape; regional gas prices to fix the western heat-rate distortion; calibrated forecast bands; "
     "and the ISO's own load forecast for a live version."),
    ("Why did the simple ridge model win in the East?",
     "PJM and New England prices are largely gas plus load, which is close to linear in heat-rate terms, so a regularized linear model captures most of it with "
     "less variance than trees."),
    ("What's the difference between AUC and precision in the top 10%?",
     "AUC measures ranking across all thresholds. Precision in the top 10% is what you'd get acting only on the model's strongest warnings: 66% against an 11% base rate."),
]
for q, a in qa:
    story.append(KeepTogether([Paragraph(f"<b>Q. {q}</b>", S["p"]), Paragraph(a, ParagraphStyle("ans", parent=S["b"], bulletFontName="Sans-Semi"), bulletText="A"), Spacer(1, 4)]))
story.append(PageBreak())

# =====================================================================================
# 11. GLOSSARY + STUDY PLAN
# =====================================================================================
H1("11. Glossary")
gl = [
    ("AUC", "Probability a random positive case is ranked above a random negative one"),
    ("Balancing authority (BA)", "Entity that balances supply and demand in an area; EIA-930 reports by BA"),
    ("Basis", "Price difference between two locations"),
    ("Brier score", "Mean squared error of predicted probabilities"),
    ("Climatology", "The normal value for a time of year"),
    ("Convexity", "Effect that grows faster than linearly; here, price vs load"),
    ("Day-ahead / real-time", "Next-day market vs the price that clears in the moment"),
    ("Delta method", "Way to get the standard error of a combination of coefficients"),
    ("Fixed effects", "Separate intercepts per group (month, weekday) to absorb what's typical for that group"),
    ("HAC / Newey-West", "Standard errors robust to autocorrelation and changing variance"),
    ("Heat rate (implied)", "Power price / gas price, in MMBtu/MWh"),
    ("Hub", "Named trading location that stands in for a region's price"),
    ("Huber loss", "Squared error for small misses, absolute error for big ones"),
    ("Leakage / look-ahead bias", "Using information a real forecaster wouldn't have had"),
    ("MAE / RMSE", "Average absolute error / root mean squared error"),
    ("Merit order / supply stack", "Plants ordered by marginal cost; the last one needed sets the price"),
    ("Net load", "Demand minus wind and solar"),
    ("On-peak", "Weekday hour-ending 7-22 block"),
    ("Partial dependence", "A model's average prediction as one feature varies"),
    ("Persistence", "Forecast that tomorrow equals today"),
    ("Pinball loss", "Asymmetric loss used to fit quantiles"),
    ("Quantile regression", "Regression for a chosen percentile rather than the mean"),
    ("Regularization", "Penalty on model complexity to reduce overfitting"),
    ("Spark spread", "Power price minus (plant heat rate x gas price)"),
    ("Walk-forward", "Train on the past, test on the next period, roll forward"),
    ("Winsorize", "Cap extreme values at a chosen percentile"),
]
table([["Term", "Meaning"]] + [list(g) for g in gl], [1.8, 4.7])
story.append(PageBreak())
H1("Study plan: what to learn next")
table([
    ["Topic", "Why", "Where to start"],
    ["Merit order and LMPs", "Foundation for everything", "ISO market primers: PJM Learning Center, CAISO and ERCOT training pages"],
    ["Regression inference", "HAC, fixed effects, interactions", "'Introductory Econometrics' (Wooldridge), chapters on OLS, inference and time series"],
    ["Time-series forecasting", "Baselines, backtesting, calibration", "'Forecasting: Principles and Practice' (Hyndman, free online)"],
    ["Gradient boosting", "How LightGBM really works", "LightGBM docs, 'Parameters Tuning' page; XGBoost paper intro"],
    ["Quantile and probabilistic forecasting", "Fixing the 72% coverage", "Conformal prediction tutorials; pinball loss"],
    ["Options on power", "The T03 trade expression", "Hull, 'Options, Futures, and Other Derivatives': options basics and volatility"],
], [1.7, 1.7, 3.1])
P("Suggested exercises, in order: (1) recompute one number from a report by hand in a notebook; (2) rerun T01 excluding 2022-23 and see what changes; "
  "(3) recalibrate the P10-P90 bands so coverage reaches 80%; (4) pull CAISO OASIS hourly prices and test batteries on the midday-to-evening spread.")

doc = SimpleDocTemplate(str(OUT), pagesize=letter, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                        topMargin=0.8 * inch, bottomMargin=0.85 * inch,
                        title="Power Market ML - Learning Guide", author="power-market-ml")
doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=footer)
print(OUT)
