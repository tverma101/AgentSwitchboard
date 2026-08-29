import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _script_text(name: str) -> str:
    return (_repo_root() / "scripts" / name).read_text(encoding="utf-8")


def _braced_body(text: str, declaration: str) -> str:
    start = text.index(declaration)
    brace_start = text.index("{", start)
    depth = 0

    for index, char in enumerate(text[brace_start:], start=brace_start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start + 1 : index]

    raise AssertionError(f"Unclosed function body for {declaration}")


def _path_without_uv() -> str:
    uv_names = ("uv", "uv.exe", "uv.cmd", "uv.bat")
    entries = []
    for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_entry:
            continue
        entry = Path(raw_entry)
        if any((entry / name).exists() for name in uv_names):
            continue
        entries.append(raw_entry)
    return os.pathsep.join(entries)


def _shell_interpreter() -> str:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("sh is not available on this platform")
    return sh


def _powershell_interpreter() -> str:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("PowerShell is not available on this platform")
    return pwsh


def _local_pytest_policy() -> str:
    if shutil.which("taskpolicy"):
        return "nice -n 5 taskpolicy -c utility"
    if shutil.which("nice"):
        return "nice -n 5"
    return "uv"


def test_ci_sh_runs_ci_checks_in_order() -> None:
    text = _script_text("ci.sh")
    legacy_future_import = "from __future__ import " + "annotations"

    assert 'CHECK_ORDER="suppressions ruff-format ruff-check ty pytest"' in text
    assert "grep -rE" in text
    assert "Fix the underlying type/import issue instead" in text
    assert legacy_future_import in text
    assert "legacy future annotations are not allowed" in text
    assert "--exclude-dir=.venv" in text
    assert "--exclude-dir=.git" in text
    assert "uv run ruff format" in text
    assert "uv run ruff format --check" not in text
    assert "uv run ruff check --fix" in text
    assert "uv run ty check" in text
    assert "uv run pytest -q --tb=short" in text
    assert "run_local_pytest" in text
    assert "--only" in text
    assert "--skip" in text
    assert "--fast" in text
    assert "--integration" in text
    assert "--installers" in text
    assert "--full" in text
    assert "--dry-run" in text
    assert "uv is required but was not found on PATH" in text
    assert "npm" not in text
    assert "smoke/" not in text
    assert "uv self update" not in text


def test_ci_sh_dry_run_does_not_require_uv() -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            "pytest",
            "--dry-run",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert _local_pytest_policy() in result.stdout
    assert "uv run pytest -q --tb=short -n 0" in result.stdout
    assert (
        '-m "not integration and not live and not interactive and not installer"'
        in result.stdout
    )
    assert "integration or live or interactive" not in result.stdout
    assert "uv is required" not in result.stderr


def test_ci_sh_fast_pytest_excludes_slow_or_external_items() -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            "pytest",
            "--fast",
            "--dry-run",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert _local_pytest_policy() in result.stdout
    assert "uv run pytest -q --tb=short -n 0" in result.stdout
    assert (
        "not integration and not live and not interactive and not installer"
        in result.stdout
    )
    assert "uv is required" not in result.stderr


def test_ci_sh_integration_tier_is_explicit() -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            "pytest",
            "--integration",
            "--dry-run",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.count("uv run pytest -q --tb=short -n 0") == 2
    assert ' -m "integration or live or interactive"' in result.stdout
    assert "uv is required" not in result.stderr


def test_ci_sh_rejects_full_with_a_partial_pytest_tier() -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            "pytest",
            "--full",
            "--fast",
            "--dry-run",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--full cannot be combined" in result.stderr


def test_ci_sh_full_is_serial_and_runs_each_explicit_tier() -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            "pytest",
            "--full",
            "--dry-run",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    pytest_commands = [
        line for line in result.stdout.splitlines() if "uv run pytest" in line
    ]
    assert len(pytest_commands) == 3
    assert all("-n 0" in line for line in pytest_commands)
    assert all("-n auto" not in line for line in pytest_commands)
    assert (
        "not integration and not live and not interactive and not installer"
        in (pytest_commands[0])
    )
    assert '"integration or live or interactive"' in pytest_commands[1]
    assert "--run-installer-tests -m installer" in pytest_commands[2]


def test_pytest_defaults_to_serial_execution() -> None:
    text = (_repo_root() / "pyproject.toml").read_text(encoding="utf-8")

    assert 'addopts = "-n 0"' in text
    assert "-n auto" not in text


def test_ci_sh_installer_tier_is_explicit_and_serial() -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            "pytest",
            "--installers",
            "--dry-run",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert _local_pytest_policy() in result.stdout
    assert (
        "uv run pytest -q --tb=short -n 0 --run-installer-tests -m installer"
        in result.stdout
    )
    assert "integration or live or interactive" not in result.stdout


def test_ci_sh_rejects_fast_installer_combination() -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            "pytest",
            "--fast",
            "--installers",
            "--dry-run",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--fast and --installers cannot be combined" in result.stderr


@pytest.mark.parametrize(
    ("check_id", "command"),
    [
        ("ruff-format", "+ uv run ruff format"),
        ("ruff-check", "+ uv run ruff check --fix"),
    ],
)
def test_ci_sh_dry_run_prints_local_ruff_repair_commands(
    check_id: str, command: str
) -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            check_id,
            "--dry-run",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert command in result.stdout
    assert "uv is required" not in result.stderr


def test_ci_sh_suppression_only_does_not_require_uv() -> None:
    result = subprocess.run(
        [
            _shell_interpreter(),
            str(_repo_root() / "scripts" / "ci.sh"),
            "--only",
            "suppressions",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Ban suppressions and legacy annotations" in result.stdout
    assert "uv is required" not in result.stderr


def test_ci_sh_is_tracked_executable() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "scripts/ci.sh"],
        cwd=_repo_root(),
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.startswith("100755 ")


def test_ci_sh_fail_fast_runs_checks_sequentially() -> None:
    text = _script_text("ci.sh")
    main = text[text.index('parse_args "$@"') :]

    suppress_index = text.index("run_suppressions()")
    ruff_format_index = text.index("run_ruff_format()")
    ruff_check_index = text.index("run_ruff_check()")
    ty_index = text.index("run_ty()")
    pytest_index = text.index("run_pytest()")

    assert (
        suppress_index < ruff_format_index < ruff_check_index < ty_index < pytest_index
    )
    assert "for check_id in $CHECK_ORDER" in main


def test_ci_ps1_runs_ci_checks_in_order() -> None:
    text = _script_text("ci.ps1")
    legacy_future_import = "from __future__ import " + "annotations"

    assert '"suppressions"' in text
    assert '"ruff-format"' in text
    assert '"ruff-check"' in text
    assert '"ty"' in text
    assert '"pytest"' in text
    assert "Select-String -Pattern" in text
    assert "Fix the underlying type/import issue instead" in text
    assert legacy_future_import in text
    assert "legacy future annotations are not allowed" in text
    assert ".venv" in text
    assert ".git" in text
    assert '"run", "ruff", "format"' in text
    assert '"format", "--check"' not in text
    assert '"run", "ruff", "check", "--fix"' in text
    assert '"-q", "--tb=short"' in text
    assert '"-n", "0"' in text
    assert '"integration or live or interactive"' in text
    assert "-Only" in text
    assert "-Skip" in text
    assert "-Fast" in text
    assert "-Integration" in text
    assert "-Installers" in text
    assert "-Full" in text
    assert "-DryRun" in text
    assert "uv is required but was not found on PATH" in text
    assert "npm" not in text
    assert "smoke/" not in text
    assert "uv self update" not in text


def test_ci_ps1_dry_run_does_not_require_uv() -> None:
    result = subprocess.run(
        [
            _powershell_interpreter(),
            "-NoProfile",
            "-File",
            str(_repo_root() / "scripts" / "ci.ps1"),
            "-Only",
            "pytest",
            "-DryRun",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "uv run pytest -q --tb=short" in result.stdout
    assert "uv is required" not in result.stderr


@pytest.mark.parametrize(
    ("check_id", "command"),
    [
        ("ruff-format", "+ uv run ruff format"),
        ("ruff-check", "+ uv run ruff check --fix"),
    ],
)
def test_ci_ps1_dry_run_prints_local_ruff_repair_commands(
    check_id: str, command: str
) -> None:
    result = subprocess.run(
        [
            _powershell_interpreter(),
            "-NoProfile",
            "-File",
            str(_repo_root() / "scripts" / "ci.ps1"),
            "-Only",
            check_id,
            "-DryRun",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert command in result.stdout
    assert "uv is required" not in result.stderr


def test_ci_ps1_suppression_only_does_not_require_uv() -> None:
    result = subprocess.run(
        [
            _powershell_interpreter(),
            "-NoProfile",
            "-File",
            str(_repo_root() / "scripts" / "ci.ps1"),
            "-Only",
            "suppressions",
        ],
        cwd=_repo_root(),
        env={**os.environ, "PATH": _path_without_uv()},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Ban suppressions and legacy annotations" in result.stdout
    assert "uv is required" not in result.stderr


def test_ci_ps1_fail_fast_runs_checks_sequentially() -> None:
    text = _script_text("ci.ps1")

    assert "foreach ($checkId in $CheckOrder)" in text
    assert "Invoke-SuppressionsCheck" in text
    assert "Invoke-RuffFormatCheck" in text
    assert "Invoke-RuffLintCheck" in text
    assert "Invoke-TyCheck" in text
    assert "Invoke-PytestCheck" in text

    suppress_index = text.index("function Invoke-SuppressionsCheck")
    ruff_format_index = text.index("function Invoke-RuffFormatCheck")
    ruff_check_index = text.index("function Invoke-RuffLintCheck")
    ty_index = text.index("function Invoke-TyCheck")
    pytest_index = text.index("function Invoke-PytestCheck")

    assert (
        suppress_index < ruff_format_index < ruff_check_index < ty_index < pytest_index
    )
