from typing import cast
from unittest.mock import patch

import pytest

from free_claude_code.cli.local_admin import LocalAdminError, apply_admin_values
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return cast(Settings, object())


def test_model_selection_save_verifies_persisted_server_values() -> None:
    calls: list[tuple[str, str]] = []

    def request_json(
        _settings: Settings,
        path: str,
        *,
        method: str = "GET",
        payload: object | None = None,
    ) -> dict[str, object]:
        del payload
        calls.append((method, path))
        if path.endswith("/validate"):
            return {"valid": True}
        if path.endswith("/apply"):
            return {"applied": True}
        return {
            "fields": [
                {"key": "MODEL", "value": "openai/gpt-5.6-sol"},
                {"key": "MODEL_CATALOG_MODE", "value": "curated"},
                {
                    "key": "MODEL_CATALOG_ALLOWLIST",
                    "value": "openai/gpt-5.6-sol, openai/gpt-5.6-luna",
                },
            ]
        }

    with patch(
        "free_claude_code.cli.local_admin._request_json", side_effect=request_json
    ):
        result = apply_admin_values(
            _settings(),
            {
                "MODEL": "openai/gpt-5.6-sol",
                "MODEL_CATALOG_MODE": "curated",
                "MODEL_CATALOG_ALLOWLIST": ("openai/gpt-5.6-luna, openai/gpt-5.6-sol"),
            },
        )

    assert result["applied"] is True
    assert calls == [
        ("POST", "/admin/api/config/validate"),
        ("POST", "/admin/api/config/apply"),
        ("GET", "/admin/api/config"),
    ]


def test_model_selection_save_fails_when_persisted_value_disagrees() -> None:
    responses = iter(
        (
            {"valid": True},
            {"applied": True},
            {"fields": [{"key": "MODEL", "value": "openai/gpt-5.6-luna"}]},
        )
    )

    with (
        patch(
            "free_claude_code.cli.local_admin._request_json",
            side_effect=lambda *_args, **_kwargs: next(responses),
        ),
        pytest.raises(LocalAdminError, match="persisted config"),
    ):
        apply_admin_values(_settings(), {"MODEL": "openai/gpt-5.6-sol"})
