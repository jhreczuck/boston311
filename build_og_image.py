"""Generates og-image.png (1200x630, the standard Open Graph size) for link
previews when this project's pages are shared. Pulls the current headline
numbers from dashboard_data.json so the preview stays accurate day to day.

Usage:
    python export_public_dashboard.py   # refresh dashboard_data.json first
    python build_og_image.py
"""

import base64
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).parent

BG = "#f4f3ee"
INK = "#0b0b0b"
INK_2 = "#52514e"
ACCENT = "#1baf7a"
CRITICAL = "#d03b3b"

W, H = 1200, 630


def load_font(size, weight=600):
    font_bytes = base64.b64decode((BASE / "oswald_b64.txt").read_text(encoding="utf-8"))
    font = ImageFont.truetype(io.BytesIO(font_bytes), size)
    try:
        font.set_variation_by_axes([weight])
    except Exception:
        pass
    return font


def main():
    data = json.loads((BASE / "dashboard_data.json").read_text(encoding="utf-8"))
    cmp_rows = data["resolution_time_comparison"]["rows"]
    confirmed = next(r for r in cmp_rows if r["request_group"] == "Confirmed bike lane blocking")
    possible = next(r for r in cmp_rows if r["request_group"] == "Possible bike lane blocking")
    total = confirmed["closed_count"] + confirmed["open_count"] + possible["closed_count"] + possible["open_count"]
    still_open = confirmed["open_count"] + possible["open_count"]

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # top accent bar
    draw.rectangle([0, 0, W, 10], fill=ACCENT)

    eyebrow_font = load_font(24, 600)
    title_font = load_font(84, 600)
    stat_font = load_font(56, 600)
    label_font = load_font(22, 500)

    draw.text((70, 60), "BOSTON OPEN DATA  ·  311 SERVICE REQUESTS", font=eyebrow_font, fill=ACCENT)
    draw.text((68, 110), "Bike Lanes, Blocked", font=title_font, fill=INK)

    stats = [
        (f"{total:,}", "REPORTS IDENTIFIED", INK),
        (f"{still_open:,}", "STILL OPEN", CRITICAL),
    ]
    x = 70
    y = 320
    for value, label, color in stats:
        draw.text((x, y), value, font=stat_font, fill=color)
        draw.text((x, y + 78), label, font=label_font, fill=INK_2)
        x += 420

    draw.text((70, H - 70), "jhreczuck.github.io/boston311-dashboard", font=label_font, fill=INK_2)

    out_path = BASE / "og-image.png"
    img.save(out_path)
    print(f"Wrote {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
