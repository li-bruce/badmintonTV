"""Convenience wrapper for the existing worker request/result protocol.

The platform worker remains responsible for GPU leases and watchdogs. This
script does not schedule jobs, install dependencies or download model files.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.models.protocol import main


if __name__ == "__main__":
    raise SystemExit(main(["run", *sys.argv[1:]]))
