import pytest

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityHelper,
    CapabilityRouter,
    CapabilityRoutingError,
    CapabilityRoutingMode,
    CapabilityRoutingPolicy,
    RequiredCapabilitySet,
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


def test_strict_capability_router_fails_before_helper_or_controller_fallback() -> None:
    required = RequiredCapabilitySet(
        frozenset(
            {Capability.TEXT_INPUT, Capability.TEXT_OUTPUT, Capability.VISION_INPUT}
        )
    )

    with pytest.raises(CapabilityRoutingError, match="strict policy"):
        CapabilityRouter().plan(
            required,
            controller_provider="opencode_go",
            controller_model="muse-spark-1.2-contributor",
            known_capabilities=frozenset({Capability.VISION_INPUT}),
        )


def test_smart_local_router_selects_only_allowlisted_local_helper() -> None:
    required = RequiredCapabilitySet(frozenset({Capability.VISION_INPUT}))
    helper = CapabilityHelper(
        helper_id="local-vision",
        provider_family="local",
        model_ref="local/vision",
        capabilities=frozenset({Capability.VISION_INPUT}),
        local=True,
    )
    router = CapabilityRouter(
        CapabilityRoutingPolicy(
            mode=CapabilityRoutingMode.SMART_LOCAL,
            allowed_helpers=frozenset({"local-vision"}),
        )
    )

    plan = router.plan(
        required,
        controller_provider="opencode_go",
        controller_model="muse",
        helpers=(helper,),
    )

    assert plan.decision == "helpers"
    assert plan.controller_provider == "opencode_go"
    assert plan.controller_failover is False
    assert plan.helpers == (helper,)
    assert plan.as_receipt()["helpers"] == [
        {
            "helper_id": "local-vision",
            "provider_family": "local",
            "model_ref": "local/vision",
            "capabilities": ["vision_input"],
            "local": True,
            "billable": False,
        }
    ]


def test_smart_go_router_rejects_non_go_helper_and_allows_explicit_go_helper() -> None:
    required = RequiredCapabilitySet(frozenset({Capability.VISION_INPUT}))
    local_helper = CapabilityHelper(
        helper_id="local-vision",
        provider_family="local",
        model_ref="local/vision",
        capabilities=frozenset({Capability.VISION_INPUT}),
        local=True,
    )
    go_helper = CapabilityHelper(
        helper_id="go-vision",
        provider_family="opencode_go",
        model_ref="opencode_go/vision",
        capabilities=frozenset({Capability.VISION_INPUT}),
        billable=True,
    )
    router = CapabilityRouter(
        CapabilityRoutingPolicy(
            mode=CapabilityRoutingMode.SMART_GO,
            allowed_helpers=frozenset({"go-vision"}),
        )
    )

    plan = router.plan(
        required,
        controller_provider="opencode_go",
        controller_model="muse",
        helpers=(local_helper, go_helper),
    )

    assert plan.helpers == (go_helper,)
    assert plan.controller_model == "muse"


def test_controller_failover_is_not_implicit_even_when_requested() -> None:
    required = RequiredCapabilitySet(frozenset({Capability.VISION_INPUT}))
    router = CapabilityRouter(
        CapabilityRoutingPolicy(
            mode=CapabilityRoutingMode.CUSTOM,
            allow_controller_failover=True,
        )
    )

    with pytest.raises(CapabilityRoutingError, match="separate policy"):
        router.plan(
            required,
            controller_provider="opencode_go",
            controller_model="muse",
        )
