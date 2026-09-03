"""Regression coverage for bounded per-model Claude context windows."""

import pytest

from free_claude_code.config.model_refs import parse_model_context_windows


def test_model_context_windows_accepts_safety_boundaries() -> None:
    assert parse_model_context_windows(
        '{"provider/min-model": 32000, "provider/max-model": 1000000}'
    ) == {
        "provider/min-model": 32_000,
        "provider/max-model": 1_000_000,
    }


@pytest.mark.parametrize("tokens", [1, 31_999, 1_000_001, 999_999_999_999])
def test_model_context_windows_rejects_values_outside_safety_range(tokens: int) -> None:
    with pytest.raises(ValueError, match="between 32000 and 1000000"):
        parse_model_context_windows(f'{{"provider/model": {tokens}}}')


def test_model_context_windows_rejects_non_integer_values() -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        parse_model_context_windows('{"provider/model": 32000.5}')
