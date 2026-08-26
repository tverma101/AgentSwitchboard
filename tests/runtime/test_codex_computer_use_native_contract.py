"""Tests for native Computer Use schema/guidance drift evidence."""

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from free_claude_code.runtime.codex_computer_use import (
    COMPUTER_USE_TOOL_SPECS,
    CodexComputerUseError,
    CodexComputerUsePaths,
)
from free_claude_code.runtime.codex_computer_use_managed import PLUGIN_RELATIVE_PATH
from free_claude_code.runtime.codex_computer_use_native_contract import (
    MAX_NATIVE_GUIDANCE_BYTES,
    SKILL_RELATIVE_PATH,
    native_contract_from_status,
    read_native_computer_use_skill,
)


def _paths(tmp_path: Path) -> CodexComputerUsePaths:
    resources = tmp_path / "ChatGPT.app" / "Contents" / "Resources"
    codex = resources / "codex"
    codex.parent.mkdir(parents=True)
    codex.write_text("", encoding="utf-8")
    app = tmp_path / "Codex Computer Use.app"
    client = app / "Contents" / "MacOS" / "client"
    client.parent.mkdir(parents=True)
    client.write_text("", encoding="utf-8")
    return CodexComputerUsePaths(codex=codex, app=app, client=client)


def _native_status() -> list[Mapping[str, Any]]:
    tools: dict[str, Any] = {}
    for spec in COMPUTER_USE_TOOL_SPECS:
        tools[str(spec["name"])] = {
            "description": spec["description"],
            "inputSchema": deepcopy(spec["input_schema"]),
        }
    return [{"name": "computer-use", "tools": tools, "authStatus": "notRequired"}]


def test_native_contract_matches_fixed_luna_tool_fields() -> None:
    contract = native_contract_from_status(_native_status())

    assert contract.compatible is True
    assert contract.schema_mismatches == ()
    assert len(contract.schema_sha256) == 64
    assert contract.receipt()["compatible"] is True


def test_native_contract_surfaces_schema_drift_instead_of_silent_mutation() -> None:
    rows = _native_status()
    server = rows[0]
    tools = server["tools"]
    assert isinstance(tools, dict)
    click = tools["click"]
    assert isinstance(click, dict)
    schema = click["inputSchema"]
    assert isinstance(schema, dict)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    properties["new_native_field"] = {"type": "string"}

    contract = native_contract_from_status(rows)

    assert contract.compatible is False
    assert any("click:schema" in item for item in contract.schema_mismatches)


def test_native_skill_is_loaded_from_bundled_plugin_and_hashed(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    skill = paths.codex.parent / PLUGIN_RELATIVE_PATH / SKILL_RELATIVE_PATH
    skill.parent.mkdir(parents=True)
    skill.write_text("# Computer Use\nUse native tools carefully.\n", encoding="utf-8")

    snapshot = read_native_computer_use_skill(paths)

    assert snapshot.text.startswith("# Computer Use")
    assert snapshot.size_bytes == len(snapshot.text.encode("utf-8"))
    assert len(snapshot.sha256) == 64


def test_native_skill_missing_or_oversized_fails_closed(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    plugin_root = paths.codex.parent / PLUGIN_RELATIVE_PATH
    plugin_root.mkdir(parents=True)

    with pytest.raises(CodexComputerUseError, match=r"SKILL\.md was not found"):
        read_native_computer_use_skill(paths)

    skill = plugin_root / SKILL_RELATIVE_PATH
    skill.parent.mkdir(parents=True)
    skill.write_bytes(b"x" * (MAX_NATIVE_GUIDANCE_BYTES + 1))

    with pytest.raises(CodexComputerUseError, match="exceeds safety bound"):
        read_native_computer_use_skill(paths)
