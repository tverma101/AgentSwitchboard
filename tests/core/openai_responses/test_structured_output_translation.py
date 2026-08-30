import pytest

from free_claude_code.core.anthropic.models import MessagesRequest
from free_claude_code.core.openai_responses.errors import ResponsesConversionError
from free_claude_code.core.openai_responses.provider_input import (
    build_responses_provider_request,
)
from free_claude_code.core.reasoning import ReasoningPolicy


def _request(output_config: dict[str, object]) -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "Return the record"}],
            "output_config": output_config,
        }
    )


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }


def test_translates_claude_json_schema_output_to_responses_text_format() -> None:
    schema = _schema()
    request = _request(
        {"format": {"type": "json_schema", "schema": schema}}
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["text"] == {
        "format": {
            "type": "json_schema",
            "name": "claude_output",
            "schema": schema,
            "strict": True,
        }
    }


def test_structured_output_composes_with_reasoning_output_config() -> None:
    request = _request(
        {
            "effort": "high",
            "summary": "concise",
            "format": {"type": "json_schema", "schema": _schema()},
        }
    )

    body = build_responses_provider_request(
        request,
        reasoning=ReasoningPolicy.provider_default(),
    )

    assert body["text"]["format"]["type"] == "json_schema"
    assert body["reasoning"]["summary"] == "concise"


def test_rejects_unknown_claude_structured_output_type() -> None:
    request = _request({"format": {"type": "json_object", "schema": _schema()}})

    with pytest.raises(ResponsesConversionError, match="json_schema"):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )


def test_rejects_malformed_claude_structured_output_shape() -> None:
    request = _request(
        {
            "format": {
                "type": "json_schema",
                "schema": _schema(),
                "name": "do-not-pass-through",
            }
        }
    )

    with pytest.raises(ResponsesConversionError, match="exactly type and schema"):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )


def test_unknown_output_config_fields_still_fail_loud() -> None:
    request = _request(
        {
            "format": {"type": "json_schema", "schema": _schema()},
            "future_knob": True,
        }
    )

    with pytest.raises(ResponsesConversionError, match="output_config.future_knob"):
        build_responses_provider_request(
            request,
            reasoning=ReasoningPolicy.provider_default(),
        )
