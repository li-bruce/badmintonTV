"""Export transport schemas: python -m packages.contracts --output DIR."""

import argparse
import json
from pathlib import Path

from . import schemas


def main() -> None:
    parser = argparse.ArgumentParser(description="Export badmintonTV v1.0 JSON schemas")
    parser.add_argument("--output", type=Path, help="Directory for one schema file per contract")
    args = parser.parse_args()
    exported = schemas()
    if args.output is None:
        print(json.dumps(exported, ensure_ascii=False, indent=2))
        return
    args.output.mkdir(parents=True, exist_ok=True)
    for name, schema in exported.items():
        destination = args.output / f"{name}.schema.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
    print(f"Exported {len(exported)} v1.0 schemas to {args.output}")


if __name__ == "__main__":
    main()
