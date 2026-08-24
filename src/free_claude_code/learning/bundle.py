"""Deterministic, inspectable bundles for FCC Learning state."""

import hashlib
import io
import json
import math
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .store import LearningStore, redact_sensitive

BUNDLE_SCHEMA = "fcc.learning.bundle"
BUNDLE_VERSION = 1

_PROFILE_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,31})\Z")
_SKILL_KEY_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+|[A-Za-z]:[\\/][^\s]+)"
)
_HEX_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")

_MEMORY_FIELDS = (
    "scope",
    "project_ref",
    "text",
    "confidence",
    "source",
    "pinned",
)
_SKILL_FIELDS = (
    "key",
    "scope",
    "project_ref",
    "description",
    "revision",
    "digest",
    "path",
)


class BundleError(ValueError):
    """Raised when a learning bundle is invalid or unsafe to apply."""


@dataclass(frozen=True, slots=True)
class LearningBundle:
    """Validated bundle manifest and skill file bytes."""

    manifest: dict[str, Any]
    files: dict[str, bytes]

    def archive_bytes(self) -> bytes:
        """Serialize the bundle with stable ZIP metadata and ordering."""

        output = io.BytesIO()
        with zipfile.ZipFile(
            output, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            _write_zip_entry(
                archive,
                "manifest.json",
                _canonical_json(self.manifest),
            )
            for name in sorted(self.files):
                _write_zip_entry(archive, name, self.files[name])
        return output.getvalue()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BundleError("bundle contains a non-JSON value") from exc


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_zip_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _field(row: Any, name: str) -> Any:
    try:
        return row[name]
    except KeyError, IndexError, TypeError:
        raise BundleError(f"bundle source is missing field: {name}") from None


def _profile_name(profile: str) -> str:
    if not isinstance(profile, str):
        raise BundleError("profile must be a string")
    normalized = profile.strip().casefold()
    if not _PROFILE_RE.fullmatch(normalized):
        raise BundleError(
            "profile must use 1-32 lowercase letters, digits, '.', '_' or '-'"
        )
    return normalized


def _portable_text(
    value: Any,
    *,
    field_name: str,
    source_project: str = "",
    normalize_project: bool = True,
) -> str:
    if not isinstance(value, str):
        raise BundleError(f"{field_name} must be a string")
    text = value
    if normalize_project and source_project:
        candidates = {source_project}
        with suppress(OSError):
            candidates.add(str(Path(source_project).expanduser().resolve()))
        for candidate in sorted(candidates, key=len, reverse=True):
            if candidate:
                text = text.replace(candidate, "<project>")
    if redact_sensitive(text) != text:
        raise BundleError(f"{field_name} contains secret-like or encoded data")
    if _ABSOLUTE_PATH_RE.search(text):
        raise BundleError(f"{field_name} contains an absolute machine path")
    return text


def _scope_and_ref(row: Mapping[str, Any], source_project: str) -> tuple[str, str]:
    scope = _field(row, "scope")
    if scope not in {"global", "project"}:
        raise BundleError(f"unsupported learning scope: {scope!r}")
    if scope == "project" and not source_project:
        raise BundleError("project-scoped state requires a source project")
    return str(scope), "current" if scope == "project" else "global"


def _memory_key(entry: Mapping[str, Any]) -> str:
    return _digest(_canonical_json({name: entry[name] for name in _MEMORY_FIELDS}))


def _skill_archive_path(skill_key: str) -> str:
    if not isinstance(skill_key, str) or not _SKILL_KEY_RE.fullmatch(skill_key):
        raise BundleError(f"unsafe skill key: {skill_key!r}")
    return f"skills/{skill_key}/SKILL.md"


def _validate_skill_content(
    content: str, *, skill_key: str, source_project: str
) -> bytes:
    _portable_text(
        content,
        field_name=f"skill {skill_key} content",
        source_project=source_project,
        normalize_project=False,
    )
    if not content.strip():
        raise BundleError(f"skill {skill_key} content is empty")
    if len(content.encode("utf-8")) > 512 * 1024:
        raise BundleError(f"skill {skill_key} content is too large")
    if not content.startswith("---\n") or "\n---\n" not in content[4:]:
        raise BundleError(f"skill {skill_key} is not a SKILL.md document")
    frontmatter = content[4:].split("\n---\n", 1)[0]
    if f"name: {skill_key}" not in frontmatter:
        raise BundleError(f"skill {skill_key} frontmatter name does not match")
    if "description:" not in frontmatter:
        raise BundleError(f"skill {skill_key} frontmatter has no description")
    return content.encode("utf-8")


def build_bundle(
    *,
    profile: str,
    project_key: str,
    memories: Iterable[Any],
    skills: Iterable[Any],
    skill_contents: Mapping[str, str],
) -> LearningBundle:
    """Build a portable bundle from store-shaped memory and skill rows."""

    normalized_profile = _profile_name(profile)
    source_project = str(project_key).strip()
    memory_entries: list[dict[str, Any]] = []
    seen_memory_keys: set[str] = set()
    for row in memories:
        scope, project_ref = _scope_and_ref(row, source_project)
        confidence = _field(row, "confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise BundleError("memory confidence must be numeric")
        if not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
            raise BundleError("memory confidence must be between 0 and 1")
        source = _portable_text(
            _field(row, "source"),
            field_name="memory source",
            source_project=source_project,
        )
        if not source:
            raise BundleError("memory source must not be empty")
        entry = {
            "scope": scope,
            "project_ref": project_ref,
            "text": _portable_text(
                _field(row, "text"),
                field_name="memory text",
                source_project=source_project,
            ),
            "confidence": float(confidence),
            "source": source,
            "pinned": bool(_field(row, "pinned")) if "pinned" in row else False,
        }
        entry["key"] = _memory_key(entry)
        if entry["key"] in seen_memory_keys:
            continue
        seen_memory_keys.add(entry["key"])
        memory_entries.append(entry)

    skill_entries: list[dict[str, Any]] = []
    skill_files: dict[str, bytes] = {}
    seen_skill_keys: set[str] = set()
    for row in skills:
        skill_key = _field(row, "skill_key")
        archive_path = _skill_archive_path(skill_key)
        if skill_key in seen_skill_keys:
            raise BundleError(f"duplicate skill key: {skill_key}")
        seen_skill_keys.add(skill_key)
        scope, project_ref = _scope_and_ref(row, source_project)
        content = skill_contents.get(skill_key)
        if content is None:
            raise BundleError(f"skill file is unavailable: {skill_key}")
        content_bytes = _validate_skill_content(
            content, skill_key=skill_key, source_project=source_project
        )
        revision = _field(row, "revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise BundleError(f"skill revision is invalid: {skill_key}")
        description = _portable_text(
            _field(row, "description"),
            field_name=f"skill {skill_key} description",
            source_project=source_project,
        )
        digest = _digest(content_bytes)
        skill_entries.append(
            {
                "key": skill_key,
                "scope": scope,
                "project_ref": project_ref,
                "description": description,
                "revision": revision,
                "digest": digest,
                "path": archive_path,
            }
        )
        skill_files[archive_path] = content_bytes

    memory_entries.sort(key=lambda entry: entry["key"])
    skill_entries.sort(key=lambda entry: entry["key"])
    base_manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "version": BUNDLE_VERSION,
        "profile": normalized_profile,
        "memories": memory_entries,
        "skills": skill_entries,
    }
    base_manifest_bytes = _canonical_json(base_manifest)
    manifest = {
        **base_manifest,
        "checksums": {
            "manifest": _digest(base_manifest_bytes),
            "files": {
                name: _digest(content) for name, content in sorted(skill_files.items())
            },
        },
    }
    return LearningBundle(manifest=manifest, files=skill_files)


def write_bundle(path: Path, bundle: LearningBundle) -> None:
    """Atomically write a bundle to an explicit destination."""

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(bundle.archive_bytes())
            temporary.flush()
            os.fsync(temporary.fileno())
        Path(temporary_name).replace(target)
    finally:
        if temporary_name is not None:
            with suppress(FileNotFoundError):
                Path(temporary_name).unlink()


def export_from_store(
    path: Path,
    *,
    store: LearningStore,
    project_key: str,
    profile: str = "default",
    limit: int = 1000,
) -> dict[str, Any]:
    """Export the visible global/current-project learning state."""

    skills = store.list_skills(project_key=project_key)
    skill_contents: dict[str, str] = {}
    for row in skills:
        skill_key = str(row["skill_key"])
        try:
            skill_contents[skill_key] = Path(str(row["path"])).read_text(
                encoding="utf-8"
            )
        except (OSError, UnicodeError) as exc:
            raise BundleError(f"skill file is unavailable: {skill_key}") from exc
    bundle = build_bundle(
        profile=profile,
        project_key=project_key,
        memories=store.list_memories(project_key=project_key, limit=max(0, limit)),
        skills=skills,
        skill_contents=skill_contents,
    )
    write_bundle(path, bundle)
    return bundle_summary(bundle)


def _validate_manifest(manifest: object) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(manifest, dict):
        raise BundleError("manifest root must be an object")
    expected_top_level = {
        "schema",
        "version",
        "profile",
        "memories",
        "skills",
        "checksums",
    }
    if set(manifest) != expected_top_level:
        raise BundleError("manifest fields do not match bundle schema")
    if manifest.get("schema") != BUNDLE_SCHEMA:
        raise BundleError("unknown learning bundle schema")
    if manifest.get("version") != BUNDLE_VERSION:
        raise BundleError(
            f"unsupported learning bundle version: {manifest.get('version')!r}"
        )
    manifest_dict = cast(dict[str, Any], manifest)
    profile = manifest_dict.get("profile")
    if not isinstance(profile, str):
        raise BundleError("manifest profile is invalid")
    _profile_name(profile)
    memories_value = manifest_dict.get("memories")
    skills_value = manifest_dict.get("skills")
    checksums_value = manifest_dict.get("checksums")
    if not isinstance(memories_value, list) or not isinstance(skills_value, list):
        raise BundleError("manifest memories and skills must be arrays")
    memories = cast(list[Any], memories_value)
    skills = cast(list[dict[str, Any]], skills_value)
    if not isinstance(checksums_value, dict) or set(checksums_value) != {
        "manifest",
        "files",
    }:
        raise BundleError("manifest checksums are missing")
    checksums = cast(dict[str, Any], checksums_value)
    manifest_digest = checksums.get("manifest")
    if not isinstance(manifest_digest, str) or not _HEX_DIGEST_RE.fullmatch(
        manifest_digest
    ):
        raise BundleError("manifest checksum is invalid")
    base_manifest = {
        key: value for key, value in manifest_dict.items() if key != "checksums"
    }
    if _digest(_canonical_json(base_manifest)) != manifest_digest:
        raise BundleError("manifest checksum does not match")
    file_checksums = checksums.get("files")
    if not isinstance(file_checksums, dict):
        raise BundleError("file checksums must be an object")
    file_checksums = cast(dict[str, str], file_checksums)

    seen_memory_keys: set[str] = set()
    for entry in memories:
        if not isinstance(entry, dict) or set(entry) != {"key", *_MEMORY_FIELDS}:
            raise BundleError("memory entry fields do not match bundle schema")
        entry = cast(dict[str, Any], entry)
        if entry["scope"] not in {"global", "project"}:
            raise BundleError("memory scope is invalid")
        expected_ref = "current" if entry["scope"] == "project" else "global"
        if entry["project_ref"] != expected_ref:
            raise BundleError("memory project binding is invalid")
        if not isinstance(entry["pinned"], bool):
            raise BundleError("memory pinned flag is invalid")
        confidence = entry["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise BundleError("memory confidence is invalid")
        if not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
            raise BundleError("memory confidence is invalid")
        _portable_text(entry["text"], field_name="memory text", normalize_project=False)
        _portable_text(
            entry["source"], field_name="memory source", normalize_project=False
        )
        key = entry["key"]
        if not isinstance(key, str) or not _HEX_DIGEST_RE.fullmatch(key):
            raise BundleError("memory key is invalid")
        if key != _memory_key(entry) or key in seen_memory_keys:
            raise BundleError("memory key does not match content")
        seen_memory_keys.add(key)

    seen_skill_keys: set[str] = set()
    expected_file_names: set[str] = set()
    for entry in skills:
        if not isinstance(entry, dict) or set(entry) != set(_SKILL_FIELDS):
            raise BundleError("skill entry fields do not match bundle schema")
        key = entry["key"]
        path = entry["path"]
        archive_path = _skill_archive_path(key)
        if path != archive_path or key in seen_skill_keys:
            raise BundleError("skill path or key is invalid")
        if entry["scope"] not in {"global", "project"}:
            raise BundleError("skill scope is invalid")
        expected_ref = "current" if entry["scope"] == "project" else "global"
        if entry["project_ref"] != expected_ref:
            raise BundleError("skill project binding is invalid")
        if (
            isinstance(entry["revision"], bool)
            or not isinstance(entry["revision"], int)
            or entry["revision"] < 0
        ):
            raise BundleError("skill revision is invalid")
        if not isinstance(entry["digest"], str) or not _HEX_DIGEST_RE.fullmatch(
            entry["digest"]
        ):
            raise BundleError("skill digest is invalid")
        _portable_text(
            entry["description"],
            field_name=f"skill {key} description",
            normalize_project=False,
        )
        expected_file_names.add(archive_path)
        seen_skill_keys.add(key)

    if set(file_checksums) != expected_file_names:
        raise BundleError("file checksum entries do not match skills")
    for name, checksum in file_checksums.items():
        if not isinstance(name, str) or not isinstance(checksum, str):
            raise BundleError("file checksum is invalid")
        if not _HEX_DIGEST_RE.fullmatch(checksum):
            raise BundleError("file checksum is invalid")
    return manifest_dict, skills


def read_bundle(path: Path) -> LearningBundle:
    """Read and fully validate one bundle before exposing its contents."""

    try:
        with zipfile.ZipFile(Path(path).expanduser(), mode="r") as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise BundleError("bundle contains duplicate archive entries")
            for entry in entries:
                mode = (entry.external_attr >> 16) & 0o170000
                if entry.is_dir() or mode == 0o120000:
                    raise BundleError("bundle contains a directory or symlink")
            if "manifest.json" not in names:
                raise BundleError("bundle has no manifest.json")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BundleError("manifest.json is not valid UTF-8 JSON") from exc
            validated_manifest, skill_entries = _validate_manifest(manifest)
            expected_names = {"manifest.json"} | {
                str(entry["path"]) for entry in skill_entries
            }
            if set(names) != expected_names:
                raise BundleError("bundle files do not match its manifest")
            files: dict[str, bytes] = {}
            file_checksums = validated_manifest["checksums"]["files"]
            for name in sorted(expected_names - {"manifest.json"}):
                content = archive.read(name)
                if _digest(content) != file_checksums[name]:
                    raise BundleError(f"skill file checksum does not match: {name}")
                files[name] = content
            for entry in skill_entries:
                content = files[entry["path"]]
                try:
                    decoded = content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise BundleError(
                        f"skill file is not UTF-8: {entry['path']}"
                    ) from exc
                _validate_skill_content(
                    decoded,
                    skill_key=entry["key"],
                    source_project="",
                )
                if _digest(content) != entry["digest"]:
                    raise BundleError(f"skill digest does not match: {entry['key']}")
            return LearningBundle(manifest=validated_manifest, files=files)
    except BundleError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise BundleError(f"cannot read learning bundle: {path}") from exc


def bundle_summary(bundle: LearningBundle) -> dict[str, Any]:
    """Return stable, non-sensitive bundle metadata for CLI output."""

    return {
        "schema": bundle.manifest["schema"],
        "version": bundle.manifest["version"],
        "profile": bundle.manifest["profile"],
        "memories": len(bundle.manifest["memories"]),
        "skills": len(bundle.manifest["skills"]),
        "manifest_digest": bundle.manifest["checksums"]["manifest"],
    }


def inspect_bundle(path: Path) -> dict[str, Any]:
    """Validate a bundle and return only inspectable metadata."""

    return bundle_summary(read_bundle(path))


def _target_memory_text(text: str, target_project: str) -> str:
    return text.replace("<project>", target_project)


def _memory_exists(
    store: LearningStore, *, scope: str, project_key: str, text: str
) -> bool:
    normalized = " ".join(text.split()).casefold()
    for row in store.list_memories(project_key=project_key, scope=scope, limit=100_000):
        if " ".join(str(row["text"]).split()).casefold() == normalized:
            return True
    return False


def _skill_target_path(
    *,
    skill_key: str,
    scope: str,
    project_key: str,
    claude_config_dir: Path,
) -> Path:
    root = (
        Path(project_key) / ".claude" / "skills"
        if scope == "project"
        else Path(claude_config_dir) / "skills"
    )
    return root / skill_key / "SKILL.md"


def _target_skill_digest(path: Path) -> str | None:
    try:
        return _digest(path.read_bytes())
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BundleError(f"cannot read existing skill: {path}") from exc


def plan_import(
    bundle: LearningBundle,
    *,
    store: LearningStore,
    target_project_key: str,
    claude_config_dir: Path,
    conflict: str = "skip",
) -> list[dict[str, Any]]:
    """Plan an import without changing SQLite or skill files."""

    if conflict not in {"skip", "replace", "fail"}:
        raise BundleError(f"unsupported conflict policy: {conflict}")
    actions: list[dict[str, Any]] = []
    for entry in bundle.manifest["memories"]:
        text = _target_memory_text(str(entry["text"]), target_project_key)
        duplicate = _memory_exists(
            store,
            scope=str(entry["scope"]),
            project_key=target_project_key,
            text=text,
        )
        actions.append(
            {
                "kind": "memory",
                "key": entry["key"],
                "action": "skip_duplicate" if duplicate else "add",
            }
        )
    for entry in bundle.manifest["skills"]:
        path = _skill_target_path(
            skill_key=str(entry["key"]),
            scope=str(entry["scope"]),
            project_key=target_project_key,
            claude_config_dir=claude_config_dir,
        )
        current_digest = _target_skill_digest(path)
        if current_digest is None:
            action = "add"
        elif current_digest == entry["digest"]:
            action = "skip_unchanged"
        elif conflict == "replace":
            action = "replace"
        elif conflict == "fail":
            action = "conflict"
        else:
            action = "skip_conflict"
        actions.append(
            {
                "kind": "skill",
                "key": entry["key"],
                "action": action,
                "path": str(path),
            }
        )
    return actions


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        Path(temporary_name).replace(path)
    finally:
        if temporary_name is not None:
            with suppress(FileNotFoundError):
                Path(temporary_name).unlink()


def _apply_skill_import(
    *,
    entry: Mapping[str, Any],
    content: bytes,
    store: LearningStore,
    target_project_key: str,
    claude_config_dir: Path,
    replacing: bool,
) -> None:
    skill_key = str(entry["key"])
    scope = str(entry["scope"])
    path = _skill_target_path(
        skill_key=skill_key,
        scope=scope,
        project_key=target_project_key,
        claude_config_dir=claude_config_dir,
    )
    current = _target_skill_digest(path)
    record = store.skill_record(skill_key)
    if replacing and current is not None:
        current_revision = int(record["revision"]) if record is not None else 0
        known_revisions = {
            int(row["revision"]) for row in store.skill_revisions(skill_key)
        }
        if current_revision <= 0 or current_revision not in known_revisions:
            store.record_skill_revision(
                skill_key=skill_key,
                revision=max(1, current_revision),
                content=path.read_text(encoding="utf-8"),
            )
    revision = max(1, int(entry["revision"]))
    next_revision = store.next_skill_revision(skill_key)
    if current is not None or next_revision > 1:
        revision = max(revision, next_revision)
    _atomic_write(path, content)
    digest = store.record_skill_revision(
        skill_key=skill_key,
        revision=revision,
        content=content.decode("utf-8"),
    )
    store.record_skill(
        skill_key=skill_key,
        path=path,
        scope=scope,
        project_key=target_project_key if scope == "project" else "",
        description=str(entry["description"]),
        revision=revision,
        digest=digest,
    )


def import_bundle(
    path: Path,
    *,
    store: LearningStore,
    target_project_key: str,
    claude_config_dir: Path,
    conflict: str = "skip",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Plan or apply a bundle import with explicit conflict behavior."""

    bundle = read_bundle(path)
    actions = plan_import(
        bundle,
        store=store,
        target_project_key=target_project_key,
        claude_config_dir=claude_config_dir,
        conflict=conflict,
    )
    if any(action["action"] == "conflict" for action in actions) and not dry_run:
        raise BundleError(
            "import has conflicts; choose --conflict skip or --conflict replace"
        )
    if dry_run:
        return {
            **bundle_summary(bundle),
            "dry_run": True,
            "actions": actions,
            "applied": {"memories": 0, "skills": 0},
        }

    memory_entries = {str(entry["key"]): entry for entry in bundle.manifest["memories"]}
    skill_entries = {str(entry["key"]): entry for entry in bundle.manifest["skills"]}
    applied = {"memories": 0, "skills": 0}
    for action in actions:
        if action["kind"] == "memory" and action["action"] == "add":
            entry = memory_entries[action["key"]]
            _, inserted = store.add_memory(
                scope=str(entry["scope"]),
                project_key=target_project_key,
                text=_target_memory_text(str(entry["text"]), target_project_key),
                confidence=float(entry["confidence"]),
                source=str(entry["source"]),
                reason=f"fcc-learning bundle import:{bundle.manifest['profile']}",
            )
            applied["memories"] += int(inserted)
        elif action["kind"] == "skill" and action["action"] in {"add", "replace"}:
            entry = skill_entries[action["key"]]
            _apply_skill_import(
                entry=entry,
                content=bundle.files[str(entry["path"])],
                store=store,
                target_project_key=target_project_key,
                claude_config_dir=claude_config_dir,
                replacing=action["action"] == "replace",
            )
            applied["skills"] += 1
    return {
        **bundle_summary(bundle),
        "dry_run": False,
        "actions": actions,
        "applied": applied,
    }
