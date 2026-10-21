"""Builds a one-page PDF fact sheet (factsheet.pdf) from dashboard_data.json.

Usage:
    python export_public_dashboard.py   # refresh dashboard_data.json first
    python build_factsheet.py
"""

import json
from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

BASE = Path(__file__).parent
d = json.loads((BASE / "dashboard_data.json").read_text(encoding="utf-8"))

INK, INK2, MUTED = HexColor("#0b0b0b"), HexColor("#52514e"), HexColor("#898781")
ACCENT, ORANGE, RED = HexColor("#1baf7a"), HexColor("#eb6834"), HexColor("#d03b3b")
PAPER, LINE = HexColor("#f4f3ee"), HexColor("#d9d7cd")

# ---- numbers ---------------------------------------------------------------
cmp_ = {r["request_group"]: r for r in d["resolution_time_comparison"]["rows"]}
conf = cmp_["Confirmed bike lane blocking"]
poss = cmp_["Possible bike lane blocking"]
other = cmp_["Other Parking/Vehicle/Bicycle Requests"]
n_conf = conf["closed_count"] + conf["open_count"]
n_poss = poss["closed_count"] + poss["open_count"]
n_total = n_conf + n_poss
outcomes = {r["outcome"]: r["total"] for r in d["resolution_outcomes"]["rows"]}
closed_noted = sum(outcomes.values())
enforced = outcomes.get("Ticketed", 0) + outcomes.get("Towed", 0)
gov = d["government_vehicle_summary"]["rows"]
gov_total = sum(r["total"] for r in gov)
police = next((r["total"] for r in gov if r["agency"] == "Police"), 0)
chronic = d["chronic_locations"]["rows"][:5]
first = min(r["requested_datetime"] for r in d["bike_lane_records"]["rows"])
as_of = datetime.fromisoformat(d["generated_at"]).astimezone()

W, H = letter
M = 42
c = canvas.Canvas(str(BASE / "factsheet.pdf"), pagesize=letter)
c.setTitle("Bike Lanes, Blocked - Boston 311 Fact Sheet")
c.setAuthor("jhreczuck")

# ---- header ----------------------------------------------------------------
c.setFillColor(PAPER); c.rect(0, 0, W, H, stroke=0, fill=1)
c.setFillColor(ACCENT); c.rect(0, H - 8, W, 8, stroke=0, fill=1)
c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 9)
c.drawString(M, H - 34, "BOSTON 311 SERVICE REQUESTS  |  FACT SHEET")
c.setFillColor(INK); c.setFont("Helvetica-Bold", 30)
c.drawString(M, H - 68, "Bike Lanes, Blocked")
c.setFillColor(INK2); c.setFont("Helvetica", 10.5)
c.drawString(M, H - 86,
    f"{n_total:,} reports to 311 of vehicles in Boston bike lanes  ·  "
    f"{datetime.fromisoformat(first).strftime('%b %d').replace(' 0', ' ')}"
    f" – {as_of.strftime('%b %d, %Y').replace(' 0', ' ')}")
c.setStrokeColor(ACCENT); c.setLineWidth(2); c.line(M, H - 96, W - M, H - 96)

# ---- stat tiles ------------------------------------------------------------
tiles = [
    (f"{n_total:,}", "bike lane reports", f"{n_conf:,} confirmed by complaint text,\n{n_poss:,} possible by location", INK),
    (f"{conf['pct_closed']:.0f}%", "confirmed reports closed", f"vs {other['pct_closed']:.0f}% for other parking,\nvehicle and bicycle requests", RED),
    (f"{enforced}", "ticketed or towed", f"of {closed_noted:,} closed cases with a note\n({outcomes.get('Ticketed',0)} ticketed, {outcomes.get('Towed',0)} towed)", ACCENT),
    (f"{gov_total}", "government vehicles", f"{police} police; also BTD, MBTA, city\n(hand-reviewed)", ORANGE),
]
tw, gap, ty = (W - 2 * M - 3 * 10) / 4, 10, H - 190
for i, (big, label, sub, col) in enumerate(tiles):
    x = M + i * (tw + gap)
    c.setFillColor(white); c.setStrokeColor(LINE); c.setLineWidth(0.6)
    c.roundRect(x, ty, tw, 82, 6, stroke=1, fill=1)
    c.setFillColor(col); c.rect(x, ty + 82 - 3, tw, 3, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 26); c.drawString(x + 10, ty + 48, big)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 8.5); c.drawString(x + 10, ty + 35, label)
    c.setFillColor(MUTED); c.setFont("Helvetica", 7)
    for j, line in enumerate(sub.split("\n")):
        c.drawString(x + 10, ty + 24 - j * 9, line)


def section(y, title):
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 12); c.drawString(M, y, title)
    c.setStrokeColor(LINE); c.setLineWidth(0.6); c.line(M, y - 5, W - M, y - 5)


# ---- response comparison table ---------------------------------------------
y = ty - 28
section(y, "How the city responds, vs. the rest of the same queue")
cols = [M, M + 200, M + 270, M + 340, M + 450]
heads = ["Request group", "Reports", "% closed", "Median hrs to close", "% on time"]
rows = [
    ("Confirmed bike lane blocking", n_conf, conf),
    ("Possible (within 15 m of a bike lane)", n_poss, poss),
    ("Other parking / vehicle / bicycle", other["closed_count"] + other["open_count"], other),
]
ry = y - 24
c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 7.5)
for x, h in zip(cols, heads):
    c.drawString(x, ry, h.upper())
for name, n, r in rows:
    ry -= 17
    c.setFillColor(INK); c.setFont("Helvetica-Bold" if name.startswith("Confirmed") else "Helvetica", 9)
    vals = [name, f"{n:,}", f"{r['pct_closed']:.1f}%", f"{r['median_hours_to_close']:.1f}", f"{r['pct_on_time']:.1f}%"]
    for x, v in zip(cols, vals):
        c.drawString(x, ry, v)
    c.setStrokeColor(LINE); c.setLineWidth(0.3); c.line(M, ry - 5, W - M, ry - 5)

# ---- outcomes bars + chronic streets, side by side -------------------------
y = ry - 32
half = (W - 2 * M - 24) / 2
c.setFillColor(INK); c.setFont("Helvetica-Bold", 12)
c.drawString(M, y, "When a case closes, what happened")
c.drawString(M + half + 24, y, "Streets hit week after week")
c.setStrokeColor(LINE); c.setLineWidth(0.6)
c.line(M, y - 5, M + half, y - 5); c.line(M + half + 24, y - 5, W - M, y - 5)
c.setFillColor(MUTED); c.setFont("Helvetica", 7.5)
c.drawString(M, y - 17, f"City closure notes on {closed_noted:,} closed Confirmed + Possible cases.")
c.drawString(M + half + 24, y - 17, "Reports on or near the street, all 26 weeks since tracking began.")

bar_x, bar_w = M + 82, half - 120
mx = max(outcomes.values())
colmap = {"Ticketed": ACCENT, "Towed": ACCENT, "Gone/Cleared": MUTED, "Not Applicable": MUTED}
by = y - 36
for name, v in sorted(outcomes.items(), key=lambda kv: -kv[1]):
    c.setFillColor(INK2); c.setFont("Helvetica", 8.5); c.drawString(M, by, name)
    c.setFillColor(colmap.get(name, HexColor("#b9b7ad")))
    c.rect(bar_x, by - 2, max(2, bar_w * v / mx), 10, stroke=0, fill=1)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 8.5)
    c.drawString(bar_x + max(2, bar_w * v / mx) + 5, by, f"{v:,}")
    by -= 17

cx = M + half + 24
cy = y - 36
cmx = max(r["total_incidents"] for r in chronic)
for r in chronic:
    c.setFillColor(INK2); c.setFont("Helvetica", 8.5); c.drawString(cx, cy, r["street"])
    c.setFillColor(ORANGE)
    cw = (half - 150) * r["total_incidents"] / cmx
    c.rect(cx + 100, cy - 2, cw, 10, stroke=0, fill=1)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 8.5)
    c.drawString(cx + 100 + cw + 5, cy, f"{r['total_incidents']:,}")
    cy -= 17

# ---- takeaways -------------------------------------------------------------
y = min(by, cy) - 14
section(y, "What stands out")
pts = [
    f"Only {conf['pct_closed']:.0f}% of confirmed bike lane reports are ever closed, about half the {other['pct_closed']:.0f}% rate for comparable requests.",
    f"Even when the city does close one (median {conf['median_hours_to_close']:.1f} hrs), it is not fast enough: only {conf['pct_on_time']:.0f}% of reports meet the city's own SLA target, vs {other['pct_on_time']:.0f}% for comparable requests.",
    f"Of {closed_noted:,} closed cases with a closure note, {enforced} ({enforced / closed_noted * 100:.0f}%) ended in a ticket or tow; "
    f"{outcomes.get('Gone/Cleared', 0)} ({outcomes.get('Gone/Cleared', 0) / closed_noted * 100:.0f}%) were closed because the vehicle was already gone.",
    f"{gov_total} reports involve police, BTD, MBTA or city vehicles themselves parked in the lane ({police} police).",
]
py = y - 22
for p in pts:
    c.setFillColor(ACCENT); c.circle(M + 3, py + 3, 2, stroke=0, fill=1)
    c.setFillColor(INK); c.setFont("Helvetica", 9)
    # simple wrap
    words, line, lines = p.split(), "", []
    for w in words:
        t = (line + " " + w).strip()
        if c.stringWidth(t, "Helvetica", 9) > W - 2 * M - 16:
            lines.append(line); line = w
        else:
            line = t
    lines.append(line)
    for ln in lines:
        c.drawString(M + 12, py, ln); py -= 12
    py -= 3

# ---- ask placeholder -------------------------------------------------------
py -= 4
ask = (
    "Boston has built bike lanes because riders are at real risk of being hit without them. "
    "We want to use them, but they are consistently blocked. Our only recourse is to report "
    "through 311 - and 311 resolves bike lane blocking at one of the lowest rates of any request type "
    f"(only {conf['pct_closed']:.0f}% of bike lane reports get closed, versus {other['pct_closed']:.0f}% of comparable parking requests and over 80% of requests in most other 311 categories*). "
    "Few reports end in enforcement."
)
ask_bold = "We request a dramatic increase in timely enforcement of bike lane blocking."
ask_lines = []
for text, font in ((ask, "Helvetica"), (ask_bold, "Helvetica-Bold")):
    line = ""
    for w in text.split():
        t = (line + " " + w).strip()
        if c.stringWidth(t, font, 10) > W - 2 * M - 24:
            ask_lines.append((line, font)); line = w
        else:
            line = t
    ask_lines.append((line, font))
box_h = 30 + 13.5 * len(ask_lines) + 4
c.setFillColor(white); c.setStrokeColor(ACCENT); c.setLineWidth(1)
c.roundRect(M, py - box_h + 4, W - 2 * M, box_h, 6, stroke=1, fill=1)
c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 8.5); c.drawString(M + 12, py - 10, "OUR ASK")
ay = py - 28
for line, font in ask_lines:
    c.setFillColor(INK); c.setFont(font, 10); c.drawString(M + 12, ay, line); ay -= 13.5

# ---- footer ----------------------------------------------------------------
c.setFillColor(MUTED); c.setFont("Helvetica", 7)
c.drawString(M, 46, "Source: Boston Open311 API (311.boston.gov). Confirmed = complaint text names a bike lane; Possible = no such text, but location is within 15 m of a mapped bike lane.")
c.drawString(M, 66, "*City-wide comparison: of the 20 request types with 150+ cases opened Apr 30 - Jul 21, 2026, confirmed bike lane reports had the lowest")
c.drawString(M, 56, "closure rate (11.8%); 12 of the 20 types closed over 80% of their requests.")
c.drawString(M, 36, "Closure outcomes are categorized from the city's own closure notes. Government-vehicle cases were hand-reviewed. Methodology and SQL are open source.")
c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 8)
c.drawString(M, 22, "jhreczuck.github.io/boston311-dashboard")
c.setFillColor(MUTED); c.setFont("Helvetica", 7)
c.drawRightString(W - M, 22, f"Data as of {as_of.strftime('%b %d, %Y').replace(' 0', ' ')}")

c.showPage()
c.save()
print("Wrote", BASE / "factsheet.pdf")
