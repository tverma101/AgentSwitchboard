#!/usr/bin/env python3
"""Compare normalized native OpenCode and Harness observations."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smoke.lib.native_harness_comparator import (  # noqa: E402
    compare_paths,
    load_observation,
    write_comparison,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare metadata-only observations for the same logical scenario "
            "through native OpenCode and Harness."
        )
    )
    parser.add_argument("native", type=Path, help="native observation JSON")
    parser.add_argument("harness", type=Path, help="Harness observation JSON")
    parser.add_argument(
        "--output",
        type=Path,
        help="optional destination for the comparison receipt",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    receipt = compare_paths(
        load_observation(args.native),
        load_observation(args.harness),
    )
    if args.output is not None:
        write_comparison(receipt, args.output)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
