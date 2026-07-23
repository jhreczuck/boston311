"""Daily dashboard refresh: rebuilds dashboard.html from the live database,
then commits + force-pushes it (single amended commit, no growing history -
this repo's only job is handing the file to the cloud publish routine) to
the dashboard_repo remote, which a scheduled cloud agent then republishes.

Usage:
    python refresh_dashboard.py
"""

import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).parent
REPO_DIR = BASE / "dashboard_repo"
PYTHON = str(BASE / "venv" / "Scripts" / "python.exe")


def run(cmd, cwd):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    run([PYTHON, "export_public_dashboard.py"], cwd=BASE)
    run([PYTHON, "build_dashboard.py"], cwd=BASE)

    shutil.copy2(BASE / "dashboard.html", REPO_DIR / "dashboard.html")
    # index.html is a duplicate copy so GitHub Pages serves it automatically
    # at the repo root, with no login gate - dashboard.html stays as the name
    # the cloud republish routine looks for.
    shutil.copy2(BASE / "dashboard.html", REPO_DIR / "index.html")

    run(["git", "add", "dashboard.html", "index.html"], cwd=REPO_DIR)

    has_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_DIR, capture_output=True
    ).returncode == 0

    if has_commit:
        run(["git", "commit", "--amend", "--no-edit"], cwd=REPO_DIR)
        run(["git", "push", "--force", "origin", "HEAD"], cwd=REPO_DIR)
    else:
        run(["git", "commit", "-m", "Daily dashboard refresh"], cwd=REPO_DIR)
        run(["git", "push", "-u", "origin", "HEAD"], cwd=REPO_DIR)

    print("Dashboard refreshed and pushed.")


if __name__ == "__main__":
    main()
