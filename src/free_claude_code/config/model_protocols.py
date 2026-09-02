"""Provider model protocol manifests used by routing and diagnostics."""

from enum import StrEnum


class GoProtocol(StrEnum):
    """Wire protocols currently documented by OpenCode Go."""

    CHAT = "chat/completions"
    RESPONSES = "responses"
    MESSAGES = "messages"


OPENCODE_GO_MODEL_PROTOCOLS: dict[str, GoProtocol] = {
    # Synced from https://dev.opencode.ai/docs/go/ endpoints table.
    # Responses: grok-4.6, gpt-5.6-luna, muse-spark-1.2/1.3-contributor.
    # Chat: glm-*, kimi-*, deepseek-*, mimo-*, longcat-2.0, hy*.
    # Messages (Anthropic native): minimax-*, qwen3.*.
    "grok-4.6": GoProtocol.RESPONSES,
    "grok-4.5": GoProtocol.RESPONSES,
    "gpt-5.6-luna": GoProtocol.RESPONSES,
    "glm-5.3-flash": GoProtocol.CHAT,
    "glm-5.3": GoProtocol.CHAT,
    "glm-5.2": GoProtocol.CHAT,
    "glm-5.1": GoProtocol.CHAT,
    "kimi-k3": GoProtocol.CHAT,
    "kimi-k2.7-code": GoProtocol.CHAT,
    "kimi-k2.6": GoProtocol.CHAT,
    "longcat-2.0": GoProtocol.CHAT,
    "deepseek-v4-pro": GoProtocol.CHAT,
    "deepseek-v4-flash": GoProtocol.CHAT,
    "deepseek-v4-flash-vision-exp": GoProtocol.CHAT,
    "mimo-v2.5": GoProtocol.CHAT,
    "mimo-v2.5-pro": GoProtocol.CHAT,
    "minimax-m3": GoProtocol.MESSAGES,
    "minimax-m2.7": GoProtocol.MESSAGES,
    "minimax-m2.5": GoProtocol.MESSAGES,
    "muse-spark-1.3-contributor": GoProtocol.RESPONSES,
    "muse-spark-1.2-contributor": GoProtocol.RESPONSES,
    "qwen3.8-max": GoProtocol.MESSAGES,
    "qwen3.8-flash": GoProtocol.MESSAGES,
    "qwen3.7-max": GoProtocol.MESSAGES,
    "qwen3.7-plus": GoProtocol.MESSAGES,
    "qwen3.6-plus": GoProtocol.MESSAGES,
    "hy4-preview": GoProtocol.CHAT,
    "hy3": GoProtocol.CHAT,
    "ox-alpha-free": GoProtocol.CHAT,
}


__all__ = ["OPENCODE_GO_MODEL_PROTOCOLS", "GoProtocol"]
