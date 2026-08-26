"""Native Codex Computer Use schema/guidance evidence for Luna parity."""

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from free_claude_code.runtime.codex_computer_use import (
    COMPUTER_USE_METHODS,
    COMPUTER_USE_TOOL_SPECS,
    CodexComputerUseError,
    CodexComputerUsePaths,
)
from free_claude_code.runtime.codex_computer_use_managed import (
    MAX_STATUS_PAGES,
    SERVER_NAME,
    ManagedCodexComputerUseBroker,
    managed_plugin_root,
)

SKILL_RELATIVE_PATH = Path("skills/computer-use/SKILL.md")
MAX_NATIVE_GUIDANCE_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class NativeComputerUseSkill:
    """Installed official Computer Use skill text captured at session start."""

    text: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class NativeComputerUseContract:
    """Observed native tool inventory/schema fingerprint from app-server."""

    tool_names: tuple[str, ...]
    schema_sha256: str
    schema_mismatches: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return not self.schema_mismatches

    def receipt(self) -> dict[str, object]:
        return {
            "tool_names": list(self.tool_names),
            "schema_sha256": self.schema_sha256,
            "schema_mismatches": list(self.schema_mismatches),
            "compatible": self.compatible,
        }


def read_native_computer_use_skill(
    paths: CodexComputerUsePaths,
) -> NativeComputerUseSkill:
    """Read the official bundled skill without copying it into Harness."""

    plugin_root = managed_plugin_root(paths)
    if plugin_root is None:
        raise CodexComputerUseError(
            "bundled Computer Use plugin is unavailable; native skill cannot be loaded"
        )
    skill_path = (plugin_root / SKILL_RELATIVE_PATH).resolve()
    try:
        skill_path.relative_to(plugin_root)
    except ValueError as error:
        raise CodexComputerUseError(
            "Computer Use skill escaped the bundled plugin root"
        ) from error
    if not skill_path.is_file():
        raise CodexComputerUseError("bundled Computer Use SKILL.md was not found")
    raw = skill_path.read_bytes()
    if not raw:
        raise CodexComputerUseError("bundled Computer Use SKILL.md is empty")
    if len(raw) > MAX_NATIVE_GUIDANCE_BYTES:
        raise CodexComputerUseError("bundled Computer Use SKILL.md exceeds safety bound")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CodexComputerUseError(
            "bundled Computer Use SKILL.md is not valid UTF-8"
        ) from error
    return NativeComputerUseSkill(
        text=text,
        sha256=sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )


def native_contract_from_status(
    rows: list[Mapping[str, Any]],
) -> NativeComputerUseContract:
    """Fingerprint native app-server schemas and compare fixed Luna field names."""

    server = next((row for row in rows if row.get("name") == SERVER_NAME), None)
    if server is None:
        raise CodexComputerUseError("native Computer Use server is absent from status")
    tools = server.get("tools")
    if not isinstance(tools, Mapping):
        raise CodexComputerUseError("native Computer Use status has no tool schema map")

    normalized: dict[str, dict[str, object]] = {}
    mismatches: list[str] = []
    luna_specs = {str(spec["name"]): spec for spec in COMPUTER_USE_TOOL_SPECS}
    for method in COMPUTER_USE_METHODS:
        native_tool = tools.get(method)
        if not isinstance(native_tool, Mapping):
            mismatches.append(f"{method}:missing-native-tool")
            continue
        native_schema = native_tool.get("inputSchema")
        if not isinstance(native_schema, Mapping):
            native_schema = native_tool.get("input_schema")
        if not isinstance(native_schema, Mapping):
            mismatches.append(f"{method}:missing-input-schema")
            native_schema = {}

        description = native_tool.get("description")
        normalized[method] = {
            "description": description if isinstance(description, str) else "",
            "input_schema": native_schema,
        }

        native_properties = native_schema.get("properties")
        native_property_names = (
            frozenset(str(name) for name in native_properties)
            if isinstance(native_properties, Mapping)
            else frozenset()
        )
        luna_schema = luna_specs[method].get("input_schema")
        luna_properties = (
            luna_schema.get("properties") if isinstance(luna_schema, Mapping) else None
        )
        luna_property_names = (
            frozenset(str(name) for name in luna_properties)
            if isinstance(luna_properties, Mapping)
            else frozenset()
        )
        if native_property_names != luna_property_names:
            mismatches.append(
                f"{method}:properties native={sorted(native_property_names)!r} "
                f"luna={sorted(luna_property_names)!r}"
            )

    extra_tools = sorted(str(name) for name in tools if name not in COMPUTER_USE_METHODS)
    if extra_tools:
        mismatches.append(f"unexpected-native-tools:{extra_tools!r}")

    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return NativeComputerUseContract(
        tool_names=tuple(sorted(str(name) for name in tools)),
        schema_sha256=sha256(encoded).hexdigest(),
        schema_mismatches=tuple(mismatches),
    )


class ContractCheckedManagedCodexComputerUseBroker(ManagedCodexComputerUseBroker):
    """Managed broker that snapshots official skill + schemas before first action."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._native_contract: NativeComputerUseContract | None = None
        self._native_skill: NativeComputerUseSkill | None = None

    @property
    def native_contract(self) -> NativeComputerUseContract:
        contract = self._native_contract
        if contract is None:
            raise CodexComputerUseError("native Computer Use contract is not loaded")
        return contract

    @property
    def native_skill(self) -> NativeComputerUseSkill:
        skill = self._native_skill
        if skill is None:
            raise CodexComputerUseError("native Computer Use skill is not loaded")
        return skill

    def start(self) -> None:
        if self.started and self._native_contract is not None and self._native_skill is not None:
            return
        super().start()
        if self._thread_id is None:
            self.close()
            raise CodexComputerUseError("native Computer Use thread is unavailable")
        try:
            deadline = time.monotonic() + min(self.readiness_timeout_seconds, 15.0)
            rows = self._list_mcp_status(deadline)
            contract = native_contract_from_status(rows)
            skill = read_native_computer_use_skill(self.paths)
            if not contract.compatible:
                raise CodexComputerUseError(
                    "native Computer Use schema drift detected: "
                    + "; ".join(contract.schema_mismatches)
                )
            self._native_contract = contract
            self._native_skill = skill
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self._native_contract = None
        self._native_skill = None
        super().close()

    def parity_receipt(self) -> dict[str, object]:
        """Return content-free native evidence suitable for diagnostics/certification."""

        return {
            "native_contract": self.native_contract.receipt(),
            "native_skill_sha256": self.native_skill.sha256,
            "native_skill_size_bytes": self.native_skill.size_bytes,
        }


__all__ = [
    "ContractCheckedManagedCodexComputerUseBroker",
    "MAX_NATIVE_GUIDANCE_BYTES",
    "NativeComputerUseContract",
    "NativeComputerUseSkill",
    "SKILL_RELATIVE_PATH",
    "native_contract_from_status",
    "read_native_computer_use_skill",
]
