"""Thin standard-protocol wrapper; platform callers still use packages.models run."""
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.models.protocol import main

if __name__ == "__main__":
    raise SystemExit(main(["run", *sys.argv[1:]]))
