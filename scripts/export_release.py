#!/usr/bin/env python3
"""Create a clean source export from tracked repository files."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True
    )
    return [Path(value) for value in result.stdout.decode().split("\0") if value]


def export(root: Path, destination: Path) -> int:
    destination = destination.resolve()
    if destination == root or root in destination.parents:
        raise SystemExit("destination must be outside the repository")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    count = 0
    for relative in tracked_files(root):
        if relative.name in {".env", ".env.local"} or any(part in {".git", ".venv", "node_modules"} for part in relative.parts):
            continue
        source = root / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Export tracked Eivon source files")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    count = export(root, args.destination)
    print(f"Exported {count} tracked files to {args.destination.resolve()}")


if __name__ == "__main__":
    main()
