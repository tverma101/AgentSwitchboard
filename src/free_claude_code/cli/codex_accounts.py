"""Manage multiple installed Codex tool accounts safely.

The live Codex credential remains ``$CODEX_HOME/auth.json``. Saved profiles use
``$CODEX_HOME/accounts/profiles/<name>/auth.json`` so they are compatible with
the public MIT ``Fasand/codex-auth`` profile layout. Switching never invokes
Codex login/logout. Adding an account stashes the live auth file before the
official login flow, preventing a second login from revoking the first saved
account's refresh grant.

This store is intentionally independent from FCC's OpenAI provider credentials
in ``~/.fcc/auth/openai.json``. The two account selectors must never copy or
replace credentials in the other store.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from free_claude_code.core.interprocess_lock import InterprocessFileLock

from .local_http import open_local_request
from .selection import SelectionItem, choose_item

DEFAULT_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"
FALLBACK_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
ACCOUNT_LOCK_TIMEOUT_SECONDS = 30.0
USAGE_TIMEOUT_SECONDS = 20.0
_CODEX_API_ENV_KEYS = ("OPENAI_API_KEY", "CODEX_API_KEY")
_PROFILE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class CodexAccountError(RuntimeError):
    """A local Codex account operation could not complete safely."""


@dataclass(frozen=True, slots=True)
class CodexAccount:
    """Credential-free subscription snapshot safe for terminal display."""

    profile: str
    account_id: str
    email: str | None
    active: bool
    plan: str | None
    usage: Mapping[str, Any] | None

    def public_dict(self) -> dict[str, Any]:
        """Return the display/API projection without ids or credential data."""

        return {
            "profile": self.profile,
            "email": self.email,
            "active": self.active,
            "plan": self.plan,
            "usage": _public_usage(self.usage),
        }


@dataclass(frozen=True, slots=True)
class _Identity:
    account_id: str
    email: str | None


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def auth_path(home: Path | None = None) -> Path:
    return (home or codex_home()) / "auth.json"


def profiles_dir(home: Path | None = None) -> Path:
    return (home or codex_home()) / "accounts" / "profiles"


def profile_dir(profile: str, home: Path | None = None) -> Path:
    _validate_profile(profile)
    return profiles_dir(home) / profile


def profile_auth_path(profile: str, home: Path | None = None) -> Path:
    return profile_dir(profile, home) / "auth.json"


def profile_usage_path(profile: str, home: Path | None = None) -> Path:
    return profile_dir(profile, home) / "usage.json"


def _marker_path(home: Path) -> Path:
    return home / "accounts" / "current_profile"


def _lock_path(home: Path) -> Path:
    return home / "accounts" / "fcc-accounts.lock"


@contextmanager
def _locked(home: Path) -> Iterator[None]:
    lock = InterprocessFileLock(_lock_path(home))
    if not lock.acquire(wait=True, timeout=ACCOUNT_LOCK_TIMEOUT_SECONDS):
        raise CodexAccountError("Timed out waiting for the Codex account lock.")
    try:
        yield
    finally:
        lock.release()


def list_accounts(*, home: Path | None = None) -> tuple[CodexAccount, ...]:
    """List saved accounts, first importing/syncing the current Codex login."""

    root = home or codex_home()
    with _locked(root):
        _sync_live(root)
        live = _try_identity(auth_path(root))
        accounts: list[CodexAccount] = []
        directory = profiles_dir(root)
        if not directory.is_dir():
            return ()
        for item in sorted(
            directory.iterdir(), key=lambda value: value.name.casefold()
        ):
            if not item.is_dir() or not _PROFILE_RE.fullmatch(item.name):
                continue
            identity = _try_identity(item / "auth.json")
            if identity is None:
                continue
            usage = _read_json(item / "usage.json")
            plan = _string(usage, "plan_type")
            accounts.append(
                CodexAccount(
                    profile=item.name,
                    account_id=identity.account_id,
                    email=identity.email,
                    active=live is not None and live.account_id == identity.account_id,
                    plan=plan,
                    usage=usage,
                )
            )
    return tuple(
        sorted(accounts, key=lambda item: (not item.active, item.profile.casefold()))
    )


def active_account(*, home: Path | None = None) -> CodexAccount | None:
    """Read the active local account without importing or writing a profile."""

    root = home or codex_home()
    with _locked(root):
        identity = _try_identity(auth_path(root))
        if identity is None:
            return None
        profile = _profile_for_account(root, identity.account_id) or _read_marker(root)
        profile = profile or "active"
        usage = _read_json(profile_usage_path(profile, root))
    return CodexAccount(
        profile=profile,
        account_id=identity.account_id,
        email=identity.email,
        active=True,
        plan=_string(usage, "plan_type"),
        usage=usage,
    )


def active_account_summary(*, home: Path | None = None) -> str:
    """Return a concise local-only label for the active Codex tool account."""

    account = active_account(home=home)
    if account is None:
        return "not connected"
    identity = account.email or account.profile
    return f"{identity} (profile {account.profile})"


def select_account(profile: str, *, home: Path | None = None) -> CodexAccount:
    """Select a saved account without logging out or invoking OAuth."""

    root = home or codex_home()
    _validate_profile(profile)
    with _locked(root):
        _sync_live(root)
        source = profile_auth_path(profile, root)
        identity = _identity(source)
        _atomic_write(auth_path(root), source.read_bytes())
        _write_marker(root, profile)
        usage = _read_json(profile_usage_path(profile, root))
    return CodexAccount(
        profile=profile,
        account_id=identity.account_id,
        email=identity.email,
        active=True,
        plan=_string(usage, "plan_type"),
        usage=usage,
    )


def add_account(
    profile: str,
    *,
    device_auth: bool = False,
    home: Path | None = None,
    executable: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> CodexAccount:
    """Safely run the official Codex sign-in/account-creation flow."""

    _validate_profile(profile)
    root = home or codex_home()
    codex = executable or shutil.which("codex")
    if codex is None:
        raise CodexAccountError("Codex CLI was not found on PATH.")
    stash = root / f".fcc-auth-stash-{uuid.uuid4().hex}.json"
    previous_marker = _read_marker(root)

    with _locked(root):
        _sync_live(root)
        if profile_dir(profile, root).exists():
            raise CodexAccountError(f"Codex account profile already exists: {profile}")
        root.mkdir(parents=True, exist_ok=True)
        _private_dir(root)
        live = auth_path(root)
        if live.exists():
            os.replace(live, stash)
            _private_file(stash)

    argv = [codex, "login"]
    if device_auth:
        argv.append("--device-auth")
    try:
        result = runner(argv, env=_codex_environment(), check=False)
    except Exception as exc:
        _restore_stash(root, stash, previous_marker)
        raise CodexAccountError(
            f"Could not start Codex login ({type(exc).__name__})."
        ) from exc
    if result.returncode != 0:
        _restore_stash(root, stash, previous_marker)
        raise CodexAccountError(f"Codex login exited with status {result.returncode}.")

    with _locked(root):
        live = auth_path(root)
        try:
            identity = _identity(live)
        except CodexAccountError:
            live.unlink(missing_ok=True)
            if stash.exists():
                os.replace(stash, live)
                _private_file(live)
            _restore_marker(root, previous_marker)
            raise
        existing = _profile_for_account(root, identity.account_id)
        target = existing or _available_profile(root, profile, identity.account_id)
        _save_profile(root, target, live, identity)
        _write_marker(root, target)
        stash.unlink(missing_ok=True)
        usage = _read_json(profile_usage_path(target, root))
    return CodexAccount(
        profile=target,
        account_id=identity.account_id,
        email=identity.email,
        active=True,
        plan=_string(usage, "plan_type"),
        usage=usage,
    )


def forget_account(profile: str, *, home: Path | None = None) -> None:
    """Forget a local saved snapshot without upstream logout/revocation."""

    root = home or codex_home()
    _validate_profile(profile)
    with _locked(root):
        _sync_live(root)
        target = profile_dir(profile, root)
        if not target.is_dir():
            raise CodexAccountError(f"Unknown Codex account profile: {profile}")
        target_identity = _identity(target / "auth.json")
        live = _try_identity(auth_path(root))
        if live is not None and live.account_id == target_identity.account_id:
            raise CodexAccountError(
                "Cannot forget the active Codex account. Select another first."
            )
        shutil.rmtree(target)
        if _read_marker(root) == profile:
            _marker_path(root).unlink(missing_ok=True)


def refresh_usage(
    profile: str,
    *,
    home: Path | None = None,
    opener: Callable[..., Any] = open_local_request,
) -> Mapping[str, Any]:
    """Refresh a saved account's plan and rate-limit windows without switching."""

    root = home or codex_home()
    _validate_profile(profile)
    with _locked(root):
        _sync_live(root)
        auth = _read_auth(profile_auth_path(profile, root))
    tokens = auth.get("tokens")
    if not isinstance(tokens, Mapping):
        raise CodexAccountError("Codex auth snapshot is missing tokens.")
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not isinstance(access_token, str) or not access_token:
        raise CodexAccountError("Codex auth snapshot is missing an access token.")
    if not isinstance(account_id, str) or not account_id:
        raise CodexAccountError("Codex auth snapshot is missing an account id.")

    error: CodexAccountError | None = None
    for approximate, url in (
        (False, DEFAULT_USAGE_URL),
        (True, FALLBACK_USAGE_URL),
    ):
        try:
            raw = _fetch_usage(url, access_token, account_id, opener)
        except CodexAccountError as exc:
            error = exc
            continue
        usage = _normalize_usage(raw, approximate=approximate)
        with _locked(root):
            _atomic_json(profile_usage_path(profile, root), usage)
        return usage
    raise error or CodexAccountError("Could not refresh Codex usage limits.")


def refresh_all_usage(*, home: Path | None = None) -> dict[str, str | None]:
    outcomes: dict[str, str | None] = {}
    for account in list_accounts(home=home):
        try:
            refresh_usage(account.profile, home=home)
        except CodexAccountError as exc:
            outcomes[account.profile] = str(exc)
        else:
            outcomes[account.profile] = None
    return outcomes


def _fetch_usage(
    url: str,
    access_token: str,
    account_id: str,
    opener: Callable[..., Any],
) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": account_id,
            "Accept": "application/json",
            "User-Agent": "free-claude-code/subscription-accounts",
        },
    )
    try:
        with opener(request, timeout=USAGE_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
    except HTTPError as exc:
        if exc.code == 401:
            raise CodexAccountError(
                "ChatGPT session expired; sign in to this account again."
            ) from exc
        raise CodexAccountError(f"Usage endpoint returned HTTP {exc.code}.") from exc
    except (URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexAccountError(
            f"Usage refresh failed ({type(exc).__name__})."
        ) from exc
    if not isinstance(data, Mapping):
        raise CodexAccountError("Usage endpoint returned an invalid payload.")
    return data


def _normalize_usage(raw: Mapping[str, Any], *, approximate: bool) -> dict[str, Any]:
    rate = raw.get("rate_limit")
    rate = rate if isinstance(rate, Mapping) else {}
    windows: list[dict[str, Any]] = []
    for window_id, key in (
        ("primary", "primary_window"),
        ("secondary", "secondary_window"),
    ):
        item = rate.get(key)
        if not isinstance(item, Mapping):
            continue
        used = _number(item.get("used_percent"))
        seconds = _integer(item.get("limit_window_seconds"))
        windows.append(
            {
                "id": window_id,
                "label": _window_label(seconds),
                "used_percent": used,
                "remaining_percent": None if used is None else max(0.0, 100.0 - used),
                "window_seconds": seconds,
                "reset_at": _integer(item.get("reset_at")),
            }
        )
    additional: list[dict[str, Any]] = []
    raw_additional = raw.get("additional_rate_limits")
    if isinstance(raw_additional, list):
        for item in raw_additional:
            if not isinstance(item, Mapping):
                continue
            limit = item.get("rate_limit")
            limit = limit if isinstance(limit, Mapping) else {}
            window = limit.get("primary_window")
            if not isinstance(window, Mapping):
                continue
            used = _number(window.get("used_percent"))
            additional.append(
                {
                    "name": str(
                        item.get("limit_name")
                        or item.get("metered_feature")
                        or "additional"
                    ),
                    "used_percent": used,
                    "remaining_percent": None
                    if used is None
                    else max(0.0, 100.0 - used),
                }
            )
    credits_raw = raw.get("credits")
    credits: dict[str, Any] = {}
    if isinstance(credits_raw, Mapping):
        for key in ("balance", "has_credits", "unlimited"):
            if key in credits_raw:
                credits[key] = credits_raw[key]
    plan = raw.get("plan_type")
    return {
        "version": 1,
        "fetched_at": int(time.time()),
        "approximate": approximate,
        "plan_type": plan if isinstance(plan, str) else None,
        "windows": windows,
        "additional_limits": additional,
        "credits": credits,
    }


def _sync_live(home: Path) -> str | None:
    live = auth_path(home)
    if not live.is_file():
        return None
    identity = _identity(live)
    profile = _profile_for_account(home, identity.account_id)
    if profile is None:
        marker = _read_marker(home)
        if marker and not profile_dir(marker, home).exists():
            profile = marker
        else:
            profile = _derive_profile(home, identity)
    _save_profile(home, profile, live, identity)
    _write_marker(home, profile)
    return profile


def _save_profile(home: Path, profile: str, source: Path, identity: _Identity) -> None:
    directory = profile_dir(profile, home)
    directory.mkdir(parents=True, exist_ok=True)
    _private_dir(directory)
    _atomic_write(directory / "auth.json", source.read_bytes())
    _atomic_json(
        directory / "meta.json",
        {
            "profileName": profile,
            "savedAt": int(time.time()),
            "email": identity.email,
            "accountId": identity.account_id,
        },
    )


def _profile_for_account(home: Path, account_id: str) -> str | None:
    directory = profiles_dir(home)
    if not directory.is_dir():
        return None
    for item in directory.iterdir():
        if not item.is_dir() or not _PROFILE_RE.fullmatch(item.name):
            continue
        identity = _try_identity(item / "auth.json")
        if identity is not None and identity.account_id == account_id:
            return item.name
    return None


def _available_profile(home: Path, requested: str, account_id: str) -> str:
    if not profile_dir(requested, home).exists():
        return requested
    suffix = re.sub(r"[^A-Za-z0-9]", "", account_id)[-8:] or uuid.uuid4().hex[:8]
    candidate = f"{requested}-{suffix}"
    counter = 2
    while profile_dir(candidate, home).exists():
        candidate = f"{requested}-{suffix}-{counter}"
        counter += 1
    return candidate


def _derive_profile(home: Path, identity: _Identity) -> str:
    stem = identity.email.split("@", 1)[0] if identity.email else "account"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("._-") or "account"
    return _available_profile(home, stem, identity.account_id)


def _read_auth(path: Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CodexAccountError(f"Codex ChatGPT auth was not found at {path}.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexAccountError("Codex ChatGPT auth file is invalid.") from exc
    if not isinstance(raw, Mapping) or not isinstance(raw.get("tokens"), Mapping):
        raise CodexAccountError("Codex is not using ChatGPT subscription auth.")
    return raw


def _identity(path: Path) -> _Identity:
    raw = _read_auth(path)
    tokens = raw.get("tokens")
    if not isinstance(tokens, Mapping):
        raise CodexAccountError("Codex ChatGPT auth token bundle is missing.")
    account_id = tokens.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise CodexAccountError("Codex ChatGPT auth is missing an account id.")
    id_claims = _jwt_claims(tokens.get("id_token"))
    access_claims = _jwt_claims(tokens.get("access_token"))
    email = _claim(id_claims, "email") or _claim(access_claims, "email")
    return _Identity(account_id, email)


def _try_identity(path: Path) -> _Identity | None:
    try:
        return _identity(path)
    except CodexAccountError:
        return None


def _jwt_claims(token: Any) -> Mapping[str, Any]:
    if not isinstance(token, str):
        return {}
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode())
    except ValueError, UnicodeDecodeError, json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, Mapping) else {}


def _claim(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) and value else None


def _restore_stash(home: Path, stash: Path, marker: str | None) -> None:
    with _locked(home):
        live = auth_path(home)
        live.unlink(missing_ok=True)
        if stash.exists():
            os.replace(stash, live)
            _private_file(live)
        _restore_marker(home, marker)


def _codex_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in _CODEX_API_ENV_KEYS:
        environment.pop(key, None)
    return environment


def _validate_profile(profile: str) -> None:
    if not profile or not _PROFILE_RE.fullmatch(profile):
        raise CodexAccountError(
            "Profile names may contain only letters, numbers, dot, underscore, and hyphen."
        )


def _write_marker(home: Path, profile: str) -> None:
    _atomic_write(_marker_path(home), f"{profile}\n".encode())


def _read_marker(home: Path) -> str | None:
    try:
        value = _marker_path(home).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if value and _PROFILE_RE.fullmatch(value) else None


def _restore_marker(home: Path, profile: str | None) -> None:
    if profile:
        _write_marker(home, profile)
    else:
        _marker_path(home).unlink(missing_ok=True)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _private_dir(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        _private_file(temporary)
        os.replace(temporary, path)
        _private_file(path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, raw: Mapping[str, Any]) -> None:
    _atomic_write(path, (json.dumps(raw, indent=2, sort_keys=True) + "\n").encode())


def _read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return None
    return raw if isinstance(raw, Mapping) else None


def _private_dir(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700)


def _private_file(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o600)


def _string(raw: Mapping[str, Any] | None, key: str) -> str | None:
    value = raw.get(key) if raw is not None else None
    return value if isinstance(value, str) and value else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _window_label(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return "limit"
    if seconds % 604800 == 0:
        weeks = seconds // 604800
        return "weekly" if weeks == 1 else f"{weeks}w"
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    return f"{seconds / 3600:g}h"


def _format_reset(value: Any) -> str:
    timestamp = _integer(value)
    if timestamp is None:
        return ""
    try:
        return datetime.fromtimestamp(timestamp).astimezone().strftime("%b %d %H:%M")
    except OSError, OverflowError, ValueError:
        return ""


def _percent(value: Any) -> str:
    number = _number(value)
    return f"{round(number)}%" if number is not None else "?"


def _usage_lines(
    usage: Mapping[str, Any] | None, *, compact: bool = False
) -> list[str]:
    if not usage:
        return ["limits not refreshed"]
    prefix = "~" if usage.get("approximate") is True else ""
    lines: list[str] = []
    windows = usage.get("windows")
    if isinstance(windows, list):
        for window in windows:
            if not isinstance(window, Mapping):
                continue
            remaining = window.get("remaining_percent")
            if remaining is None:
                continue
            text = f"{window.get('label', 'limit')} {prefix}{_percent(remaining)} left"
            reset = _format_reset(window.get("reset_at"))
            if reset:
                text += f" (resets {reset})"
            lines.append(text)
    additional = usage.get("additional_limits")
    if isinstance(additional, list):
        lines.extend(
            f"{item.get('name', 'additional')} {prefix}{_percent(item['remaining_percent'])} left"
            for item in additional
            if isinstance(item, Mapping) and item.get("remaining_percent") is not None
        )
    credits = usage.get("credits")
    if isinstance(credits, Mapping):
        if credits.get("unlimited") is True:
            lines.append("credits unlimited")
        elif credits.get("balance") not in {None, "", 0, "0"}:
            lines.append(f"credits {credits['balance']}")
    return (
        lines[:2] if compact and len(lines) > 2 else (lines or ["limits unavailable"])
    )


def _public_usage(usage: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Keep the Admin projection limited to the normalized usage schema."""

    if not usage:
        return None
    result: dict[str, Any] = {
        key: usage[key]
        for key in ("version", "fetched_at", "approximate", "plan_type")
        if key in usage
    }
    windows = usage.get("windows")
    if isinstance(windows, list):
        result["windows"] = [
            {
                key: item[key]
                for key in (
                    "id",
                    "label",
                    "used_percent",
                    "remaining_percent",
                    "window_seconds",
                    "reset_at",
                )
                if key in item
            }
            for item in windows
            if isinstance(item, Mapping)
        ]
    additional = usage.get("additional_limits")
    if isinstance(additional, list):
        result["additional_limits"] = [
            {
                key: item[key]
                for key in ("name", "used_percent", "remaining_percent")
                if key in item
            }
            for item in additional
            if isinstance(item, Mapping)
        ]
    credits = usage.get("credits")
    if isinstance(credits, Mapping):
        result["credits"] = {
            key: credits[key]
            for key in ("balance", "has_credits", "unlimited")
            if key in credits
        }
    return result


def _print_accounts(accounts: Sequence[CodexAccount]) -> None:
    if not accounts:
        print("No saved Codex tool accounts.")
        return
    for account in accounts:
        marker = ">" if account.active else " "
        plan = f"  {account.plan}" if account.plan else ""
        print(
            f"{marker} {account.profile:<18} {account.email or account.profile}{plan}"
        )
        for line in _usage_lines(account.usage):
            print(f"    {line}")


def _choose_account(accounts: Sequence[CodexAccount]) -> CodexAccount | None:
    if not accounts:
        print("No saved Codex tool accounts.")
        return None
    selected = choose_item(
        [
            SelectionItem(
                item_id=account.profile,
                label=account.email or account.profile,
                detail=" · ".join(
                    [
                        account.plan or "plan unknown",
                        *_usage_lines(account.usage, compact=True),
                    ]
                    + (["active"] if account.active else [])
                ),
            )
            for account in accounts
        ],
        title="Codex tool accounts",
        footer="type filter · ↑↓ move · enter select · esc cancel",
    )
    if selected is None:
        return None
    return next((item for item in accounts if item.profile == selected.item_id), None)


def _restart_notice() -> None:
    print(
        "Selection applies to new Codex/helper sessions. Restart FCC or start a "
        "fresh Harness session before using the selected subscription."
    )


def _interactive() -> int:
    while True:
        try:
            accounts = list_accounts()
        except CodexAccountError as exc:
            print(f"Codex tool accounts unavailable: {exc}")
            accounts = ()
        print("\nCodex Tool Accounts\n-------------------")
        _print_accounts(accounts)
        print(
            "[S] Select  [A] Add/sign up  [D] Device add  [R] Refresh  [F] Forget  [Q] Quit"
        )
        try:
            action = input("Accounts> ").strip().casefold()
        except EOFError, KeyboardInterrupt:
            print()
            return 0
        if action in {"q", "quit", "b", "back"}:
            return 0
        if action in {"s", "select"}:
            account = _choose_account(accounts)
            if account is not None:
                try:
                    select_account(account.profile)
                except CodexAccountError as exc:
                    print(f"Could not select account: {exc}")
                else:
                    _restart_notice()
        elif action in {"a", "add", "d", "device"}:
            try:
                profile = input("Profile name> ").strip()
            except EOFError, KeyboardInterrupt:
                print()
                continue
            if not profile:
                continue
            print("Official Codex login can sign in or create a new tool account.")
            try:
                account = add_account(profile, device_auth=action in {"d", "device"})
            except CodexAccountError as exc:
                print(f"Could not add account: {exc}")
            else:
                print(
                    f"Added and selected {account.profile} ({account.email or account.account_id})."
                )
                _restart_notice()
        elif action in {"r", "refresh", "usage"}:
            for profile, error in refresh_all_usage().items():
                if error:
                    print(f"{profile}: {error}")
        elif action in {"f", "forget", "remove"}:
            account = _choose_account(accounts)
            if account is not None:
                try:
                    forget_account(account.profile)
                except CodexAccountError as exc:
                    print(f"Could not forget account: {exc}")
        else:
            print("Unknown action. Use S, A, D, R, F, or Q.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``fcc accounts`` interactively or as a small command surface."""

    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _interactive()
    command, *rest = args
    try:
        if command in {"list", "ls"}:
            _print_accounts(list_accounts())
        elif command in {"refresh", "usage"}:
            if not rest or rest == ["--all"]:
                for profile, error in refresh_all_usage().items():
                    print(f"{profile}: {error or 'refreshed'}")
            else:
                refresh_usage(rest[0])
                _print_accounts(list_accounts())
        elif command in {"switch", "select", "use"} and len(rest) == 1:
            account = select_account(rest[0])
            print(
                f"Selected {account.profile} ({account.email or account.account_id})."
            )
            _restart_notice()
        elif command in {"add", "signup", "sign-up"}:
            device = "--device-auth" in rest
            names = [value for value in rest if value != "--device-auth"]
            if len(names) != 1:
                raise CodexAccountError(
                    "Usage: fcc accounts add <profile> [--device-auth]"
                )
            print("Official Codex login can sign in or create a new tool account.")
            account = add_account(names[0], device_auth=device)
            print(
                f"Added and selected {account.profile} ({account.email or account.account_id})."
            )
            _restart_notice()
        elif command in {"forget", "remove", "rm"} and len(rest) == 1:
            forget_account(rest[0])
            print(f"Forgot local account snapshot: {rest[0]}")
        elif command in {"help", "--help", "-h"}:
            print(
                "Usage: fcc accounts [list|refresh|switch|add|forget]\n"
                "  add <profile> [--device-auth] uses the official Codex sign-in flow"
            )
        else:
            raise CodexAccountError(f"Invalid accounts command: {' '.join(args)}")
    except CodexAccountError as exc:
        print(f"fcc accounts: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
