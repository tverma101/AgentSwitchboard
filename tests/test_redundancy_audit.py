import ast
import hashlib
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "free_claude_code"
TEST_ROOT = REPO_ROOT / "tests"
EXCLUDED_DIR_NAMES = frozenset({"_vendor", "__pycache__"})
DEFINITION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _python_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        for path in root.rglob("*.py"):
            relative = path.relative_to(REPO_ROOT)
            if any(part in EXCLUDED_DIR_NAMES for part in relative.parts):
                continue
            files.append(path)
    return sorted(files)


def _decorator_name(decorator: ast.expr) -> str | None:
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _allows_redefinition(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a duplicate name is part of a standard decorator pattern."""

    decorators = {_decorator_name(decorator) for decorator in node.decorator_list}
    return bool({"overload", "setter", "deleter", "register"} & decorators)


def _scope_label(path: Path, classes: tuple[str, ...]) -> str:
    label = _display_path(path)
    if not classes:
        return label
    return f"{label}:{'.'.join(classes)}"


def _duplicate_definition_issues(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    issues: list[str] = []

    def inspect_scope(body: list[ast.stmt], classes: tuple[str, ...]) -> None:
        seen: dict[str, int] = {}
        for statement in body:
            if not isinstance(statement, DEFINITION_TYPES):
                continue
            if isinstance(statement, FUNCTION_TYPES) and _allows_redefinition(statement):
                pass
            elif statement.name in seen:
                issues.append(
                    f"{_scope_label(path, classes)} redefines {statement.name!r} "
                    f"at lines {seen[statement.name]} and {statement.lineno}"
                )
            else:
                seen[statement.name] = statement.lineno

            if isinstance(statement, ast.ClassDef):
                inspect_scope(statement.body, (*classes, statement.name))

    inspect_scope(tree.body, ())
    return issues


def _test_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    payload = (
        type(node).__name__,
        ast.dump(node.args, include_attributes=False),
        tuple(ast.dump(item, include_attributes=False) for item in node.decorator_list),
        tuple(ast.dump(item, include_attributes=False) for item in node.body),
        ast.dump(node.returns, include_attributes=False) if node.returns else None,
        tuple(
            ast.dump(item, include_attributes=False)
            for item in getattr(node, "type_params", ())
        ),
    )
    return repr(payload)


def _duplicate_test_implementation_issues(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    issues: list[str] = []

    def inspect_scope(body: list[ast.stmt], classes: tuple[str, ...]) -> None:
        seen: dict[str, tuple[str, int]] = {}
        for statement in body:
            if isinstance(statement, FUNCTION_TYPES) and statement.name.startswith("test_"):
                fingerprint = _test_fingerprint(statement)
                previous = seen.get(fingerprint)
                if previous is not None:
                    previous_name, previous_line = previous
                    issues.append(
                        f"{_scope_label(path, classes)} has identical tests "
                        f"{previous_name!r} (line {previous_line}) and "
                        f"{statement.name!r} (line {statement.lineno})"
                    )
                else:
                    seen[fingerprint] = (statement.name, statement.lineno)
            if isinstance(statement, ast.ClassDef):
                inspect_scope(statement.body, (*classes, statement.name))

    inspect_scope(tree.body, ())
    return issues


def _parametrize_duplicate_issues(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTION_TYPES) or not node.name.startswith("test_"):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if _decorator_name(decorator.func) != "parametrize" or len(decorator.args) < 2:
                continue
            if any(keyword.arg == "ids" for keyword in decorator.keywords):
                continue
            values = decorator.args[1]
            if not isinstance(values, (ast.List, ast.Tuple)):
                continue
            seen: dict[str, int] = {}
            for index, case in enumerate(values.elts):
                fingerprint = ast.dump(case, include_attributes=False)
                previous = seen.get(fingerprint)
                if previous is not None:
                    issues.append(
                        f"{_display_path(path)}:{node.lineno} {node.name!r} repeats "
                        f"parametrize case {previous + 1} as case {index + 1}"
                    )
                else:
                    seen[fingerprint] = index
    return issues


def _duplicate_file_issues(paths: list[Path]) -> list[str]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in paths:
        if path.name == "__init__.py":
            continue
        payload = path.read_bytes()
        if not payload.strip():
            continue
        groups[hashlib.sha256(payload).hexdigest()].append(path)

    issues: list[str] = []
    for duplicates in groups.values():
        if len(duplicates) < 2:
            continue
        relative = [_display_path(path) for path in duplicates]
        issues.append(f"exact duplicate Python files: {', '.join(relative)}")
    return sorted(issues)


def _all_repository_issues() -> list[str]:
    source_files = _python_files(SOURCE_ROOT)
    test_files = _python_files(TEST_ROOT)
    issues: list[str] = []
    for path in (*source_files, *test_files):
        issues.extend(_duplicate_definition_issues(path))
    for path in test_files:
        issues.extend(_duplicate_test_implementation_issues(path))
        issues.extend(_parametrize_duplicate_issues(path))
    issues.extend(_duplicate_file_issues([*source_files, *test_files]))
    return sorted(issues)


def test_redundancy_audit_rejects_overwritten_definitions(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def helper():\n"
        "    return 2\n",
        encoding="utf-8",
    )

    assert len(_duplicate_definition_issues(path)) == 1


def test_redundancy_audit_allows_property_and_overload_patterns(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        "from typing import overload\n\n"
        "@overload\n"
        "def parse(value: str) -> str: ...\n\n"
        "@overload\n"
        "def parse(value: int) -> int: ...\n\n"
        "class Item:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n\n"
        "    @value.setter\n"
        "    def value(self, new_value):\n"
        "        pass\n",
        encoding="utf-8",
    )

    assert _duplicate_definition_issues(path) == []


def test_redundancy_audit_rejects_identical_tests(tmp_path: Path) -> None:
    path = tmp_path / "test_sample.py"
    path.write_text(
        "def test_alpha():\n"
        "    assert 1 + 1 == 2\n\n"
        "def test_beta():\n"
        "    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    assert len(_duplicate_test_implementation_issues(path)) == 1


def test_redundancy_audit_rejects_duplicate_parametrize_cases(tmp_path: Path) -> None:
    path = tmp_path / "test_sample.py"
    path.write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', [1, 2, 1])\n"
        "def test_value(value):\n"
        "    assert value > 0\n",
        encoding="utf-8",
    )

    assert len(_parametrize_duplicate_issues(path)) == 1


def test_redundancy_audit_rejects_exact_duplicate_python_files(tmp_path: Path) -> None:
    left = tmp_path / "left.py"
    right = tmp_path / "right.py"
    left.write_text("VALUE = 1\n", encoding="utf-8")
    right.write_text("VALUE = 1\n", encoding="utf-8")

    assert len(_duplicate_file_issues([left, right])) == 1


def test_repository_has_no_high_confidence_python_redundancy() -> None:
    issues = _all_repository_issues()
    assert issues == [], "\n" + "\n".join(issues)
