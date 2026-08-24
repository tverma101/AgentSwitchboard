from free_claude_code.providers.model_listing import extract_openai_model_infos


def test_openai_model_listing_preserves_explicit_vision_capabilities() -> None:
    infos = extract_openai_model_infos(
        {
            "data": [
                {
                    "id": "vision-model",
                    "capabilities": {
                        "vision": True,
                        "accepted_image_types": [
                            "image/png",
                            "image/webp",
                            "image/gif",
                        ],
                    },
                },
                {"id": "text-only", "capabilities": {"vision": False}},
            ]
        },
        provider_name="TEST",
    )

    by_id = {info.model_id: info for info in infos}
    assert by_id["vision-model"].supports_vision is True
    assert by_id["vision-model"].accepted_image_types == ("image/png", "image/webp")
    assert by_id["text-only"].supports_vision is False
