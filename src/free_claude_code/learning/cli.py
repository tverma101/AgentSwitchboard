"""Command-line entrypoint for FCC Learning state and lifecycle controls."""

import argparse
import json
import os
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from free_claude_code.core.anthropic.context_artifact import (
    ContextArtifactError,
    read_context_artifact_slice,
)
from free_claude_code.core.claude_compatibility import (
    default_process_wrapper_path,
    inspect_claude_compatibility,
)

from .bundle import BundleError, export_from_store, import_bundle, inspect_bundle
from .config import (
    LearningProfileError,
    archive_profile,
    configured_profile,
    create_profile,
    list_profiles,
    profile_database,
    profile_home,
    rename_profile,
    restore_profile,
)
from .context_policy import (
    context_policy_status,
    install_context_policy,
    uninstall_context_policy,
)
from .hooks import claude_config_dir, install_hooks, run_hook, uninstall_hooks
from .stop_hook import drain_queue
from .store import LearningStore, learning_home, project_identity


def _cwd(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cwd", default=os.getcwd(), help="project directory for scoped state"
    )
    parser.add_argument("--profile", help="named FCC Learning profile")


def _profile(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="named FCC Learning profile")


def _row(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        keys = tuple(row.keys())
        return {str(key): row[key] for key in keys}
    return dict(row)


def _print_rows(rows: Iterable[Any]) -> None:
    print(json.dumps([_row(row) for row in rows], indent=2, default=str))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcc-learning",
        description="Persistent memory and automatic Claude Code skill learning for FCC.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("install", help="merge FCC Learning hooks into Claude Code")
    subcommands.add_parser("uninstall", help="remove only FCC Learning hooks")
    status = subcommands.add_parser("status", help="show local learning state")
    _profile(status)

    profile = subcommands.add_parser(
        "profile", help="list or change isolated learning profiles"
    )
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("list", help="list discovered profiles")
    profile_create = profile_commands.add_parser("create", help="create a profile")
    profile_create.add_argument("name")
    profile_rename = profile_commands.add_parser("rename", help="rename a profile")
    profile_rename.add_argument("name")
    profile_rename.add_argument("new_name")
    profile_archive = profile_commands.add_parser(
        "archive", help="move a profile into the local recovery archive"
    )
    profile_archive.add_argument("name")
    profile_restore = profile_commands.add_parser(
        "restore", help="restore a profile from the local recovery archive"
    )
    profile_restore.add_argument("name")

    compatibility = subcommands.add_parser(
        "claude-compat",
        help="inspect the installed Claude Code compatibility firewall state",
    )
    compatibility.add_argument(
        "--binary",
        help="explicit Claude executable path; defaults to the first claude on PATH",
    )

    policy = subcommands.add_parser(
        "context-policy",
        help="manage the global Claude context-discipline instructions",
    )
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    policy_commands.add_parser("install", help="install or update the managed block")
    policy_commands.add_parser("uninstall", help="remove only the managed block")
    policy_commands.add_parser("status", help="show the policy path and digest")

    artifact = subcommands.add_parser(
        "context-artifact",
        help="retrieve a bounded slice from a governed local tool-result artifact",
    )
    artifact_commands = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_slice = artifact_commands.add_parser(
        "slice", help="read a bounded line/byte slice"
    )
    artifact_slice.add_argument("path")
    artifact_slice.add_argument("--start-line", type=int, default=1)
    artifact_slice.add_argument("--line-count", type=int, default=80)
    artifact_slice.add_argument("--max-bytes", type=int, default=16 * 1024)

    memory = subcommands.add_parser("memory", help="inspect or edit durable memories")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_list = memory_commands.add_parser("list")
    _cwd(memory_list)
    memory_list.add_argument("--scope", choices=("global", "project"))
    memory_list.add_argument("--limit", type=int, default=100)
    memory_search = memory_commands.add_parser("search")
    _cwd(memory_search)
    memory_search.add_argument("terms")
    memory_search.add_argument("--limit", type=int, default=100)
    memory_show = memory_commands.add_parser("show")
    _cwd(memory_show)
    memory_show.add_argument("memory_id", type=int)
    memory_remove = memory_commands.add_parser("remove")
    _cwd(memory_remove)
    memory_remove.add_argument("memory_id", type=int)
    memory_history = memory_commands.add_parser("history")
    _cwd(memory_history)
    memory_history.add_argument("memory_id", type=int)
    memory_evict = memory_commands.add_parser("evict")
    memory_evict.add_argument("--older-than-days", type=float, default=180.0)
    memory_evict.add_argument("--limit", type=int, default=100)

    skill = subcommands.add_parser("skill", help="inspect or roll back learned skills")
    skill_commands = skill.add_subparsers(dest="skill_command", required=True)
    skill_list = skill_commands.add_parser("list")
    _cwd(skill_list)
    skill_history = skill_commands.add_parser("history")
    _profile(skill_history)
    skill_history.add_argument("skill_key")
    skill_rollback = skill_commands.add_parser("rollback")
    _profile(skill_rollback)
    skill_rollback.add_argument("skill_key")
    skill_rollback.add_argument("revision", type=int)

    bundle = subcommands.add_parser(
        "bundle", help="export, inspect, or import portable learning state"
    )
    bundle_commands = bundle.add_subparsers(dest="bundle_command", required=True)
    bundle_export = bundle_commands.add_parser(
        "export", help="write a deterministic portable learning bundle"
    )
    bundle_export.add_argument("path")
    _cwd(bundle_export)
    bundle_export.add_argument("--limit", type=int, default=1000)
    bundle_inspect = bundle_commands.add_parser(
        "inspect", help="validate a bundle and print its manifest summary"
    )
    bundle_inspect.add_argument("path")
    bundle_import = bundle_commands.add_parser(
        "import", help="plan or apply a portable learning bundle"
    )
    bundle_import.add_argument("path")
    _cwd(bundle_import)
    bundle_import.add_argument(
        "--conflict", choices=("skip", "replace", "fail"), default="skip"
    )
    bundle_import.add_argument("--dry-run", action="store_true")

    queue = subcommands.add_parser(
        "queue", help="inspect or drain durable learning jobs"
    )
    queue_commands = queue.add_subparsers(dest="queue_command", required=True)
    queue_status = queue_commands.add_parser("status")
    _profile(queue_status)
    queue_drain = queue_commands.add_parser("drain")
    _profile(queue_drain)
    queue_drain.add_argument("--limit", type=int, default=2)

    hook = subcommands.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument("event", choices=("session-start", "user-prompt"))
    _profile(hook)
    return parser


def _memory_command(args: argparse.Namespace, store: LearningStore) -> None:
    project_key = project_identity(args.cwd)
    if args.memory_command == "list":
        _print_rows(
            store.list_memories(
                project_key=project_key, scope=args.scope, limit=args.limit
            )
        )
    elif args.memory_command == "search":
        _print_rows(
            store.list_memories(
                project_key=project_key, search=args.terms, limit=args.limit
            )
        )
    elif args.memory_command == "show":
        row = store.get_memory(args.memory_id, project_key=project_key)
        if row is None:
            raise SystemExit(f"memory {args.memory_id} is not visible in this project")
        print(json.dumps(_row(row), indent=2, default=str))
    elif args.memory_command == "remove":
        if not store.remove_memory(
            args.memory_id,
            project_key=project_key,
            reason="fcc-learning memory remove",
            evidence="user_explicit",
        ):
            raise SystemExit(f"memory {args.memory_id} is not visible in this project")
        print(json.dumps({"removed": args.memory_id}))
    elif args.memory_command == "history":
        _print_rows(store.memory_history(args.memory_id, project_key=project_key))
    elif args.memory_command == "evict":
        print(
            json.dumps(
                {
                    "evicted": store.evict_stale_memories(
                        older_than_days=args.older_than_days, limit=args.limit
                    )
                }
            )
        )


def _skill_command(args: argparse.Namespace, store: LearningStore) -> None:
    if args.skill_command == "list":
        _print_rows(store.list_skills(project_key=project_identity(args.cwd)))
    elif args.skill_command == "history":
        _print_rows(store.skill_revisions(args.skill_key))
    elif args.skill_command == "rollback":
        path = store.rollback_skill(args.skill_key, args.revision)
        if path is None:
            raise SystemExit(
                f"skill revision not found: {args.skill_key}@{args.revision}"
            )
        print(
            json.dumps(
                {
                    "rolled_back": args.skill_key,
                    "revision": args.revision,
                    "path": str(path),
                }
            )
        )


def _profile_command(args: argparse.Namespace) -> dict[str, object]:
    if args.profile_command == "list":
        active = configured_profile()
        return {
            "active_profile": active,
            "profiles": [
                {
                    "profile": name,
                    "active": name == active,
                    "database": str(profile_database(name)),
                    "exists": profile_home(name).exists(),
                }
                for name in list_profiles()
            ],
        }
    if args.profile_command == "create":
        return {"created": create_profile(args.name)}
    if args.profile_command == "rename":
        return {
            "renamed": {
                "from": args.name,
                "to": rename_profile(args.name, args.new_name),
            }
        }
    if args.profile_command == "archive":
        return {"archived": archive_profile(args.name)}
    if args.profile_command == "restore":
        return {"restored": restore_profile(args.name)}
    raise LearningProfileError("unknown profile command")


def _context_artifact_root() -> str:
    configured = os.environ.get("FCC_CONTEXT_GOVERNOR_ARTIFACT_DIR", "").strip()
    if not configured:
        env_files = [Path(".env"), Path.home() / ".fcc" / ".env"]
        if explicit := os.environ.get("FCC_ENV_FILE"):
            env_files.append(Path(explicit).expanduser())
        for env_file in env_files:
            try:
                value = dotenv_values(env_file).get("FCC_CONTEXT_GOVERNOR_ARTIFACT_DIR")
            except OSError:
                continue
            if isinstance(value, str) and value.strip():
                configured = value.strip()
    return configured or str(Path.home() / ".fcc" / "context-artifacts")


def main() -> None:
    args = _parser().parse_args()
    if args.command == "install":
        changed = install_hooks()
        print("installed" if changed else "already installed")
        return
    if args.command == "uninstall":
        changed = uninstall_hooks()
        print("removed" if changed else "not installed")
        return
    if args.command == "context-policy":
        if args.policy_command == "install":
            changed = install_context_policy()
            print(json.dumps({"changed": changed, **context_policy_status()}))
        elif args.policy_command == "uninstall":
            changed = uninstall_context_policy()
            print(json.dumps({"changed": changed, **context_policy_status()}))
        else:
            print(json.dumps(context_policy_status(), indent=2))
        return
    if args.command == "context-artifact":
        try:
            result = read_context_artifact_slice(
                args.path,
                root=_context_artifact_root(),
                start_line=args.start_line,
                line_count=args.line_count,
                max_bytes=args.max_bytes,
            )
        except ContextArtifactError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result.as_response(), ensure_ascii=False, indent=2))
        return
    if args.command == "claude-compat":
        binary = args.binary or shutil.which("claude")
        if binary is None:
            print(
                json.dumps(
                    {
                        "state": "unresolved",
                        "claude_version": None,
                        "binary_path": None,
                    },
                    indent=2,
                )
            )
            return
        status = inspect_claude_compatibility(
            binary,
            base_env=os.environ,
            wrapper_path=default_process_wrapper_path(os.environ),
        )
        print(json.dumps(status.as_receipt(), indent=2, sort_keys=True))
        return

    if args.command == "bundle" and args.bundle_command == "inspect":
        try:
            result = inspect_bundle(Path(args.path))
        except BundleError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.command == "profile":
        try:
            result = _profile_command(args)
        except LearningProfileError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    try:
        store = LearningStore(profile=getattr(args, "profile", None))
    except LearningProfileError as exc:
        raise SystemExit(str(exc)) from exc
    if args.command == "status":
        print(
            json.dumps(
                {
                    "home": str(learning_home()),
                    "database": str(store.path),
                    **store.profile_info(),
                    **store.counts(),
                    "queue": store.queue_counts(),
                },
                indent=2,
            )
        )
        return
    if args.command == "memory":
        _memory_command(args, store)
        return
    if args.command == "skill":
        _skill_command(args, store)
        return
    if args.command == "bundle":
        try:
            if args.bundle_command == "export":
                result = export_from_store(
                    Path(args.path),
                    store=store,
                    project_key=project_identity(args.cwd),
                    profile=store.profile,
                    limit=args.limit,
                )
            else:
                result = import_bundle(
                    Path(args.path),
                    store=store,
                    target_project_key=project_identity(args.cwd),
                    claude_config_dir=claude_config_dir(),
                    conflict=args.conflict,
                    dry_run=args.dry_run,
                )
        except BundleError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.command == "queue":
        if args.queue_command == "status":
            print(json.dumps(store.queue_counts(), indent=2))
        else:
            print(json.dumps({"processed": drain_queue(store, max_items=args.limit)}))
        return
    if args.command == "hook":
        try:
            run_hook(args.event, profile=args.profile)
        except Exception as exc:
            print(f"FCC Learning hook failed: {type(exc).__name__}", file=sys.stderr)
        return


if __name__ == "__main__":
    main()
