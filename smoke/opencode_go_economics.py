"""Compare native OpenCode Go and FCC cache/cost benchmark receipts."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smoke.lib.opencode_go_economics import (  # noqa: E402
    compare_receipts,
    load_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", required=True, help="native OpenCode receipt JSONL")
    parser.add_argument("--fcc", required=True, help="FCC/Claude Code receipt JSONL")
    parser.add_argument("--max-cost-regression-pct", type=float, default=5.0)
    parser.add_argument(
        "--max-cache-share-gap-points",
        type=float,
        default=3.0,
        help="maximum FCC cache-read-share deficit versus native, in percentage points",
    )
    parser.add_argument(
        "--min-cache-read-share",
        type=float,
        default=None,
        help="legacy explicit absolute cache-read gate; native-relative comparison is the default",
    )
    args = parser.parse_args()

    native_metadata, native_rows = load_receipt(args.native)
    fcc_metadata, fcc_rows = load_receipt(args.fcc)
    for label, metadata in (("native", native_metadata), ("fcc", fcc_metadata)):
        if not isinstance(metadata.get("commit_sha"), str):
            parser.error(f"{label} receipt metadata must include commit_sha")
    comparison = compare_receipts(native_rows, fcc_rows)
    comparison["receipts"] = {
        "native": native_metadata,
        "fcc": fcc_metadata,
    }
    print(json.dumps(comparison, indent=2, sort_keys=True))

    regression = float(comparison["estimated_cost_regression_pct"])
    fcc_share = float(comparison["fcc"]["cache_read_share"])
    cache_gap = float(comparison["cache_read_share_gap_percentage_points"])
    if regression > args.max_cost_regression_pct:
        return 1
    if args.min_cache_read_share is not None:
        cache_gate_failed = fcc_share < args.min_cache_read_share
    else:
        cache_gate_failed = cache_gap > args.max_cache_share_gap_points
    if cache_gate_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
