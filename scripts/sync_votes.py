#!/usr/bin/env python3
"""Export + validate the versioned votes.csv adjudication layer.

Warehouse is the writer. Sheets is an optional read-only coverage diff.
Runtime scoring must not fetch Sheets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vact.analysis.votes import sync_votes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-version", default="2021")
    parser.add_argument("--warehouse", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--sheets",
        action="store_true",
        help="Write data/reports/votes_sheets_diff.md (read-only).",
    )
    args = parser.parse_args(argv)
    result = sync_votes(
        map_version=args.map_version,
        warehouse_path=args.warehouse,
        out_path=args.out,
        sheets=args.sheets,
    )
    diff = result["diff"]
    print(f"synced {result['path']} n={result['n']}")
    print(
        f"diff +{len(diff['added'])} -{len(diff['removed'])} ~{len(diff['changed'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
