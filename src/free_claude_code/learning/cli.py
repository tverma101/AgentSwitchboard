"""Command-line entrypoint for FCC Learning state and lifecycle controls."""

import argparse
import json
import os
import sys
from collections.abc import Iterable
from typing import Any

from .hooks import install_hooks, run_hook, uninstall_hooks
from .stop_hook import drain_queue
from .store import LearningStore, learning_home, project_identity


def _cwd(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cwd", default=os.getcwd(), help="project directory for scoped state"
    )


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
    subcommands.add_parser("status", help="show local learning state")

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
    skill_history.add_argument("skill_key")
    skill_rollback = skill_commands.add_parser("rollback")
    skill_rollback.add_argument("skill_key")
    skill_rollback.add_argument("revision", type=int)

    queue = subcommands.add_parser(
        "queue", help="inspect or drain durable learning jobs"
    )
    queue_commands = queue.add_subparsers(dest="queue_command", required=True)
    queue_commands.add_parser("status")
    queue_drain = queue_commands.add_parser("drain")
    queue_drain.add_argument("--limit", type=int, default=2)

    hook = subcommands.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument("event", choices=("session-start", "user-prompt"))
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

    store = LearningStore()
    if args.command == "status":
        print(
            json.dumps(
                {
                    "home": str(learning_home()),
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
    if args.command == "queue":
        if args.queue_command == "status":
            print(json.dumps(store.queue_counts(), indent=2))
        else:
            print(json.dumps({"processed": drain_queue(store, max_items=args.limit)}))
        return
    if args.command == "hook":
        try:
            run_hook(args.event)
        except Exception as exc:
            print(f"FCC Learning hook failed: {type(exc).__name__}", file=sys.stderr)
        return


if __name__ == "__main__":
    main()
