"""Build or verify the isolated, pinned Fine-Badminton annotation catalog."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import sys

from packages.library.annotation_catalog import load_json, publish_catalog, verify_catalog
from packages.library.storage import DEFAULT_PROJECT_ROOT, QuotaManager


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--config", default="configs/library/annotation_catalog.json")
    args = parser.parse_args(argv)
    try:
        config = load_json(args.config)
        if args.command == "build":
            result = publish_catalog(QuotaManager(), config)
        else:
            result = verify_catalog(DEFAULT_PROJECT_ROOT, config)
        result["checked_at"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, csv.Error) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
