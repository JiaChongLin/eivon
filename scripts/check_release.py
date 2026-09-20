"""Offline release checks used before publishing an Eivon repository."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for command in [
    [str(ROOT / ".venv/bin/ruff"), "check", "src", "tests", "examples"],
    [str(ROOT / ".venv/bin/python"), "-m", "pytest", "-q"],
    ["npm", "run", "build", "--prefix", "console"],
]:
    print("$", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)
print("Release checks passed")
