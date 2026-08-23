"""Compare native OpenCode Go and FCC cache/cost benchmark receipts."""

import argparse
import json

from smoke.lib.opencode_go_economics import compare_receipts, load_jsonl


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", required=True, help="native OpenCode receipt JSONL")
    parser.add_argument("--fcc", required=True, help="FCC/Claude Code receipt JSONL")
    parser.add_argument("--max-cost-regression-pct", type=float, default=5.0)
    parser.add_argument("--min-cache-read-share", type=float, default=0.98)
    args = parser.parse_args()

    comparison = compare_receipts(load_jsonl(args.native), load_jsonl(args.fcc))
    print(json.dumps(comparison, indent=2, sort_keys=True))

    regression = float(comparison["estimated_cost_regression_pct"])
    fcc_share = float(comparison["fcc"]["cache_read_share"])
    if regression > args.max_cost_regression_pct:
        return 1
    if fcc_share < args.min_cache_read_share:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
