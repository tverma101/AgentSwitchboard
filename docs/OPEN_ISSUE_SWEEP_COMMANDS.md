# Open-issue sweep commands

```bash
# Show deterministic plan only
uv run python scripts/certify_open_issues.py --list

# Execute deterministic shared certification
uv run python scripts/certify_open_issues.py

# Include literal-Claude/provider/device lanes explicitly
uv run python scripts/certify_open_issues.py --live

# Local Codex browser plugin canary
uv run python scripts/smoke_codex_browser.py --family chrome

# Compare normalized native and AgentSwitchboard observations
uv run python scripts/compare_native_harness.py native.json harness.json \
  --output comparison.json
```

A deterministic green result does not certify a live provider, installed Claude
surface, browser backend, or real compaction boundary.
