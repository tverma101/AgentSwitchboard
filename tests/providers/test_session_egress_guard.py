"""Provider construction must preserve a launch-owned shared egress guard."""

from unittest.mock import MagicMock

from free_claude_code.core.provider_policy import ProviderEgressGuard, ProviderPolicy
from free_claude_code.providers.base import ProviderConfig
from free_claude_code.providers.runtime.factory import _create_opencode_go


def test_opencode_go_preserves_injected_session_guard() -> None:
    guard = ProviderEgressGuard(
        ProviderPolicy(
            primary_provider="opencode_go",
            primary_model="muse-spark-1.2-contributor",
        )
    )
    config = ProviderConfig(
        api_key="test",
        base_url="https://opencode.ai/zen/v1",
        provider_family="opencode_go",
        egress_guard=guard,
    )
    settings = MagicMock()
    settings.model = "opencode_go/muse-spark-1.2-contributor"
    admission = MagicMock()

    provider = _create_opencode_go(config, settings, admission)

    assert provider._config.egress_guard is guard
