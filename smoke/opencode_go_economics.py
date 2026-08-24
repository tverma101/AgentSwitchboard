"""Compare native OpenCode Go and Harness cache/cost benchmark receipts."""

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
    parser.add_argument(
        "--harness",
        "--fcc",
        dest="harness",
        required=True,
        help="Harness/Claude Code receipt JSONL",
    )
    parser.add_argument("--max-cost-regression-pct", type=float, default=5.0)
    parser.add_argument(
        "--max-cache-share-gap-points",
        type=float,
        default=3.0,
        help="maximum Harness cache-read-share deficit versus native, in points",
    )
    parser.add_argument(
        "--min-cache-read-share",
        type=float,
        default=None,
        help="legacy explicit absolute cache-read gate",
    )
    parser.add_argument(
        "--max-retry-amplification-delta",
        type=float,
        default=0.02,
        help="maximum Harness retry-amplification increase versus native",
    )
    args = parser.parse_args()

    try:
        native_metadata, native_rows = load_receipt(args.native)
        harness_metadata, harness_rows = load_receipt(args.harness)
        comparison = compare_receipts(
            native_rows,
            harness_rows,
            native_metadata=native_metadata,
            harness_metadata=harness_metadata,
        )
    except ValueError as exc:
        parser.error(str(exc))
    comparison["receipts"] = {
        "native": native_metadata,
        "harness": harness_metadata,
        "fcc": harness_metadata,
    }
    print(json.dumps(comparison, indent=2, sort_keys=True))

    regression = float(comparison["estimated_cost_regression_pct"])
    harness_share = float(comparison["harness"]["cache_read_share"])
    cache_gap = float(comparison["cache_read_share_gap_percentage_points"])
    retry_delta = float(comparison["retry_amplification_delta"])
    if regression > args.max_cost_regression_pct:
        return 1
    if args.min_cache_read_share is not None:
        cache_gate_failed = harness_share < args.min_cache_read_share
    else:
        cache_gate_failed = cache_gap > args.max_cache_share_gap_points
    if cache_gate_failed:
        return 1
    if retry_delta > args.max_retry_amplification_delta:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
