from free_claude_code.application.capabilities import (
    Capability,
    required_capabilities_for_messages,
)
from free_claude_code.core.anthropic.models import Message, MessagesRequest, Tool


def test_required_capabilities_extract_image_and_nested_tool_result() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "provider/model",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "inspect"},
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "url",
                                        "url": "https://example.test/image.png",
                                    },
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )

    required = required_capabilities_for_messages(request)

    assert required.capabilities == frozenset(
        {
            Capability.TEXT_INPUT,
            Capability.TEXT_OUTPUT,
            Capability.VISION_INPUT,
            Capability.IMAGE_TOOL_RESULTS,
        }
    )
    assert required.as_dict()["capabilities"] == [
        "image_tool_results",
        "text_input",
        "text_output",
        "vision_input",
    ]


def test_required_capabilities_extract_tool_modes_without_prompt_content() -> None:
    request = MessagesRequest(
        model="provider/model",
        messages=[
            Message(
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": "one",
                        "name": "browser.click",
                        "input": {},
                    },
                    {
                        "type": "tool_use",
                        "id": "two",
                        "name": "computer.inspect",
                        "input": {},
                    },
                ],
            )
        ],
        tools=[Tool(name="screenshot.capture")],
        tool_choice={"type": "tool", "name": "screenshot.capture"},
        thinking={"enabled": True},
        output_config={"format": {"type": "json_schema"}},
        parallel_tool_calls=True,
    )

    required = required_capabilities_for_messages(request)

    assert required.capabilities == frozenset(
        {
            Capability.TEXT_INPUT,
            Capability.TEXT_OUTPUT,
            Capability.NATIVE_TOOLS,
            Capability.PARALLEL_TOOLS,
            Capability.NAMED_TOOL_CHOICE,
            Capability.REASONING_EFFORT,
            Capability.STRUCTURED_OUTPUT,
            Capability.SEMANTIC_BROWSER_CONTROL,
            Capability.SEMANTIC_MACOS_CONTROL,
            Capability.SCREENSHOT_VISION,
        }
    )


def test_text_only_request_has_no_visual_or_helper_requirements() -> None:
    required = required_capabilities_for_messages(
        MessagesRequest(
            model="provider/model", messages=[Message(role="user", content="hi")]
        )
    )

    assert required.capabilities == {
        Capability.TEXT_INPUT,
        Capability.TEXT_OUTPUT,
    }
