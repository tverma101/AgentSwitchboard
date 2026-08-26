"""Bounded execution seam for explicitly approved capability helpers."""

import json
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityHelper,
    CapabilityRoutePlan,
)
from free_claude_code.core.provider_policy import ProviderEgressGuard

DEFAULT_HELPER_TIMEOUT_SECONDS = 60.0
DEFAULT_CANCELLATION_GRACE_SECONDS = 0.25
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024

HelperCallable = Callable[
    [str, Mapping[str, Any], threading.Event],
    Mapping[str, Any],
]


class HelperExecutionStatus(StrEnum):
    """Terminal state for one bounded helper attempt."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INDETERMINATE = "indeterminate"
    OUTPUT_REJECTED = "output_rejected"


@dataclass(frozen=True, slots=True)
class HelperExecutionReceipt:
    """Metadata-only helper receipt; never stores arguments or output content."""

    helper_id: str
    provider_family: str
    operation: str
    status: HelperExecutionStatus
    duration_ms: int
    attempts: int
    local: bool
    billable: bool
    failure_owner: str | None = None
    output_bytes: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "helper_id": self.helper_id,
            "provider_family": self.provider_family,
            "operation": self.operation,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "local": self.local,
            "billable": self.billable,
            "failure_owner": self.failure_owner,
            "output_bytes": self.output_bytes,
        }


@dataclass(frozen=True, slots=True)
class HelperExecutionResult:
    """Bounded structured output plus a metadata-only execution receipt."""

    output: dict[str, Any]
    receipt: HelperExecutionReceipt


@dataclass(frozen=True, slots=True)
class ApprovedHelper:
    """One repo/user-authored helper implementation registered before a session."""

    helper_id: str
    provider_family: str
    capabilities: frozenset[Capability]
    execute: HelperCallable
    local: bool = True
    billable: bool = False
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    mutating_operations: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.helper_id.strip():
            raise ValueError("helper_id is required")
        if not self.provider_family.strip():
            raise ValueError("provider_family is required")
        if not self.capabilities:
            raise ValueError("helper must declare at least one capability")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        if self.local and self.billable:
            raise ValueError("a local helper cannot be marked billable")
        if any(not operation.strip() for operation in self.mutating_operations):
            raise ValueError("mutating operation names cannot be empty")

    def router_metadata(self) -> CapabilityHelper:
        """Return the existing #30 router metadata for this implementation."""

        return CapabilityHelper(
            helper_id=self.helper_id,
            provider_family=self.provider_family,
            model_ref="local-tool" if self.local else "helper",
            capabilities=self.capabilities,
            local=self.local,
            billable=self.billable,
        )

    def operation_may_have_side_effects(self, operation: str) -> bool:
        """Return whether transport loss makes this operation indeterminate."""

        return operation in self.mutating_operations


class HelperExecutionError(RuntimeError):
    """Base failure carrying a content-free execution receipt."""

    def __init__(self, message: str, receipt: HelperExecutionReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


class HelperTimeoutError(HelperExecutionError):
    """A read-only helper honored cancellation after the controller timeout."""


class HelperIndeterminateError(HelperExecutionError):
    """A helper may have committed a side effect or did not prove cancellation."""


class HelperOutputError(HelperExecutionError):
    """The helper returned non-JSON or oversized controller-facing output."""


class ApprovedHelperRegistry:
    """Explicit startup registry; no filesystem/network discovery is performed."""

    def __init__(self) -> None:
        self._helpers: dict[str, ApprovedHelper] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, helper: ApprovedHelper) -> None:
        if self._frozen:
            raise RuntimeError("approved helper registry is frozen")
        if helper.helper_id in self._helpers:
            raise ValueError(f"helper is already registered: {helper.helper_id}")
        self._helpers[helper.helper_id] = helper

    def freeze(self) -> None:
        self._frozen = True

    def resolve(self, helper_id: str) -> ApprovedHelper:
        try:
            return self._helpers[helper_id]
        except KeyError as error:
            raise KeyError(f"approved helper is not registered: {helper_id}") from error

    def router_helpers(self) -> tuple[CapabilityHelper, ...]:
        """Return deterministic metadata for the existing capability router."""

        return tuple(
            self._helpers[helper_id].router_metadata()
            for helper_id in sorted(self._helpers)
        )

    def receipt(self) -> tuple[dict[str, object], ...]:
        """Return deterministic, content-free registry metadata."""

        rows: list[dict[str, object]] = []
        for helper_id in sorted(self._helpers):
            helper = self._helpers[helper_id]
            rows.append(
                {
                    "helper_id": helper.helper_id,
                    "provider_family": helper.provider_family,
                    "capabilities": sorted(
                        capability.value for capability in helper.capabilities
                    ),
                    "local": helper.local,
                    "billable": helper.billable,
                    "max_output_bytes": helper.max_output_bytes,
                    "mutating_operations": sorted(helper.mutating_operations),
                }
            )
        return tuple(rows)


class ApprovedHelperExecutor:
    """Execute one selected helper without replacing the primary controller."""

    def __init__(
        self,
        registry: ApprovedHelperRegistry,
        guard: ProviderEgressGuard,
        *,
        default_timeout_seconds: float = DEFAULT_HELPER_TIMEOUT_SECONDS,
        cancellation_grace_seconds: float = DEFAULT_CANCELLATION_GRACE_SECONDS,
    ) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        if cancellation_grace_seconds < 0:
            raise ValueError("cancellation_grace_seconds cannot be negative")
        self._registry = registry
        self._guard = guard
        self._default_timeout_seconds = default_timeout_seconds
        self._cancellation_grace_seconds = cancellation_grace_seconds

    def execute_planned(
        self,
        plan: CapabilityRoutePlan,
        *,
        helper_id: str,
        operation: str,
        arguments: Mapping[str, Any],
        timeout_seconds: float | None = None,
    ) -> HelperExecutionResult:
        """Execute only a helper already selected by the #30 route plan."""

        selected_ids = {helper.helper_id for helper in plan.helpers}
        if plan.decision != "helpers" or helper_id not in selected_ids:
            raise PermissionError(
                f"helper was not selected by the capability route: {helper_id}"
            )
        return self.execute(
            helper_id=helper_id,
            operation=operation,
            arguments=arguments,
            timeout_seconds=timeout_seconds,
        )

    def execute(
        self,
        *,
        helper_id: str,
        operation: str,
        arguments: Mapping[str, Any],
        timeout_seconds: float | None = None,
    ) -> HelperExecutionResult:
        """Run one attempt with pre-egress policy, timeout, cancellation and bounds."""

        helper = self._registry.resolve(helper_id)
        category = "local_tool" if helper.local else "helper"
        self._guard.authorize(helper.provider_family, category=category)

        timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")

        started = time.monotonic()
        cancel_event = threading.Event()
        finished: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                output = helper.execute(operation, arguments, cancel_event)
            except Exception as error:
                finished.put((False, error))
                return
            finished.put((True, output))

        worker = threading.Thread(
            target=run,
            name=f"fcc-helper-{helper.helper_id}",
            daemon=True,
        )
        worker.start()

        try:
            succeeded, payload = finished.get(timeout=timeout)
        except queue.Empty:
            cancel_event.set()
            worker.join(timeout=self._cancellation_grace_seconds)
            duration_ms = _duration_ms(started)
            side_effecting = helper.operation_may_have_side_effects(operation)
            if side_effecting or worker.is_alive():
                reason = (
                    "helper operation may have committed before timeout"
                    if side_effecting
                    else "helper did not prove cancellation after timeout"
                )
                receipt = _receipt(
                    helper,
                    operation,
                    HelperExecutionStatus.INDETERMINATE,
                    duration_ms,
                    failure_owner=helper.helper_id,
                )
                raise HelperIndeterminateError(
                    f"{reason}: {helper.helper_id}",
                    receipt,
                )
            receipt = _receipt(
                helper,
                operation,
                HelperExecutionStatus.TIMED_OUT,
                duration_ms,
                failure_owner=helper.helper_id,
            )
            raise HelperTimeoutError(
                f"read-only helper timed out and cancelled: {helper.helper_id}",
                receipt,
            )

        duration_ms = _duration_ms(started)
        if not succeeded:
            receipt = _receipt(
                helper,
                operation,
                HelperExecutionStatus.FAILED,
                duration_ms,
                failure_owner=helper.helper_id,
            )
            cause = payload if isinstance(payload, BaseException) else None
            raise HelperExecutionError(
                f"helper execution failed: {helper.helper_id}",
                receipt,
            ) from cause

        if not isinstance(payload, Mapping):
            receipt = _receipt(
                helper,
                operation,
                HelperExecutionStatus.OUTPUT_REJECTED,
                duration_ms,
                failure_owner=helper.helper_id,
            )
            raise HelperOutputError(
                f"helper returned non-mapping output: {helper.helper_id}",
                receipt,
            )

        output = dict(payload)
        try:
            output_bytes = _json_output_size(output)
        except ValueError as error:
            receipt = _receipt(
                helper,
                operation,
                HelperExecutionStatus.OUTPUT_REJECTED,
                duration_ms,
                failure_owner=helper.helper_id,
            )
            raise HelperOutputError(
                f"helper returned non-JSON output: {helper.helper_id}",
                receipt,
            ) from error
        if output_bytes > helper.max_output_bytes:
            receipt = _receipt(
                helper,
                operation,
                HelperExecutionStatus.OUTPUT_REJECTED,
                duration_ms,
                failure_owner=helper.helper_id,
                output_bytes=output_bytes,
            )
            raise HelperOutputError(
                f"helper output exceeded bound: {helper.helper_id}",
                receipt,
            )

        return HelperExecutionResult(
            output=output,
            receipt=_receipt(
                helper,
                operation,
                HelperExecutionStatus.SUCCESS,
                duration_ms,
                output_bytes=output_bytes,
            ),
        )


def _json_output_size(output: Mapping[str, Any]) -> int:
    try:
        encoded = json.dumps(
            dict(output),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("helper output must be JSON-serializable") from error
    return len(encoded)


def _duration_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _receipt(
    helper: ApprovedHelper,
    operation: str,
    status: HelperExecutionStatus,
    duration_ms: int,
    *,
    failure_owner: str | None = None,
    output_bytes: int | None = None,
) -> HelperExecutionReceipt:
    return HelperExecutionReceipt(
        helper_id=helper.helper_id,
        provider_family=helper.provider_family,
        operation=operation,
        status=status,
        duration_ms=duration_ms,
        attempts=1,
        local=helper.local,
        billable=helper.billable,
        failure_owner=failure_owner,
        output_bytes=output_bytes,
    )


__all__ = [
    "ApprovedHelper",
    "ApprovedHelperExecutor",
    "ApprovedHelperRegistry",
    "HelperExecutionError",
    "HelperExecutionReceipt",
    "HelperExecutionResult",
    "HelperExecutionStatus",
    "HelperIndeterminateError",
    "HelperOutputError",
    "HelperTimeoutError",
]
