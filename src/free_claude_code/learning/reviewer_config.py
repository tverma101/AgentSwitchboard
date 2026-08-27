"""Profile-isolated preferences for bounded reviewer pack selection."""

import json
import os
from contextlib import suppress
from pathlib import Path

from .config import profile_home
from .reviewer_scars import ReviewerPack, ReviewerScarError

PACK_SETTINGS_SCHEMA = "fcc.reviewer-pack-settings.v1"
MAX_PACK_SETTINGS_BYTES = 8 * 1024


class ReviewerPackSettings:
    """Persist explicit pack overrides without changing the shared defaults."""

    def __init__(self, profile: str | None = None) -> None:
        self._root = profile_home(profile)
        self._path = self._root / "reviewer-packs.json"

    @property
    def path(self) -> Path:
        return self._path

    def overrides(self) -> dict[ReviewerPack, bool]:
        """Return explicit per-profile overrides; absent packs remain automatic."""

        if self._path.is_symlink():
            raise ReviewerScarError("reviewer pack settings must not be a symlink")
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise ReviewerScarError("cannot read reviewer pack settings") from exc
        if len(raw.encode("utf-8")) > MAX_PACK_SETTINGS_BYTES:
            raise ReviewerScarError("reviewer pack settings exceed their size bound")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReviewerScarError("reviewer pack settings are invalid JSON") from exc
        if not isinstance(value, dict) or set(value) != {"schema", "overrides"}:
            raise ReviewerScarError("reviewer pack settings schema is invalid")
        if value.get("schema") != PACK_SETTINGS_SCHEMA:
            raise ReviewerScarError("reviewer pack settings schema is invalid")
        raw_overrides = value.get("overrides")
        if not isinstance(raw_overrides, dict):
            raise ReviewerScarError("reviewer pack overrides must be an object")
        overrides: dict[ReviewerPack, bool] = {}
        for raw_pack, enabled in raw_overrides.items():
            try:
                pack = ReviewerPack(raw_pack)
            except ValueError as exc:
                raise ReviewerScarError("reviewer pack override is unknown") from exc
            if not isinstance(enabled, bool):
                raise ReviewerScarError("reviewer pack override must be boolean")
            overrides[pack] = enabled
        return overrides

    def set_override(
        self, pack: ReviewerPack, enabled: bool
    ) -> dict[ReviewerPack, bool]:
        """Set one explicit override and return the resulting override map."""

        overrides = self.overrides()
        overrides[pack] = enabled
        self._write(overrides)
        return overrides

    def _write(self, overrides: dict[ReviewerPack, bool]) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._path.is_symlink():
            raise ReviewerScarError("reviewer pack settings must not be a symlink")
        payload = {
            "schema": PACK_SETTINGS_SCHEMA,
            "overrides": {
                pack.value: overrides[pack]
                for pack in sorted(overrides, key=lambda item: item.value)
            },
        }
        encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_PACK_SETTINGS_BYTES:
            raise ReviewerScarError("reviewer pack settings exceed their size bound")
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            os.chmod(self._path, 0o600)
        except OSError as exc:
            raise ReviewerScarError("cannot write reviewer pack settings") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                temporary.unlink()


__all__ = [
    "MAX_PACK_SETTINGS_BYTES",
    "PACK_SETTINGS_SCHEMA",
    "ReviewerPackSettings",
]
