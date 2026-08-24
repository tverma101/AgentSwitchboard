"""CLI facade for FCC's shared Claude compatibility controls."""

from free_claude_code.core.claude_compatibility import (
    CLAUDE_ALLOW_UNCERTIFIED_ENV,
    CLAUDE_KNOWN_GOOD_VERSION_ENV,
    CLAUDE_PROCESS_WRAPPER_ENV,
    CLAUDE_PROCESS_WRAPPER_PATH_ENV,
    ClaudeCompatibilityError,
    ClaudeCompatibilityStatus,
    default_process_wrapper_path,
    enforce_claude_compatibility,
    ensure_process_wrapper,
    inspect_claude_compatibility,
    write_compatibility_receipt,
)

__all__ = [
    "CLAUDE_ALLOW_UNCERTIFIED_ENV",
    "CLAUDE_KNOWN_GOOD_VERSION_ENV",
    "CLAUDE_PROCESS_WRAPPER_ENV",
    "CLAUDE_PROCESS_WRAPPER_PATH_ENV",
    "ClaudeCompatibilityError",
    "ClaudeCompatibilityStatus",
    "default_process_wrapper_path",
    "enforce_claude_compatibility",
    "ensure_process_wrapper",
    "inspect_claude_compatibility",
    "write_compatibility_receipt",
]
