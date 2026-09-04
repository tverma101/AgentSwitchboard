from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label} anchor changed")
    return text.replace(old, new, 1)


path = Path("src/free_claude_code/application/routing.py")
text = path.read_text()
text = replace_once(
    text,
    "from free_claude_code.config.provider_catalog import (\n    PROVIDER_CATALOG,\n    SUPPORTED_PROVIDER_IDS,\n)\n",
    "from free_claude_code.config.custom_providers import provider_registry_for_settings\n",
    "provider catalog import",
)
text = replace_once(
    text,
    "    def __init__(self, settings: Settings):\n        self._settings = settings\n        self._model_aliases = parse_model_aliases(\n",
    "    def __init__(self, settings: Settings):\n        self._settings = settings\n        self._provider_catalog = provider_registry_for_settings(settings).catalog\n        self._model_aliases = parse_model_aliases(\n",
    "ModelRouter init",
)
text = replace_once(
    text,
    "        if direct_provider_id is not None and direct_provider_model is not None:\n            if force_ultracode:\n",
    "        if direct_provider_id is not None and direct_provider_model is not None:\n            provider_model_ref = f\"{direct_provider_id}/{direct_provider_model}\"\n            if force_ultracode:\n",
    "direct route",
)
text = replace_once(
    text,
    "                virtual_context_window = self._model_context_windows.get(\n                    requested_model\n                )\n",
    "                virtual_context_window = self._model_context_windows.get(\n                    provider_model_ref\n                )\n",
    "direct context lookup",
)
text = replace_once(
    text,
    "                provider_model_ref=requested_model,\n",
    "                provider_model_ref=provider_model_ref,\n",
    "direct provider_model_ref",
)
old_methods = """    @staticmethod
    def _validate_provider_id(provider_id: str) -> None:
        if provider_id not in PROVIDER_CATALOG:
            raise UnknownProviderError.for_provider(provider_id, PROVIDER_CATALOG)

    @staticmethod
    def _direct_provider_model(
        model_name: str
"""
new_methods = """    def _validate_provider_id(self, provider_id: str) -> None:
        if provider_id not in self._provider_catalog:
            raise UnknownProviderError.for_provider(provider_id, self._provider_catalog)

    def _direct_provider_model(
        self, model_name: str
"""
text = replace_once(text, old_methods, new_methods, "provider methods")
text = replace_once(
    text,
    "decoded.provider_id not in SUPPORTED_PROVIDER_IDS",
    "decoded.provider_id not in self._provider_catalog",
    "decoded provider guard",
)
text = replace_once(
    text,
    "provider_id not in SUPPORTED_PROVIDER_IDS",
    "provider_id not in self._provider_catalog",
    "literal provider guard",
)
path.write_text(text)

tests = Path("tests/application/test_routing.py")
text = tests.read_text()


def replace_in_test(name: str, old: str, new: str) -> None:
    global text
    start = text.index(f"def {name}(")
    end = text.find("\ndef ", start + 1)
    if end == -1:
        end = len(text)
    block = text[start:end]
    block = replace_once(block, old, new, name)
    text = text[:start] + block + text[end:]


replace_in_test(
    "test_model_router_routes_gateway_encoded_provider_model_directly",
    """    assert (
        routed.resolved.provider_model_ref
        == "anthropic/nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )
""",
    """    assert (
        routed.resolved.provider_model_ref
        == "nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )
""",
)
replace_in_test(
    "test_model_router_routes_ultra_gateway_model_with_ultracode_effort",
    """    assert (
        routed.resolved.provider_model_ref
        == "claude-3-freecc-ultra/nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )
""",
    """    assert (
        routed.resolved.provider_model_ref
        == "nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )
""",
)

addition = r'''


def test_model_router_routes_enabled_custom_provider_directly(settings):
    custom_settings = settings.model_copy(
        update={
            "custom_providers_json": (
                '{"providers":[{"id":"custom-lane","display_name":"Custom Lane",'
                '"base_url":"http://localhost:9000/v1","local":true,'
                '"models":["model-x"],"enabled":true}]}'
            )
        }
    )
    router = ModelRouter(custom_settings)

    direct = router.resolve("custom_lane/model-x")
    gateway = router.resolve("anthropic/custom_lane/model-x")

    assert direct.provider_id == "custom_lane"
    assert direct.provider_model == "model-x"
    assert direct.provider_model_ref == "custom_lane/model-x"
    assert gateway.provider_id == "custom_lane"
    assert gateway.provider_model == "model-x"
    assert gateway.provider_model_ref == "custom_lane/model-x"


def test_gateway_model_uses_canonical_manual_context_window(settings):
    settings = settings.model_copy(
        update={
            "model_context_windows": (
                '{"nvidia_nim/deepseek-ai/deepseek-v4-pro": 777777}'
            )
        }
    )

    resolved = ModelRouter(settings).resolve(
        "anthropic/nvidia_nim/deepseek-ai/deepseek-v4-pro"
    )

    assert resolved.provider_model_ref == "nvidia_nim/deepseek-ai/deepseek-v4-pro"
    assert resolved.virtual_context_window == 777_777
'''
if "def test_model_router_routes_enabled_custom_provider_directly(" in text:
    raise RuntimeError("custom provider regression test already exists")
tests.write_text(text.rstrip() + addition + "\n")
