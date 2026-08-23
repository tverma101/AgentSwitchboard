#!/usr/bin/env python3
"""Run the reproducible OpenCode Go synthetic or explicitly opt-in live benchmark."""

import argparse
import asyncio
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smoke.lib.opencode_go_transport import (  # noqa: E402
    TransportBenchmarkConfig,
    run_transport_benchmark,
    write_receipt,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic", "live"), default="synthetic")
    parser.add_argument("--model", default="qwen3.7-plus")
    parser.add_argument("--samples", default="1,100,1000")
    parser.add_argument("--response-bytes", type=int, default=65_536)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".smoke-results/opencode-go-transport.json"),
    )
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--proxy", default="")
    args = parser.parse_args()
    samples = tuple(
        int(value.strip()) for value in args.samples.split(",") if value.strip()
    )
    config = TransportBenchmarkConfig(
        mode=args.mode,
        model=args.model,
        samples=samples,
        response_bytes=args.response_bytes,
        output_path=args.output,
        base_url=args.base_url or "https://opencode.ai/zen/go/v1",
        proxy=args.proxy,
    )
    receipt = asyncio.run(run_transport_benchmark(config))
    receipt["command"] = "uv run python " + " ".join(
        shlex.quote(value) for value in sys.argv
    )
    write_receipt(receipt, config.output_path)
    print(config.output_path)


if __name__ == "__main__":
    main()
