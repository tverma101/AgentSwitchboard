"""Provider-independent local Appshot contracts and queue boundaries.

This module deliberately stops at a local attachment boundary.  It does not
choose a model, inject terminal input, or provide a computer-use runtime.
"""

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .visual_attachments import (
    MAX_IMAGE_BYTES,
    VisualAttachmentReceipt,
    validate_image_bytes,
)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SESSION_SOURCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,32}$")
_MAX_APP_NAME_CHARS = 128
_MAX_BUNDLE_ID_CHARS = 256
_MAX_WINDOW_TITLE_CHARS = 512
_MAX_ACCESSIBILITY_CHARS = 4096

_DEFAULT_SENSITIVE_MARKERS = (
    "1password",
    "authenticator",
    "banking",
    "bitwarden",
    "dashlane",
    "keychain access",
    "keeper",
    "lastpass",
    "password",
    "payment",
    "wallet",
)


class AppshotContractError(ValueError):
    """An Appshot cannot cross the local attachment boundary safely."""


class SensitiveAppshotError(AppshotContractError):
    """The focused app/window is denied by the local privacy policy."""


def _clean_text(value: object, *, fallback: str, limit: int) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.replace("\x00", " ").split())
    return cleaned[:limit] or fallback


def _optional_text(value: object, *, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.replace("\x00", " ").split())
    return cleaned[:limit] or None


def _positive_dimension(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _required_int(value: object, *, field_name: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise AppshotContractError(f"invalid Appshot receipt {field_name}")


@dataclass(frozen=True, slots=True)
class TerminalSessionAssociation:
    """An explicit opaque terminal-session target for one Appshot."""

    session_id: str
    source: str = "explicit"

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not _SESSION_ID_RE.fullmatch(
            self.session_id
        ):
            raise AppshotContractError("session_id must be a short opaque identifier")
        if not isinstance(self.source, str) or not _SESSION_SOURCE_RE.fullmatch(
            self.source
        ):
            raise AppshotContractError("session source must be a short identifier")

    @classmethod
    def explicit(cls, session_id: str) -> TerminalSessionAssociation:
        return cls(session_id=session_id, source="explicit")

    @classmethod
    def environment(cls, session_id: str) -> TerminalSessionAssociation:
        return cls(session_id=session_id, source="environment")

    def as_dict(self) -> dict[str, str]:
        return {"session_id": self.session_id, "source": self.source}


@dataclass(frozen=True, slots=True)
class FocusedWindowMetadata:
    """Sanitized identity and optional bounded semantics for one focused window."""

    app_name: str
    window_title: str = ""
    bundle_id: str | None = None
    width: int | None = None
    height: int | None = None
    accessibility_summary: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "app_name",
            _clean_text(
                self.app_name,
                fallback="Unknown app",
                limit=_MAX_APP_NAME_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "window_title",
            _clean_text(
                self.window_title,
                fallback="",
                limit=_MAX_WINDOW_TITLE_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "bundle_id",
            _optional_text(self.bundle_id, limit=_MAX_BUNDLE_ID_CHARS),
        )
        object.__setattr__(self, "width", _positive_dimension(self.width))
        object.__setattr__(self, "height", _positive_dimension(self.height))
        object.__setattr__(
            self,
            "accessibility_summary",
            _optional_text(self.accessibility_summary, limit=_MAX_ACCESSIBILITY_CHARS),
        )

    @classmethod
    def from_mapping(cls, metadata: Mapping[str, object]) -> FocusedWindowMetadata:
        """Build metadata from an OS adapter without trusting its raw strings."""
        app_name = metadata.get("app", metadata.get("app_name", "Unknown app"))
        window_title = metadata.get("window", metadata.get("window_title", ""))
        bundle_id = metadata.get("bundle_id", metadata.get("bundle_identifier"))
        accessibility_summary = metadata.get(
            "accessibility_summary", metadata.get("ax_summary")
        )
        return cls(
            app_name=app_name if isinstance(app_name, str) else "Unknown app",
            window_title=window_title if isinstance(window_title, str) else "",
            bundle_id=bundle_id if isinstance(bundle_id, str) else None,
            width=_positive_dimension(metadata.get("width")),
            height=_positive_dimension(metadata.get("height")),
            accessibility_summary=(
                accessibility_summary
                if isinstance(accessibility_summary, str)
                else None
            ),
        )

    def with_dimensions(self, width: int, height: int) -> FocusedWindowMetadata:
        return replace(
            self,
            width=self.width or width,
            height=self.height or height,
        )

    @property
    def display_title(self) -> str:
        return (
            f"{self.app_name} — {self.window_title}"
            if self.window_title
            else self.app_name
        )

    def as_receipt_dict(self) -> dict[str, object]:
        """Return metadata safe for a persisted receipt or normal log."""
        data: dict[str, object] = {
            "app": self.app_name,
            "window": self.window_title,
        }
        if self.bundle_id:
            data["bundle_id"] = self.bundle_id
        if self.width is not None and self.height is not None:
            data["width"] = self.width
            data["height"] = self.height
        if self.accessibility_summary:
            data["accessibility_summary"] = {
                "present": True,
                "chars": len(self.accessibility_summary),
                "sha256": hashlib.sha256(
                    self.accessibility_summary.encode("utf-8")
                ).hexdigest()[:16],
            }
        return data

    def as_payload_dict(self) -> dict[str, object]:
        """Return bounded metadata for an explicit in-process attachment."""
        data = self.as_receipt_dict()
        if self.accessibility_summary:
            data["accessibility_summary"] = self.accessibility_summary
        return data


class FocusedWindowCapturePort(Protocol):
    """Two-phase source that can deny a window before reading its pixels."""

    def inspect_focused_window(self) -> FocusedWindowMetadata:
        """Return the current focused-window identity and bounded metadata."""

    def capture_focused_window(self, window: FocusedWindowMetadata) -> bytes:
        """Capture the inspected window, or fail without persisting bytes."""


@dataclass(frozen=True, slots=True)
class SensitiveAppPolicy:
    """Conservative deny-by-default markers with an injectable test seam."""

    markers: tuple[str, ...] = _DEFAULT_SENSITIVE_MARKERS

    def matched_marker(self, window: FocusedWindowMetadata) -> str | None:
        haystack = " ".join(
            (window.app_name, window.bundle_id or "", window.window_title)
        ).casefold()
        for marker in self.markers:
            normalized = marker.strip().casefold()
            if normalized and normalized in haystack:
                return normalized
        return None

    def ensure_allowed(self, window: FocusedWindowMetadata) -> None:
        if self.matched_marker(window) is not None:
            raise SensitiveAppshotError("Appshot denied by sensitive-app policy")


@dataclass(frozen=True, slots=True)
class AppshotPolicy:
    """Local admission policy; queue persistence is intentionally separate."""

    max_bytes: int = MAX_IMAGE_BYTES
    label: str = "appshot"
    sensitive_apps: SensitiveAppPolicy = field(default_factory=SensitiveAppPolicy)

    def __post_init__(self) -> None:
        if not 1 <= self.max_bytes <= MAX_IMAGE_BYTES:
            raise AppshotContractError(
                f"max_bytes must be between 1 and {MAX_IMAGE_BYTES}"
            )
        object.__setattr__(
            self,
            "label",
            _clean_text(self.label, fallback="appshot", limit=64),
        )


@dataclass(frozen=True, slots=True)
class AppshotAttachment:
    """In-process attachment; ``image_bytes`` is never included in ``as_dict``."""

    association: TerminalSessionAssociation
    metadata: FocusedWindowMetadata
    visual: VisualAttachmentReceipt
    image_bytes: bytes
    content_hash: str
    captured_at: str
    capture_latency_ms: float
    image_path: Path | None = None

    @property
    def session_id(self) -> str:
        return self.association.session_id

    @property
    def app(self) -> str:
        return self.metadata.app_name

    @property
    def window(self) -> str:
        return self.metadata.window_title

    def confirmation(self) -> str:
        return (
            f"[appshot: {self.metadata.display_title} · "
            f"{self.visual.width}\u00d7{self.visual.height}]"
        )

    def as_dict(self) -> dict[str, object]:
        """Return a redacted diagnostic view with no bytes or absolute paths."""
        return {
            "session": self.association.as_dict(),
            "app": self.metadata.app_name,
            "window": self.metadata.window_title,
            "visual": self.visual.as_dict(),
            "content_hash": self.content_hash,
            "captured_at": self.captured_at,
            "capture_latency_ms": self.capture_latency_ms,
        }

    def payload(self) -> dict[str, object]:
        """Return the explicit local payload a session consumer may attach."""
        return {
            "session": self.association.as_dict(),
            "window": self.metadata.as_payload_dict(),
            "visual": self.visual.as_dict(),
            "image_bytes": self.image_bytes,
        }

    def receipt(
        self,
        *,
        persisted: bool,
        asset_name: str | None,
        deduplicated: bool = False,
    ) -> AppshotReceipt:
        return AppshotReceipt(
            association=self.association,
            metadata=self.metadata,
            visual=self.visual,
            content_hash=self.content_hash,
            captured_at=self.captured_at,
            capture_latency_ms=self.capture_latency_ms,
            persisted=persisted,
            asset_name=asset_name,
            deduplicated=deduplicated,
        )


@dataclass(frozen=True, slots=True)
class AppshotReceipt:
    """Sanitized queue receipt; image bytes and absolute paths are excluded."""

    association: TerminalSessionAssociation
    metadata: FocusedWindowMetadata
    visual: VisualAttachmentReceipt
    content_hash: str
    captured_at: str
    capture_latency_ms: float
    persisted: bool
    asset_name: str | None
    deduplicated: bool = False

    def __post_init__(self) -> None:
        if self.asset_name is not None:
            asset_path = Path(self.asset_name)
            if asset_path.is_absolute() or ".." in asset_path.parts:
                raise AppshotContractError("receipt asset_name must be relative")

    @property
    def attachment_id(self) -> str:
        return self.visual.attachment_id

    @property
    def name(self) -> str:
        return f"{self.association.session_id}-{self.attachment_id}.json"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "fcc.appshot.receipt.v1",
            "session": self.association.as_dict(),
            "window": self.metadata.as_receipt_dict(),
            "visual": self.visual.as_dict(),
            "content_hash": self.content_hash,
            "captured_at": self.captured_at,
            "capture_latency_ms": self.capture_latency_ms,
            "persisted": self.persisted,
            "asset_name": self.asset_name,
            "deduplicated": self.deduplicated,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AppshotReceipt:
        session_data = _object_mapping(value.get("session"))
        window_data = _object_mapping(value.get("window"))
        visual_data = _object_mapping(value.get("visual"))
        session_id = session_data.get("session_id")
        source = session_data.get("source", "explicit")
        attachment_id = visual_data.get("attachment_id")
        media_type = visual_data.get("media_type")
        byte_count = visual_data.get("byte_count")
        width = visual_data.get("width")
        height = visual_data.get("height")
        if not isinstance(session_id, str):
            raise AppshotContractError("invalid Appshot receipt session")
        if not isinstance(source, str):
            raise AppshotContractError("invalid Appshot receipt source")
        if not isinstance(attachment_id, str) or not isinstance(media_type, str):
            raise AppshotContractError("invalid Appshot receipt visual")
        byte_count = _required_int(byte_count, field_name="byte_count")
        width = _required_int(width, field_name="width")
        height = _required_int(height, field_name="height")
        content_hash = value.get("content_hash")
        captured_at = value.get("captured_at")
        latency = value.get("capture_latency_ms")
        asset_name = value.get("asset_name")
        if not isinstance(content_hash, str) or not isinstance(captured_at, str):
            raise AppshotContractError("invalid Appshot receipt metadata")
        if not isinstance(latency, (int, float)) or isinstance(latency, bool):
            raise AppshotContractError("invalid Appshot receipt latency")
        if asset_name is not None and not isinstance(asset_name, str):
            raise AppshotContractError("invalid Appshot receipt asset")
        metadata = FocusedWindowMetadata.from_mapping(window_data)
        return cls(
            association=TerminalSessionAssociation(
                session_id=session_id,
                source=source,
            ),
            metadata=metadata,
            visual=VisualAttachmentReceipt(
                attachment_id=attachment_id,
                media_type=media_type,
                byte_count=byte_count,
                width=width,
                height=height,
                label=str(visual_data.get("label", "appshot")),
            ),
            content_hash=content_hash,
            captured_at=captured_at,
            capture_latency_ms=float(latency),
            persisted=value.get("persisted") is True,
            asset_name=asset_name,
            deduplicated=value.get("deduplicated") is True,
        )


class AppshotQueuePort(Protocol):
    """Queue boundary consumed by a wrapper or local session integration."""

    def enqueue(self, attachment: AppshotAttachment) -> AppshotReceipt:
        """Store one attachment and return a sanitized receipt."""

    def pending(
        self, association: TerminalSessionAssociation
    ) -> tuple[AppshotReceipt, ...]:
        """Return receipts for exactly one explicit terminal-session target."""


class InMemoryAppshotQueue:
    """Default queue: local, process-scoped, deduplicating, and non-persistent."""

    def __init__(self) -> None:
        self._items: dict[
            tuple[str, str], tuple[AppshotAttachment, AppshotReceipt]
        ] = {}

    def enqueue(self, attachment: AppshotAttachment) -> AppshotReceipt:
        key = (attachment.session_id, attachment.content_hash)
        existing = self._items.get(key)
        if existing is not None:
            return replace(existing[1], deduplicated=True)
        receipt = attachment.receipt(persisted=False, asset_name=None)
        self._items[key] = (attachment, receipt)
        return receipt

    def pending(
        self, association: TerminalSessionAssociation
    ) -> tuple[AppshotReceipt, ...]:
        receipts = [
            receipt
            for attachment, receipt in self._items.values()
            if attachment.session_id == association.session_id
        ]
        return tuple(sorted(receipts, key=lambda item: (item.captured_at, item.name)))

    def read_asset(self, receipt: AppshotReceipt) -> bytes:
        key = (receipt.association.session_id, receipt.content_hash)
        item = self._items.get(key)
        if item is None:
            raise AppshotContractError("Appshot is not present in this queue")
        return item[0].image_bytes


class FileAppshotQueue:
    """Explicit opt-in local queue; receipt JSON never contains image bytes."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser()

    def _receipt_path(
        self, association: TerminalSessionAssociation, attachment_id: str
    ) -> Path:
        return self.root / f"{association.session_id}-{attachment_id}.json"

    def _asset_name(self, attachment: AppshotAttachment) -> str:
        suffix = ".png" if attachment.visual.media_type == "image/png" else ".img"
        return f"{attachment.session_id}/{attachment.visual.attachment_id}{suffix}"

    def enqueue(self, attachment: AppshotAttachment) -> AppshotReceipt:
        asset_name = self._asset_name(attachment)
        receipt_path = self._receipt_path(
            attachment.association, attachment.visual.attachment_id
        )
        existing = self._read_receipt(receipt_path)
        if existing is not None:
            if existing.content_hash != attachment.content_hash:
                raise AppshotContractError("Appshot attachment-id collision")
            return replace(existing, deduplicated=True)

        asset_path = self._checked_path(asset_name)
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        if not asset_path.exists():
            _atomic_write_bytes(asset_path, attachment.image_bytes)
        receipt = attachment.receipt(persisted=True, asset_name=asset_name)
        _atomic_write_text(
            receipt_path,
            json.dumps(receipt.as_dict(), sort_keys=True) + "\n",
        )
        return receipt

    def pending(
        self, association: TerminalSessionAssociation
    ) -> tuple[AppshotReceipt, ...]:
        if not self.root.is_dir():
            return ()
        receipts: list[AppshotReceipt] = []
        for path in sorted(self.root.glob(f"{association.session_id}-*.json")):
            receipt = self._read_receipt(path)
            if (
                receipt is not None
                and receipt.association.session_id == association.session_id
            ):
                receipts.append(receipt)
        return tuple(receipts)

    def asset_path(self, receipt: AppshotReceipt) -> Path:
        if not receipt.persisted or receipt.asset_name is None:
            raise AppshotContractError("receipt does not reference a persisted asset")
        return self._checked_path(receipt.asset_name)

    def receipt_path(self, receipt: AppshotReceipt) -> Path:
        if not receipt.persisted:
            raise AppshotContractError("receipt is not persisted")
        return self._receipt_path(receipt.association, receipt.attachment_id)

    def read_asset(self, receipt: AppshotReceipt) -> bytes:
        return self.asset_path(receipt).read_bytes()

    def _checked_path(self, asset_name: str) -> Path:
        candidate = (self.root / asset_name).resolve()
        root = self.root.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise AppshotContractError("receipt asset escapes the queue root") from exc
        return candidate

    @staticmethod
    def _read_receipt(path: Path) -> AppshotReceipt | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        if not isinstance(value, Mapping):
            return None
        try:
            return AppshotReceipt.from_dict(value)
        except AppshotContractError, TypeError, ValueError:
            return None


def capture_appshot(
    source: FocusedWindowCapturePort,
    association: TerminalSessionAssociation,
    *,
    queue: AppshotQueuePort | None = None,
    policy: AppshotPolicy | None = None,
    media_type: str = "image/png",
    monotonic: Callable[[], float] = time.monotonic,
    timestamp: Callable[[], datetime] | None = None,
) -> tuple[AppshotAttachment, AppshotReceipt]:
    """Inspect, authorize, capture, validate, and queue one focused window."""
    selected_policy = policy or AppshotPolicy()
    started = monotonic()
    metadata = source.inspect_focused_window()
    selected_policy.sensitive_apps.ensure_allowed(metadata)
    image_bytes = source.capture_focused_window(metadata)
    finished = monotonic()
    visual = validate_image_bytes(
        image_bytes,
        media_type=media_type,
        label=selected_policy.label,
        max_bytes=selected_policy.max_bytes,
    )
    metadata = metadata.with_dimensions(visual.width, visual.height)
    clock_timestamp = timestamp or _utc_now
    captured_at = _format_timestamp(clock_timestamp())
    attachment = AppshotAttachment(
        association=association,
        metadata=metadata,
        visual=visual,
        image_bytes=image_bytes,
        content_hash=hashlib.sha256(image_bytes).hexdigest(),
        captured_at=captured_at,
        capture_latency_ms=round(max(0.0, finished - started) * 1000, 3),
    )
    selected_queue = queue or InMemoryAppshotQueue()
    return attachment, selected_queue.enqueue(attachment)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _object_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_text(path: Path, data: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(data, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "AppshotAttachment",
    "AppshotContractError",
    "AppshotPolicy",
    "AppshotQueuePort",
    "AppshotReceipt",
    "FileAppshotQueue",
    "FocusedWindowCapturePort",
    "FocusedWindowMetadata",
    "InMemoryAppshotQueue",
    "SensitiveAppPolicy",
    "SensitiveAppshotError",
    "TerminalSessionAssociation",
    "capture_appshot",
]
