"""Manage multiple ChatGPT-authenticated Codex subscriptions safely.

The active Codex CLI credential remains ``$CODEX_HOME/auth.json``.  Saved
profiles mirror the small, proven layout used by Fasand/codex-auth (MIT,
7fd9b5325d5093631e76abdc963fee43d5efedb5): each profile owns an exact
``auth.json`` snapshot plus credential-free metadata and cached usage.

Switching never calls ``codex logout`` or ``codex login``.  The outgoing live
auth file is snapshotted first, then the selected snapshot is atomically
installed.  Adding an account temporarily stashes the live auth file before
invoking the official Codex login flow so that logging into a second account
cannot revoke the first account's refresh grant.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from free_claude_code.core.interprocess_lock import InterprocessFileLock

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
    """Credential-free account snapshot safe for terminal display."""

    profile: str
    account_id: str
    email: str | None
    active: bool
    plan: str | None
    usage: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class _AuthIdentity:
    account_id: str
    email: str | None


def codex_home() -> Path:
    """Return the Codex CLI home used by the installed subscription runtime."""

    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def auth_path(home: Path | None = None) -> Path:
    return (home or codex_home()) / "auth.json"


def accounts_root(home: Path | None = None) -> Path:
    return (home or codex_home()) / "accounts"


def profiles_dir(home: Path | None = None) -> Path:
    return accounts_root(home) / "profiles"


def current_profile_path(home: Path | None = None) -> Path:
    return accounts_root(home) / "current_profile"


def account_lock_path(home: Path | None = None) -> Path:
    return accounts_root(home) / "fcc-accounts.lock"


def profile_dir(profile: str, home: Path | None = None) -> Path:
    _validate_profile_name(profile)
    return profiles_dir(home) / profile


def profile_auth_path(profile: str, home: Path | None = None) -> Path:
    return profile_dir(profile, home) / "auth.json"


def profile_meta_path(profile: str, home: Path | None = None) -> Path:
    return profile_dir(profile, home) / "meta.json"


def profile_usage_path(profile: str, home: Path | None = None) -> Path:
    return profile_dir(profile, home) / "usage.json"


def list_accounts(*, home: Path | None = None) -> tuple[CodexAccount, ...]:
    """Return saved subscriptions, importing/syncing the live account first."""

    root = home or codex_home()
    with _account_lock(root):
        _sync_active_unlocked(root)
        active_identity = _try_read_identity(auth_path(root))
        accounts: list[CodexAccount] = []
        directory = profiles_dir(root)
        if not directory.is_dir():
            return ()
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            if not candidate.is_dir() or not _PROFILE_RE.fullmatch(candidate.name):
                continue
            try:
                identity = _read_identity(candidate / "auth.json")
            except CodexAccountError:
                continue
            usage = _read_json_optional(candidate / "usage.json")
            plan = _string(usage, "plan_type") if usage is not None else None
            accounts.append(
                CodexAccount(
                    profile=candidate.name,
                    account_id=identity.account_id,
                    email=identity.email,
                    active=(
                        active_identity is not None
                        and active_identity.account_id == identity.account_id
                    ),
                    plan=plan,
                    usage=usage,
                )
            )
    return tuple(sorted(accounts, key=lambda account: (not account.active, account.profile.casefold())))


def select_account(profile: str, *, home: Path | None = None) -> CodexAccount:
    """Select one saved subscription without invoking Codex login/logout."""

    root = home or codex_home()
    _validate_profile_name(profile)
    with _account_lock(root):
        _sync_active_unlocked(root)
        source = profile_auth_path(profile, root)
        if not source.is_file():
            raise CodexAccountError(f"Unknown Codex account profile: {profile}")
        identity = _read_identity(source)
        _atomic_write(auth_path(root), source.read_bytes(), mode=0o600)
        _write_current_profile(root, profile)
        usage = _read_json_optional(profile_usage_path(profile, root))
        return CodexAccount(
            profile=profile,
            account_id=identity.account_id,
            email=identity.email,
            active=True,
            plan=_string(usage, "plan_type") if usage is not None else None,
            usage=usage,
        )


def add_account(
    profile: str,
    *,
    device_auth: bool = False,
    home: Path | None = None,
    executable: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> CodexAccount:
    """Run official Codex login after safely stashing the currently live auth."""

    _validate_profile_name(profile)
    root = home or codex_home()
    codex = executable or shutil.which("codex")
    if codex is None:
        raise CodexAccountError("Codex CLI was not found on PATH.")

    stash = root / f".fcc-auth-stash-{uuid.uuid4().hex}.json"
    previous_marker = _read_current_profile(root)
    with _account_lock(root):
        _sync_active_unlocked(root)
        destination = profile_dir(profile, root)
        if destination.exists():
            raise CodexAccountError(f"Codex account profile already exists: {profile}")
        live = auth_path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _chmod_private_dir(root)
        if live.exists():
            os.replace(live, stash)
            _chmod_private_file(stash)

    argv = [codex, "login"]
    if device_auth:
        argv.append("--device-auth")
    environment = _codex_subscription_environment()
    try:
        result = runner(argv, env=environment, check=False)
    except Exception as exc:
        _restore_stashed_auth(root, stash, previous_marker)
        raise CodexAccountError(f"Could not start Codex login ({type(exc).__name__}).") from exc

    if result.returncode != 0:
        _restore_stashed_auth(root, stash, previous_marker)
        raise CodexAccountError(f"Codex login exited with status {result.returncode}.")

    with _account_lock(root):
        live = auth_path(root)
        try:
            identity = _read_identity(live)
        except CodexAccountError:
            live.unlink(missing_ok=True)
            if stash.is_file():
                os.replace(stash, live)
                _chmod_private_file(live)
            _restore_current_profile_marker(root, previous_marker)
            raise

        existing = _profile_for_account_unlocked(root, identity.account_id)
        target_profile = existing or profile
        _save_auth_profile_unlocked(root, target_profile, live, identity)
        _write_current_profile(root, target_profile)
        stash.unlink(missing_ok=True)
        usage = _read_json_optional(profile_usage_path(target_profile, root))
        return CodexAccount(
            profile=target_profile,
            account_id=identity.account_id,
            email=identity.email,
            active=True,
            plan=_string(usage, "plan_type") if usage is not None else None,
            usage=usage,
        )


def forget_account(profile: str, *, home: Path | None = None) -> None:
    """Delete one saved snapshot without revoking or logging out upstream."""

    root = home or codex_home()
    _validate_profile_name(profile)
    with _account_lock(root):
        _sync_active_unlocked(root)
        target = profile_dir(profile, root)
        if not target.is_dir():
            raise CodexAccountError(f"Unknown Codex account profile: {profile}")
        target_identity = _read_identity(target / "auth.json")
        active_identity = _try_read_identity(auth_path(root))
        if (
            active_identity is not None
            and active_identity.account_id == target_identity.account_id
        ):
            raise CodexAccountError(
                "Cannot forget the active Codex account. Select another account first."
            )
        shutil.rmtree(target)
        if _read_current_profile(root) == profile:
            current_profile_path(root).unlink(missing_ok=True)


def refresh_usage(
    profile: str,
    *,
    home: Path | None = None,
    opener: Callable[..., Any] = urlopen,
) -> Mapping[str, Any]:
    """Refresh plan/rate-limit data for one saved account without switching it."""

    root = home or codex_home()
    _validate_profile_name(profile)
    with _account_lock(root):
        _sync_active_unlocked(root)
        source = profile_auth_path(profile, root)
        auth = _read_auth(source)

    tokens = auth.get("tokens")
    if not isinstance(tokens, Mapping):
        raise CodexAccountError("Codex auth snapshot is missing tokens.")
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not isinstance(access_token, str) or not access_token:
        raise CodexAccountError("Codex auth snapshot is missing an access token.")
    if not isinstance(account_id, str) or not account_id:
        raise CodexAccountError("Codex auth snapshot is missing an account id.")

    last_error: str | None = None
    for index, endpoint in enumerate((DEFAULT_USAGE_URL, FALLBACK_USAGE_URL)):
        try:
            payload = _fetch_usage_payload(
                endpoint,
                access_token=access_token,
                account_id=account_id,
                opener=opener,
            )
        except CodexAccountError as exc:
            last_error = str(exc)
            continue
        normalized = _normalize_usage(
            payload,
            endpoint="primary" if index == 0 else "fallback",
        )
        with _account_lock(root):
            _atomic_write_json(profile_usage_path(profile, root), normalized)
        return normalized
    raise CodexAccountError(last_error or "Could not refresh Codex usage limits.")


def refresh_all_usage(*, home: Path | None = None) -> dict[str, str | None]:
    """Refresh every saved profile and return safe per-profile error summaries."""

    outcomes: dict[str, str | None] = {}
    for account in list_accounts(home=home):
        try:
            refresh_usage(account.profile, home=home)
        except CodexAccountError as exc:
            outcomes[account.profile] = str(exc)
        else:
            outcomes[account.profile] = None
    return outcomes


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone ``fcc accounts`` command."""

    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _interactive_menu()
    command = args.pop(0).casefold()
    try:
        if command in {"list", "ls"}:
            _print_accounts(list_accounts())
            return 0
        if command in {"refresh", "usage"}:
            if not args or args[0] == "--all":
                outcomes = refresh_all_usage()
                for profile, error in outcomes.items():
                    print(f"{profile}: {error or 'refreshed'}")
            else:
                refresh_usage(args[0])
                _print_accounts(list_accounts())
            return 0
        if command in {"switch", "select", "use"}:
            if len(args) != 1:
                raise CodexAccountError("Usage: fcc accounts switch <profile>")
            account = select_account(args[0])
            print(f"Selected {account.profile} ({account.email or account.account_id}).")
            _print_restart_notice()
            return 0
        if command in {"add", "signup", "sign-up"}:
            device = "--device-auth" in args
            names = [arg for arg in args if arg != "--device-auth"]
            if len(names) != 1:
                raise CodexAccountError(
                    "Usage: fcc accounts add <profile> [--device-auth]"
                )
            print(
                "Opening the official Codex ChatGPT sign-in. The browser page can "
                "also create a new ChatGPT account."
            )
            account = add_account(names[0], device_auth=device)
            print(f"Added and selected {account.profile} ({account.email or account.account_id}).")
            _print_restart_notice()
            return 0
        if command in {"forget", "remove", "rm"}:
            if len(args) != 1:
                raise CodexAccountError("Usage: fcc accounts forget <profile>")
            forget_account(args[0])
            print(f"Forgot local account snapshot: {args[0]}")
            return 0
        if command in {"--help", "-h", "help"}:
            _print_help()
            return 0
        raise CodexAccountError(f"Unknown accounts command: {command}")
    except CodexAccountError as exc:
        print(f"fcc accounts: {exc}", file=sys.stderr)
        return 1


def _interactive_menu() -> int:
    while True:
        try:
            accounts = list_accounts()
        except CodexAccountError as exc:
            print(f"ChatGPT accounts unavailable: {exc}")
            accounts = ()
        print()
        print("ChatGPT / Codex subscriptions")
        print("-----------------------------")
        _print_accounts(accounts)
        print("[S] Select   [A] Add / sign up   [D] Device add")
        print("[R] Refresh limits   [F] Forget   [Q] Quit")
        try:
            choice = input("Accounts> ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in {"q", "quit", "b", "back"}:
            return 0
        if choice in {"s", "select", "use"}:
            selected = _choose_account(accounts)
            if selected is None:
                continue
            try:
                account = select_account(selected.profile)
            except CodexAccountError as exc:
                print(f"Could not select account: {exc}")
            else:
                print(f"Selected {account.profile} ({account.email or account.account_id}).")
                _print_restart_notice()
            continue
        if choice in {"a", "add", "signup", "sign-up", "d", "device"}:
            try:
                name = input("Profile name (letters/numbers/._-)> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            if not name:
                print("No account added.")
                continue
            print(
                "The official Codex login page can sign in or create a new "
                "ChatGPT account."
            )
            try:
                account = add_account(name, device_auth=choice in {"d", "device"})
            except CodexAccountError as exc:
                print(f"Could not add account: {exc}")
            else:
                print(f"Added and selected {account.profile} ({account.email or account.account_id}).")
                _print_restart_notice()
            continue
        if choice in {"r", "refresh", "usage"}:
            if not accounts:
                print("No saved accounts to refresh.")
                continue
            print("Refreshing subscription limits...")
            outcomes = refresh_all_usage()
            for profile, error in outcomes.items():
                if error:
                    print(f"  {profile}: {error}")
            continue
        if choice in {"f", "forget", "remove"}:
            selected = _choose_account(accounts)
            if selected is None:
                continue
            try:
                forget_account(selected.profile)
            except CodexAccountError as exc:
                print(f"Could not forget account: {exc}")
            else:
                print(f"Forgot local snapshot: {selected.profile}")
            continue
        print("Unknown account action. Use S, A, D, R, F, or Q.")


def _choose_account(accounts: Sequence[CodexAccount]) -> CodexAccount | None:
    if not accounts:
        print("No saved ChatGPT/Codex subscriptions are available.")
        return None
    items = [
        SelectionItem(
            item_id=account.profile,
            label=account.email or account.profile,
            detail=_account_detail(account),
        )
        for account in accounts
    ]
    selected = choose_item(
        items,
        title="ChatGPT / Codex subscriptions",
        footer="type filter · ↑↓ move · enter select · esc cancel",
    )
    if selected is None:
        return None
    return next(
        (account for account in accounts if account.profile == selected.item_id),
        None,
    )


def _print_accounts(accounts: Sequence[CodexAccount]) -> None:
    if not accounts:
        print("No saved ChatGPT/Codex subscriptions.")
        return
    for account in accounts:
        marker = ">" if account.active else " "
        identity = account.email or account.profile
        plan = f"  {account.plan}" if account.plan else ""
        print(f"{marker} {account.profile:<18} {identity}{plan}")
        for line in _usage_lines(account.usage):
            print(f"    {line}")


def _account_detail(account: CodexAccount) -> str:
    parts = [account.plan or "plan unknown"]
    parts.extend(_usage_lines(account.usage, compact=True))
    if account.active:
        parts.append("active")
    return " · ".join(parts)


def _usage_lines(
    usage: Mapping[str, Any] | None,
    *,
    compact: bool = False,
) -> list[str]:
    if not usage:
        return ["limits not refreshed"]
    approximate = usage.get("approximate") is True
    prefix = "~" if approximate else ""
    lines: list[str] = []
    windows = usage.get("windows")
    if isinstance(windows, list):
        for window in windows:
            if not isinstance(window, Mapping):
                continue
            label = str(window.get("label") or window.get("id") or "limit")
            remaining = window.get("remaining_percent")
            used = window.get("used_percent")
            reset_at = _format_reset(window.get("reset_at"))
            if remaining is not None:
                text = f"{label} {prefix}{_percent(remaining)} left"
            elif used is not None:
                text = f"{label} {prefix}{_percent(used)} used"
            else:
                continue
            if reset_at:
                text += f" (resets {reset_at})"
            lines.append(text)
    additional = usage.get("additional_limits")
    if isinstance(additional, list):
        for item in additional:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "additional")
            remaining = item.get("remaining_percent")
            if remaining is not None:
                lines.append(f"{name} {prefix}{_percent(remaining)} left")
    credits = usage.get("credits")
    if isinstance(credits, Mapping):
        if credits.get("unlimited") is True:
            lines.append("credits unlimited")
        elif credits.get("balance") not in {None, "", 0, "0"}:
            lines.append(f"credits {credits['balance']}")
    if compact and len(lines) > 2:
        return lines[:2]
    return lines or ["limits unavailable"]


def _fetch_usage_payload(
    endpoint: str,
    *,
    access_token: str,
    account_id: str,
    opener: Callable[..., Any],
) -> Mapping[str, Any]:
    request = Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": account_id,
            "Accept": "application/json",
            "User-Agent": "free-claude-code/subscription-accounts",
        },
    )
    try:
        with opener(request, timeout=USAGE_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except HTTPError as exc:
        if exc.code == 401:
            raise CodexAccountError(
                "ChatGPT session expired; add/sign in to this account again."
            ) from exc
        raise CodexAccountError(f"Usage endpoint returned HTTP {exc.code}.") from exc
    except (URLError, OSError) as exc:
        raise CodexAccountError(f"Usage refresh failed ({type(exc).__name__}).") from exc
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexAccountError("Usage endpoint returned invalid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise CodexAccountError("Usage endpoint returned an invalid payload.")
    return payload


def _normalize_usage(payload: Mapping[str, Any], *, endpoint: str) -> dict[str, Any]:
    rate = payload.get("rate_limit")
    rate = rate if isinstance(rate, Mapping) else {}
    windows: list[dict[str, Any]] = []
    for window_id, key in (("primary", "primary_window"), ("secondary", "secondary_window")):
        raw_window = rate.get(key)
        if not isinstance(raw_window, Mapping):
            continue
        used = _number(raw_window.get("used_percent"))
        seconds = _integer(raw_window.get("limit_window_seconds"))
        window: dict[str, Any] = {
            "id": window_id,
            "label": _window_label(seconds),
            "used_percent": used,
            "remaining_percent": None if used is None else max(0.0, 100.0 - used),
            "window_seconds": seconds,
            "reset_at": _integer(raw_window.get("reset_at")),
            "reset_after_seconds": _integer(raw_window.get("reset_after_seconds")),
        }
        windows.append(window)

    additional_limits: list[dict[str, Any]] = []
    raw_additional = payload.get("additional_rate_limits")
    if isinstance(raw_additional, list):
        for item in raw_additional:
            if not isinstance(item, Mapping):
                continue
            inner = item.get("rate_limit")
            inner = inner if isinstance(inner, Mapping) else {}
            primary = inner.get("primary_window")
            if not isinstance(primary, Mapping):
                continue
            used = _number(primary.get("used_percent"))
            additional_limits.append(
                {
                    "name": str(
                        item.get("limit_name")
                        or item.get("metered_feature")
                        or "additional"
                    ),
                    "used_percent": used,
                    "remaining_percent": (
                        None if used is None else max(0.0, 100.0 - used)
                    ),
                    "window_seconds": _integer(primary.get("limit_window_seconds")),
                    "reset_at": _integer(primary.get("reset_at")),
                }
            )

    credits_raw = payload.get("credits")
    credits: dict[str, Any] = {}
    if isinstance(credits_raw, Mapping):
        for key in ("balance", "has_credits", "unlimited"):
            if key in credits_raw:
                credits[key] = credits_raw[key]

    return {
        "version": 1,
        "fetched_at": int(time.time()),
        "endpoint": endpoint,
        "approximate": endpoint != "primary",
        "plan_type": payload.get("plan_type") if isinstance(payload.get("plan_type"), str) else None,
        "windows": windows,
        "additional_limits": additional_limits,
        "credits": credits,
    }


def _sync_active_unlocked(root: Path) -> str | None:
    live = auth_path(root)
    if not live.is_file():
        return None
    identity = _read_identity(live)
    existing = _profile_for_account_unlocked(root, identity.account_id)
    marker = _read_current_profile(root)
    if existing is not None:
        profile = existing
    elif marker is not None and not profile_dir(marker, root).exists():
        profile = marker
    else:
        profile = _derive_profile_name_unlocked(root, identity)
    _save_auth_profile_unlocked(root, profile, live, identity)
    _write_current_profile(root, profile)
    return profile


def _save_auth_profile_unlocked(
    root: Path,
    profile: str,
    source: Path,
    identity: _AuthIdentity,
) -> None:
    destination = profile_dir(profile, root)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_private_dir(destination)
    _atomic_write(destination / "auth.json", source.read_bytes(), mode=0o600)
    payload = _read_auth(source)
    tokens = payload.get("tokens")
    tokens = tokens if isinstance(tokens, Mapping) else {}
    id_claims = _jwt_claims(tokens.get("id_token"))
    access_claims = _jwt_claims(tokens.get("access_token"))
    _atomic_write_json(
        destination / "meta.json",
        {
            "profileName": profile,
            "savedAt": int(time.time()),
            "email": identity.email,
            "accountId": identity.account_id,
            "lastRefresh": payload.get("last_refresh"),
            "idTokenExpiresEpoch": _integer(id_claims.get("exp")),
            "accessTokenExpiresEpoch": _integer(access_claims.get("exp")),
            "hasRefreshToken": bool(tokens.get("refresh_token")),
        },
    )


def _profile_for_account_unlocked(root: Path, account_id: str) -> str | None:
    directory = profiles_dir(root)
    if not directory.is_dir():
        return None
    for candidate in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if not candidate.is_dir() or not _PROFILE_RE.fullmatch(candidate.name):
            continue
        identity = _try_read_identity(candidate / "auth.json")
        if identity is not None and identity.account_id == account_id:
            return candidate.name
    return None


def _derive_profile_name_unlocked(root: Path, identity: _AuthIdentity) -> str:
    source = identity.email.split("@", 1)[0] if identity.email else "account"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", source).strip(".-_") or "account"
    if not profile_dir(base, root).exists():
        return base
    suffix = identity.account_id.replace("-", "")[-8:] or uuid.uuid4().hex[:8]
    candidate = f"{base}-{suffix}"
    counter = 2
    while profile_dir(candidate, root).exists():
        candidate = f"{base}-{suffix}-{counter}"
        counter += 1
    return candidate


def _restore_stashed_auth(root: Path, stash: Path, marker: str | None) -> None:
    with _account_lock(root):
        live = auth_path(root)
        live.unlink(missing_ok=True)
        if stash.is_file():
            os.replace(stash, live)
            _chmod_private_file(live)
        _restore_current_profile_marker(root, marker)


def _restore_current_profile_marker(root: Path, marker: str | None) -> None:
    if marker:
        _write_current_profile(root, marker)
    else:
        current_profile_path(root).unlink(missing_ok=True)


def _read_auth(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CodexAccountError(f"Codex ChatGPT auth was not found at {path}.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexAccountError("Codex ChatGPT auth file is invalid.") from exc
    if not isinstance(payload, Mapping):
        raise CodexAccountError("Codex ChatGPT auth file must contain a JSON object.")
    tokens = payload.get("tokens")
    if not isinstance(tokens, Mapping):
        raise CodexAccountError(
            "Codex is not using ChatGPT subscription auth (token bundle missing)."
        )
    return payload


def _read_identity(path: Path) -> _AuthIdentity:
    payload = _read_auth(path)
    tokens = payload["tokens"]
    assert isinstance(tokens, Mapping)
    account_id = tokens.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise CodexAccountError("Codex ChatGPT auth is missing an account id.")
    id_claims = _jwt_claims(tokens.get("id_token"))
    access_claims = _jwt_claims(tokens.get("access_token"))
    email = _claim_string(id_claims, "email") or _claim_string(access_claims, "email")
    return _AuthIdentity(account_id=account_id, email=email)


def _try_read_identity(path: Path) -> _AuthIdentity | None:
    try:
        return _read_identity(path)
    except CodexAccountError:
        return None


def _jwt_claims(token: Any) -> Mapping[str, Any]:
    if not isinstance(token, str):
        return {}
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return {}
    encoded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _claim_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _codex_subscription_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in _CODEX_API_ENV_KEYS:
        environment.pop(key, None)
    return environment


def _validate_profile_name(profile: str) -> None:
    if not profile or not _PROFILE_RE.fullmatch(profile):
        raise CodexAccountError(
            "Profile names may contain only letters, numbers, dot, underscore, and hyphen."
        )


def _account_lock(root: Path) -> InterprocessFileLock:
    lock = InterprocessFileLock(account_lock_path(root))
    if not lock.acquire(wait=True, timeout=ACCOUNT_LOCK_TIMEOUT_SECONDS):
        raise CodexAccountError("Timed out waiting for the Codex account lock.")
    return lock


def _atomic_write(path: Path, content: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_private_dir(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        if os.name != "nt":
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, mode)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(
        path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        mode=0o600,
    )


def _write_current_profile(root: Path, profile: str) -> None:
    _atomic_write(current_profile_path(root), f"{profile}\n".encode(), mode=0o600)


def _read_current_profile(root: Path) -> str | None:
    try:
        value = current_profile_path(root).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if value and _PROFILE_RE.fullmatch(value) else None


def _read_json_optional(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _chmod_private_dir(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700)


def _chmod_private_file(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o600)


def _window_label(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return "limit"
    if seconds % 604800 == 0:
        weeks = seconds // 604800
        return "weekly" if weeks == 1 else f"{weeks}w"
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    hours = seconds / 3600
    return f"{hours:g}h"


def _format_reset(value: Any) -> str:
    timestamp = _integer(value)
    if timestamp is None:
        return ""
    try:
        return datetime.fromtimestamp(timestamp).astimezone().strftime("%b %d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _percent(value: Any) -> str:
    number = _number(value)
    return f"{int(round(number))}%" if number is not None else "?"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _string(payload: Mapping[str, Any] | None, key: str) -> str | None:
    if payload is None:
        return None
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _print_restart_notice() -> None:
    print(
        "Account selection applies to new Codex/helper sessions. Restart FCC or "
        "start a fresh Harness session before using the newly selected subscription."
    )


def _print_help() -> None:
    print(
        "Usage: fcc accounts [command]\n\n"
        "Commands:\n"
        "  list                         List saved ChatGPT/Codex subscriptions\n"
        "  refresh [profile|--all]      Refresh plan and rate-limit windows\n"
        "  switch <profile>             Select subscription without login/logout\n"
        "  add <profile> [--device-auth]  Official sign-in / account creation flow\n"
        "  forget <profile>             Delete a non-active local snapshot\n"
        "\nWithout a command, an interactive account picker is opened."
    )


if __name__ == "__main__":
    raise SystemExit(main())
