"""Assembles dashboard.html from dashboard_template.html + dashboard_data.json
+ the embedded font, for publishing via Artifact.

Usage:
    python export_public_dashboard.py   # refresh dashboard_data.json first
    python build_dashboard.py
"""

from pathlib import Path

BASE = Path(__file__).parent

template = (BASE / "dashboard_template.html").read_text(encoding="utf-8")
data_json = (BASE / "dashboard_data.json").read_text(encoding="utf-8")
font_b64 = (BASE / "oswald_b64.txt").read_text(encoding="utf-8")

out = template.replace("__DATA_JSON__", data_json).replace("__FONT_B64__", font_b64)

out_path = BASE / "dashboard.html"
out_path.write_text(out, encoding="utf-8")
print(f"Wrote {out_path} ({out_path.stat().st_size:,} bytes)")
