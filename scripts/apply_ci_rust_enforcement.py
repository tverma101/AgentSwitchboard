from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


workflow = Path(".github/workflows/tests.yml")
workflow.write_text(
    '''# Branch protection: require every public gate this workflow reports:
#   Ban suppressions and legacy annotations
#   ruff-format, ruff-check, ty, pytest
# The protected `pytest` context is a final gate over both pytest-suite and rust-tui.
# GitHub may prefix with the workflow name (e.g. "CI / ruff-format"); use the names the branch protection UI offers after a run.

name: CI

env:
  UV_MALWARE_CHECK: "1"
  UV_PREVIEW_FEATURES: "malware-check"

on:
  push:
    branches: [main, master]
  # Run on every PR target, including chained release-train and design PRs.
  pull_request:
  merge_group:
  workflow_dispatch:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  no-suppressions-or-legacy-annotations:
    name: Ban suppressions and legacy annotations
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: ${{ github.event.pull_request.head.sha || github.ref }}
          repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}
          fetch-depth: 1

      - name: "Fail on type ignores and legacy future annotations"
        run: |
          if grep -rE '# type: ignore|# ty: ignore|from __future__ import annotations' --include='*.py' . --exclude-dir=.venv --exclude-dir=.git; then
            echo "::error::type: ignore / ty: ignore comments and legacy future annotations are not allowed. Fix the underlying type/import issue instead."
            exit 1
          fi
          exit 0

  quality:
    name: ${{ matrix.id }}
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
    strategy:
      fail-fast: false
      matrix:
        include:
          - id: ruff-format
            run: uv run --no-sync ruff format --check
          - id: ruff-check
            run: uv run --no-sync ruff check
          - id: ty
            run: uv run --no-sync ty check
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: ${{ github.event.pull_request.head.sha || github.ref }}
          repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}
          fetch-depth: 1

      - name: Install uv
        uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d
        with:
          version: "0.11.16"
          enable-cache: true
          cache-python: false

      - name: Prepare project environment
        run: uv sync --locked

      - name: Run
        run: ${{ matrix.run }}

  pytest-suite:
    name: pytest-suite
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: ${{ github.event.pull_request.head.sha || github.ref }}
          repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}
          fetch-depth: 1

      - name: Install uv
        uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d
        with:
          version: "0.11.16"
          enable-cache: true
          cache-python: false

      - name: Prepare project environment
        run: uv sync --locked

      - name: Run full Python suite
        run: uv run --no-sync pytest -q --tb=short

  rust-tui:
    name: rust-tui
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: ${{ github.event.pull_request.head.sha || github.ref }}
          repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}
          fetch-depth: 1

      - name: Install pinned Rust toolchain
        run: rustup toolchain install 1.88.0 --profile minimal --component rustfmt,clippy

      - name: Format native control center in CI workspace
        run: cargo +1.88.0 fmt --manifest-path src/free_claude_code/native_tui/Cargo.toml

      - name: Preserve rustfmt output for review
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: rustfmt-source
          path: src/free_claude_code/native_tui
          if-no-files-found: error
          retention-days: 1

      - name: Lint native control center
        run: cargo +1.88.0 clippy --manifest-path src/free_claude_code/native_tui/Cargo.toml --all-targets -- -D warnings

      - name: Test native control center
        run: cargo +1.88.0 test --manifest-path src/free_claude_code/native_tui/Cargo.toml --all-targets

      - name: Enforce committed rustfmt output
        run: git diff --exit-code -- src/free_claude_code/native_tui

  pytest:
    name: pytest
    if: ${{ always() }}
    needs: [pytest-suite, rust-tui]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      contents: read
    steps:
      - name: Require Python and Rust suites
        env:
          PYTEST_SUITE_RESULT: ${{ needs.pytest-suite.result }}
          RUST_TUI_RESULT: ${{ needs.rust-tui.result }}
        run: |
          if [ "$PYTEST_SUITE_RESULT" != "success" ] || [ "$RUST_TUI_RESULT" != "success" ]; then
            echo "::error::pytest-suite=$PYTEST_SUITE_RESULT rust-tui=$RUST_TUI_RESULT"
            exit 1
          fi
'''
)


path = Path("scripts/ci.sh")
text = path.read_text()
text = replace_once(
    text,
    'CHECK_ORDER="suppressions ruff-format ruff-check ty pytest"',
    'CHECK_ORDER="suppressions ruff-format ruff-check ty pytest rust-tui"',
    "sh check order",
)
text = replace_once(
    text,
    "Requires uv on PATH when running ruff, ty, or pytest checks.\n",
    "Requires uv on PATH for Python checks and rustup/cargo for rust-tui.\n",
    "sh prerequisites help",
)
text = replace_once(
    text,
    "  pytest         uv run pytest -q --tb=short\n",
    "  pytest         uv run pytest -q --tb=short\n"
    "  rust-tui       pinned rustfmt, clippy, tests, and committed-format check\n",
    "sh rust help",
)
text = replace_once(
    text,
    "        suppressions | ruff-format | ruff-check | ty | pytest) return 0 ;;",
    "        suppressions | ruff-format | ruff-check | ty | pytest | rust-tui) return 0 ;;",
    "sh valid ids",
)
old = '''selected_checks_need_uv() {
    if [ "$dry_run" -ne 0 ]; then
        return 1
    fi

    for check_id in $CHECK_ORDER; do
        if should_run_check "$check_id" && [ "$check_id" != "suppressions" ]; then
            return 0
        fi
    done

    return 1
}
'''
new = '''selected_checks_need_uv() {
    if [ "$dry_run" -ne 0 ]; then
        return 1
    fi

    for check_id in ruff-format ruff-check ty pytest; do
        if should_run_check "$check_id"; then
            return 0
        fi
    done

    return 1
}

assert_rust_available() {
    command -v rustup >/dev/null 2>&1 || fail "rustup is required for rust-tui."
    command -v cargo >/dev/null 2>&1 || fail "cargo is required for rust-tui."
    command -v git >/dev/null 2>&1 || fail "git is required for rust-tui."
}

selected_checks_need_rust() {
    [ "$dry_run" -eq 0 ] && should_run_check rust-tui
}
'''
text = replace_once(text, old, new, "sh prerequisite selection")
insert = '''run_rust_tui() {
    step "rust-tui"
    manifest=src/free_claude_code/native_tui/Cargo.toml
    run rustup toolchain install 1.88.0 --profile minimal --component rustfmt,clippy
    run cargo +1.88.0 fmt --manifest-path "$manifest"
    run cargo +1.88.0 clippy --manifest-path "$manifest" --all-targets -- -D warnings
    run cargo +1.88.0 test --manifest-path "$manifest" --all-targets
    run git diff --exit-code -- src/free_claude_code/native_tui
}

'''
text = replace_once(text, "run_check() {\n", insert + "run_check() {\n", "sh rust runner")
text = replace_once(
    text,
    "        pytest) run_pytest ;;\n",
    "        pytest) run_pytest ;;\n        rust-tui) run_rust_tui ;;\n",
    "sh rust dispatch",
)
text = replace_once(
    text,
    "if selected_checks_need_uv; then\n    assert_uv_available\nfi\n",
    "if selected_checks_need_uv; then\n    assert_uv_available\nfi\n"
    "if selected_checks_need_rust; then\n    assert_rust_available\nfi\n",
    "sh prerequisite invocation",
)
path.write_text(text)


path = Path("scripts/ci.ps1")
text = path.read_text()
text = replace_once(
    text,
    '    "ty",\n    "pytest"\n)',
    '    "ty",\n    "pytest",\n    "rust-tui"\n)',
    "ps1 check order",
)
text = replace_once(
    text,
    "Requires uv on PATH when running ruff, ty, or pytest checks.\n",
    "Requires uv on PATH for Python checks and rustup/cargo for rust-tui.\n",
    "ps1 prerequisites help",
)
text = replace_once(
    text,
    "  pytest         uv run pytest -q --tb=short\n",
    "  pytest         uv run pytest -q --tb=short\n"
    "  rust-tui       pinned rustfmt, clippy, tests, and committed-format check\n",
    "ps1 rust help",
)
old = '''function Test-SelectedChecksNeedUv {
    if ($DryRun) {
        return $false
    }

    foreach ($checkId in $CheckOrder) {
        if ((Test-ShouldRunCheck $checkId) -and $checkId -ne "suppressions") {
            return $true
        }
    }

    return $false
}
'''
new = '''function Test-SelectedChecksNeedUv {
    if ($DryRun) {
        return $false
    }

    foreach ($checkId in @("ruff-format", "ruff-check", "ty", "pytest")) {
        if (Test-ShouldRunCheck $checkId) {
            return $true
        }
    }

    return $false
}

function Assert-RustAvailable {
    if (-not (Get-Command rustup -ErrorAction SilentlyContinue)) {
        throw "rustup is required for rust-tui."
    }
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        throw "cargo is required for rust-tui."
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is required for rust-tui."
    }
}

function Test-SelectedChecksNeedRust {
    return (-not $DryRun) -and (Test-ShouldRunCheck "rust-tui")
}
'''
text = replace_once(text, old, new, "ps1 prerequisite selection")
insert = '''function Invoke-RustTuiCheck {
    Write-Step "rust-tui"
    $manifest = "src/free_claude_code/native_tui/Cargo.toml"
    Invoke-CiCommand -FilePath "rustup" -Arguments @(
        "toolchain", "install", "1.88.0", "--profile", "minimal", "--component", "rustfmt,clippy"
    )
    Invoke-CiCommand -FilePath "cargo" -Arguments @(
        "+1.88.0", "fmt", "--manifest-path", $manifest
    )
    Invoke-CiCommand -FilePath "cargo" -Arguments @(
        "+1.88.0", "clippy", "--manifest-path", $manifest, "--all-targets", "--", "-D", "warnings"
    )
    Invoke-CiCommand -FilePath "cargo" -Arguments @(
        "+1.88.0", "test", "--manifest-path", $manifest, "--all-targets"
    )
    Invoke-CiCommand -FilePath "git" -Arguments @(
        "diff", "--exit-code", "--", "src/free_claude_code/native_tui"
    )
}

'''
text = replace_once(text, "function Invoke-Check {\n", insert + "function Invoke-Check {\n", "ps1 rust runner")
text = replace_once(
    text,
    '        "pytest" { Invoke-PytestCheck }\n',
    '        "pytest" { Invoke-PytestCheck }\n        "rust-tui" { Invoke-RustTuiCheck }\n',
    "ps1 rust dispatch",
)
text = replace_once(
    text,
    "if (Test-SelectedChecksNeedUv) {\n    Assert-UvAvailable\n}\n",
    "if (Test-SelectedChecksNeedUv) {\n    Assert-UvAvailable\n}\n\n"
    "if (Test-SelectedChecksNeedRust) {\n    Assert-RustAvailable\n}\n",
    "ps1 prerequisite invocation",
)
path.write_text(text)


path = Path("tests/scripts/test_ci_scripts.py")
text = path.read_text()
text = replace_once(
    text,
    '    assert \'CHECK_ORDER="suppressions ruff-format ruff-check ty pytest"\' in text\n',
    '    assert \'CHECK_ORDER="suppressions ruff-format ruff-check ty pytest rust-tui"\' in text\n',
    "test sh check order",
)
text = replace_once(
    text,
    '    assert "uv run pytest -q --tb=short" in text\n',
    '    assert "uv run pytest -q --tb=short" in text\n'
    '    assert "rustup toolchain install 1.88.0" in text\n'
    '    assert "cargo +1.88.0 clippy" in text\n'
    '    assert "cargo +1.88.0 test" in text\n',
    "test sh rust commands",
)
text = replace_once(
    text,
    '    pytest_index = text.index("run_pytest()")\n\n    assert (\n        suppress_index < ruff_format_index < ruff_check_index < ty_index < pytest_index\n    )\n',
    '    pytest_index = text.index("run_pytest()")\n'
    '    rust_index = text.index("run_rust_tui()")\n\n'
    '    assert (\n'
    '        suppress_index\n'
    '        < ruff_format_index\n'
    '        < ruff_check_index\n'
    '        < ty_index\n'
    '        < pytest_index\n'
    '        < rust_index\n'
    '    )\n',
    "test sh order",
)
text = replace_once(
    text,
    '    assert \'"pytest"\' in text\n',
    '    assert \'"pytest"\' in text\n'
    '    assert \'"rust-tui"\' in text\n'
    '    assert \'"toolchain", "install", "1.88.0"\' in text\n'
    '    assert \'"+1.88.0", "clippy"\' in text\n'
    '    assert \'"+1.88.0", "test"\' in text\n',
    "test ps1 rust commands",
)
text = replace_once(
    text,
    '    assert "Invoke-PytestCheck" in text\n',
    '    assert "Invoke-PytestCheck" in text\n    assert "Invoke-RustTuiCheck" in text\n',
    "test ps1 rust function",
)
text = replace_once(
    text,
    '    pytest_index = text.index("function Invoke-PytestCheck")\n\n    assert (\n        suppress_index < ruff_format_index < ruff_check_index < ty_index < pytest_index\n    )',
    '    pytest_index = text.index("function Invoke-PytestCheck")\n'
    '    rust_index = text.index("function Invoke-RustTuiCheck")\n\n'
    '    assert (\n'
    '        suppress_index\n'
    '        < ruff_format_index\n'
    '        < ruff_check_index\n'
    '        < ty_index\n'
    '        < pytest_index\n'
    '        < rust_index\n'
    '    )',
    "test ps1 order",
)
text += '''\n\ndef test_ci_sh_rust_dry_run_does_not_require_uv() -> None:\n    result = subprocess.run(\n        [\n            _shell_interpreter(),\n            str(_repo_root() / "scripts" / "ci.sh"),\n            "--only",\n            "rust-tui",\n            "--dry-run",\n        ],\n        cwd=_repo_root(),\n        env={**os.environ, "PATH": _path_without_uv()},\n        text=True,\n        capture_output=True,\n        check=False,\n    )\n\n    assert result.returncode == 0\n    assert "+ rustup toolchain install 1.88.0" in result.stdout\n    assert "+ cargo +1.88.0 fmt" in result.stdout\n    assert "+ cargo +1.88.0 clippy" in result.stdout\n    assert "+ cargo +1.88.0 test" in result.stdout\n    assert "+ git diff --exit-code -- src/free_claude_code/native_tui" in result.stdout\n    assert "uv is required" not in result.stderr\n\n\ndef test_ci_ps1_rust_dry_run_does_not_require_uv() -> None:\n    result = subprocess.run(\n        [\n            _powershell_interpreter(),\n            "-NoProfile",\n            "-File",\n            str(_repo_root() / "scripts" / "ci.ps1"),\n            "-Only",\n            "rust-tui",\n            "-DryRun",\n        ],\n        cwd=_repo_root(),\n        env={**os.environ, "PATH": _path_without_uv()},\n        text=True,\n        capture_output=True,\n        check=False,\n    )\n\n    assert result.returncode == 0\n    assert "+ rustup toolchain install 1.88.0" in result.stdout\n    assert "+ cargo +1.88.0 fmt" in result.stdout\n    assert "+ cargo +1.88.0 clippy" in result.stdout\n    assert "+ cargo +1.88.0 test" in result.stdout\n    assert "+ git diff --exit-code -- src/free_claude_code/native_tui" in result.stdout\n    assert "uv is required" not in result.stderr\n'''
path.write_text(text)


Path("tests/scripts/test_ci_workflow_enforcement.py").write_text(
    '''from pathlib import Path\n\n\ndef test_protected_pytest_context_gates_python_and_rust() -> None:\n    workflow = (\n        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "tests.yml"\n    ).read_text(encoding="utf-8")\n\n    assert "  pytest-suite:" in workflow\n    assert "    name: pytest-suite" in workflow\n    assert "  rust-tui:" in workflow\n    assert "  pytest:" in workflow\n    assert "    name: pytest" in workflow\n    assert "    if: ${{ always() }}" in workflow\n    assert "    needs: [pytest-suite, rust-tui]" in workflow\n    assert "PYTEST_SUITE_RESULT: ${{ needs.pytest-suite.result }}" in workflow\n    assert "RUST_TUI_RESULT: ${{ needs.rust-tui.result }}" in workflow\n    assert 'if [ "$PYTEST_SUITE_RESULT" != "success" ] || [ "$RUST_TUI_RESULT" != "success" ]; then' in workflow\n\n\ndef test_quality_matrix_no_longer_publishes_an_independent_pytest_context() -> None:\n    workflow = (\n        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "tests.yml"\n    ).read_text(encoding="utf-8")\n\n    quality = workflow.split("  quality:", 1)[1].split("  pytest-suite:", 1)[0]\n    assert "- id: pytest" not in quality\n    assert "- id: ruff-format" in quality\n    assert "- id: ruff-check" in quality\n    assert "- id: ty" in quality\n'''
)
