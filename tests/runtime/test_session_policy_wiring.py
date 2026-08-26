"""Acceptance tests for launch-time session policy composition."""

import threading
from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

import pytest

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityRouter,
    CapabilityRoutingMode,
    RequiredCapabilitySet,
)
from free_claude_code.application.helpers import ApprovedHelper, ApprovedHelperRegistry
from free_claude_code.application.model_metadata import ProviderModelInfo
from free_claude_code.application.session_policy import (
    build_session_execution_policy_for_settings,
)
from free_claude_code.cli.managed.manager import ManagedClaudeSessionManager
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import Message, MessagesRequest
from free_claude_code.core.provider_policy import (
    ProviderPolicyError,
    ProviderPolicyMode,
)
from free_claude_code.core.reasoning import DEFAULT_REASONING_POLICY, ReasoningPolicy
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import BaseProvider, ProviderConfig
from free_claude_code.runtime.application import ApplicationRuntime
from free_claude_code.runtime.bootstrap import _build_provider_runtime
from free_claude_code.runtime.provider_manager import ProviderRuntimeManager


class _ProbeProvider(BaseProvider):
    """Provider test double whose only possible upstream action is guarded."""

    def preflight_stream(
        self,
        request: MessagesRequest,
        *,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> None:
        del request, reasoning

    async def cleanup(self) -> None:
        return None

    async def list_model_infos(self) -> frozenset[ProviderModelInfo]:
        return frozenset()

    def stream_response(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> AsyncIterator[str]:
        del request, input_tokens, request_id, response_model, reasoning

        async def empty() -> AsyncIterator[str]:
            if False:
                yield ""

        return empty()


class _EgressProbeProvider(_ProbeProvider):
    """Fake transport that records only calls that pass the session guard."""

    def __init__(self, config: ProviderConfig, network_calls: list[str]) -> None:
        super().__init__(config)
        self._network_calls = network_calls

    def stream_response(
        self,
        request: MessagesRequest,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        response_model: str | None = None,
        reasoning: ReasoningPolicy = DEFAULT_REASONING_POLICY,
    ) -> AsyncIterator[str]:
        self._authorize_egress("https://api.openai.com/v1/responses")
        self._network_calls.append("openai")
        return super().stream_response(
            request,
            input_tokens,
            request_id=request_id,
            response_model=response_model,
            reasoning=reasoning,
        )


def _registry() -> ApprovedHelperRegistry:
    def execute(
        operation: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event,
    ) -> dict[str, object]:
        return {
            "operation": operation,
            "argument_count": len(arguments),
            "cancelled": cancel_event.is_set(),
        }

    registry = ApprovedHelperRegistry()
    registry.register(
        ApprovedHelper(
            helper_id="codex-computer-use",
            provider_family="computer",
            capabilities=frozenset({Capability.PIXEL_COMPUTER_USE}),
            execute=execute,
        )
    )
    registry.freeze()
    return registry


def _settings() -> Settings:
    return Settings().model_copy(
        update={
            "model": "opencode_go/muse-spark-1.2-contributor",
            "opencode_api_key": "controller-credential",
            "allowed_helper_ids": "codex-computer-use",
            "provider_policy_mode": ProviderPolicyMode.STRICT.value,
            "capability_routing_mode": CapabilityRoutingMode.SMART_LOCAL.value,
            "paid_fallback": False,
            "anthropic_auth_token": "unrelated-credential",
            "azure_openai_api_key": "unrelated-credential",
            "open_router_api_key": "unrelated-credential",
        }
    )


def _openai_probe(
    config: ProviderConfig,
    _settings: Settings,
    _admission: ProviderAdmissionController,
) -> BaseProvider:
    return _ProbeProvider(config)


@pytest.mark.asyncio
async def test_strict_local_helper_has_zero_forbidden_provider_egress() -> None:
    """A local helper works while unrelated provider credentials cannot escape."""

    registry = _registry()
    network_calls: list[str] = []

    def openai_factory(
        config: ProviderConfig,
        _settings: Settings,
        _admission: ProviderAdmissionController,
    ) -> BaseProvider:
        return _EgressProbeProvider(config, network_calls)

    runtime = _build_provider_runtime(
        _settings(),
        openai_factory=openai_factory,
        helper_registry=registry,
    )
    policy = runtime.session_policy
    assert policy is not None

    openai = runtime.resolve_provider("openai")
    assert openai._config.egress_guard is policy.egress_guard
    request = MessagesRequest(
        model="fallback-model",
        messages=[Message(role="user", content="probe")],
    )
    with pytest.raises(ProviderPolicyError, match="blocked before network I/O"):
        openai.stream_response(request)
    assert network_calls == []

    route = CapabilityRouter(policy.routing_policy).plan(
        RequiredCapabilitySet(frozenset({Capability.PIXEL_COMPUTER_USE})),
        controller_provider="opencode_go",
        controller_model="muse-spark-1.2-contributor",
        known_capabilities=frozenset({Capability.PIXEL_COMPUTER_USE}),
        helpers=registry.router_helpers(),
    )
    result = policy.helper_executor(registry).execute_planned(
        route,
        helper_id="codex-computer-use",
        operation="list_apps",
        arguments={},
    )

    assert result.output["operation"] == "list_apps"
    receipt = policy.receipt()
    egress = cast(Mapping[str, object], receipt["egress"])
    assert egress["counts"] == {"local": 1}
    assert egress["blocked_counts"] == {"openai": 1}
    await runtime.cleanup()


@pytest.mark.asyncio
async def test_provider_generation_and_managed_runtime_share_policy_object() -> None:
    registry = _registry()
    settings = _settings()
    manager = ProviderRuntimeManager(
        settings,
        runtime_factory=lambda snapshot: _build_provider_runtime(
            snapshot,
            openai_factory=_openai_probe,
            helper_registry=registry,
        ),
    )

    policy = manager.current_session_policy()
    assert policy is not None
    assert policy is manager.current_session_policy()
    lease = await manager.acquire()
    assert lease.session_policy is policy

    second_settings = settings.model_copy(update={"model": "opencode_go/second"})
    await manager.replace(second_settings, commit=lambda: None)
    replacement = await manager.acquire()
    assert replacement.session_policy is not policy
    assert lease.session_policy is policy

    await replacement.release()
    await lease.release()
    await manager.close()


@pytest.mark.asyncio
async def test_managed_session_retains_policy_and_registry_for_its_lifetime() -> None:
    registry = _registry()
    settings = _settings()
    runtime = _build_provider_runtime(
        settings,
        openai_factory=_openai_probe,
        helper_registry=registry,
    )
    policy = runtime.session_policy
    assert policy is not None

    manager = ManagedClaudeSessionManager(
        workspace_path="/tmp",
        proxy_root_url="http://127.0.0.1:8082",
        session_policy=policy,
        approved_helper_registry=registry,
    )
    session, _session_id, is_new = await manager.get_or_create_session()

    assert is_new is True
    assert session.config.session_policy is policy
    assert session.config.approved_helper_registry is registry
    await manager.stop_all()
    await runtime.cleanup()


@pytest.mark.asyncio
async def test_admin_status_publishes_generation_policy_receipt() -> None:
    registry = _registry()
    settings = _settings()
    manager = ProviderRuntimeManager(
        settings,
        runtime_factory=lambda snapshot: _build_provider_runtime(
            snapshot,
            openai_factory=_openai_probe,
            helper_registry=registry,
        ),
    )
    runtime = ApplicationRuntime(manager, transcriber=None)

    status = runtime.admin_status()

    assert status["session_policy"] == {
        "controller_provider": "opencode_go",
        "controller_model": "muse-spark-1.2-contributor",
        "provider_policy_mode": "strict",
        "capability_routing_mode": "smart_local",
        "allowed_helpers": ["codex-computer-use"],
        "paid_fallback": False,
        "egress": {
            "primary_model": "muse-spark-1.2-contributor",
            "primary_provider": "opencode_go",
            "mode": "strict",
            "paid_fallback": False,
            "counts": {},
            "blocked_counts": {},
        },
    }
    await runtime.close()


def test_settings_policy_builder_parses_admin_allowlist() -> None:
    settings = _settings().model_copy(
        update={
            "allowed_helper_ids": "codex-computer-use,\n codex-computer-use",
        }
    )
    policy = build_session_execution_policy_for_settings(settings, _registry())

    assert policy.allowed_helper_ids == frozenset({"codex-computer-use"})
    assert policy.routing_policy.mode is CapabilityRoutingMode.SMART_LOCAL
