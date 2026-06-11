from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from .store import MemoryInput, MemoryRecord, MemoryStore, VALID_KINDS, parse_timestamp, utc_now_iso


_SINCE_RELATIVE_RE = re.compile(r"^(\d+)d$")


DEFAULT_DB_PATH = Path(".memory-kernel") / "memory.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory-kernel",
        description="Focused local memory for AI agents.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the local memory database.")

    remember = subparsers.add_parser("remember", help="Store one memory record.")
    remember.add_argument("--scope", required=True)
    remember.add_argument("--kind", required=True, choices=VALID_KINDS)
    remember.add_argument("--title", required=True)
    remember.add_argument("--content", required=True)
    remember.add_argument("--summary", default="")
    remember.add_argument("--tags", nargs="*", default=[])
    remember.add_argument("--source", default="")
    remember.add_argument("--importance", type=float, default=0.5)
    remember.add_argument("--certainty", type=float, default=0.7)
    remember.add_argument("--json", action="store_true", help="Return machine-readable output.")

    ingest = subparsers.add_parser(
        "ingest",
        help="Ingest raw text or a file and extract structured memories.",
    )
    ingest.add_argument("--scope")
    ingest_source = ingest.add_mutually_exclusive_group()
    ingest_source.add_argument("--text")
    ingest_source.add_argument("--file")
    ingest.add_argument("--source", default="")
    ingest.add_argument("--kind", choices=VALID_KINDS)
    ingest.add_argument("--tags", nargs="*", default=[])
    ingest.add_argument("--max-items", type=int, default=24)
    ingest.add_argument("--importance", type=float)
    ingest.add_argument("--certainty", type=float)
    ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing to the database.",
    )
    ingest.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for scope/tags/text and preview before saving.",
    )
    ingest.add_argument("--json", action="store_true", help="Return machine-readable output.")

    search = subparsers.add_parser("search", help="Search the memory store.")
    search.add_argument("query")
    search.add_argument("--scope")
    search.add_argument("--kind", choices=VALID_KINDS)
    search.add_argument("--tags", nargs="*", default=[])
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--json", action="store_true", help="Return machine-readable output.")

    context = subparsers.add_parser("context", help="Build a compact context pack.")
    context.add_argument("query")
    context.add_argument("--scope")
    context.add_argument("--kind", choices=VALID_KINDS)
    context.add_argument("--tags", nargs="*", default=[])
    context.add_argument("--limit", type=int, default=5)
    context.add_argument("--budget-chars", type=int, default=1200)
    context.add_argument("--json", action="store_true", help="Return machine-readable output.")

    wake_up = subparsers.add_parser("wake-up", help="Build a wake-up pack from hot memories.")
    wake_up.add_argument("--scope")
    wake_up.add_argument("--limit", type=int, default=6)
    wake_up.add_argument("--budget-chars", type=int, default=800)
    wake_up.add_argument("--json", action="store_true", help="Return machine-readable output.")

    list_cmd = subparsers.add_parser("list", help="List recent memories with optional filters.")
    list_cmd.add_argument("--scope")
    list_cmd.add_argument("--kind", choices=VALID_KINDS)
    list_cmd.add_argument("--tags", nargs="*", default=[])
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.add_argument(
        "--include-archived",
        action="store_true",
        dest="include_archived",
        help="Also show archived and superseded memories.",
    )
    list_cmd.add_argument("--json", action="store_true", help="Return machine-readable output.")

    show = subparsers.add_parser("show", help="Show one memory by id.")
    show.add_argument("--id", required=True, dest="memory_id")
    show.add_argument("--json", action="store_true", help="Return machine-readable output.")

    update = subparsers.add_parser("update", help="Update fields of an existing memory.")
    update.add_argument("--id", required=True, dest="memory_id")
    update.add_argument("--scope")
    update.add_argument("--kind", choices=VALID_KINDS)
    update.add_argument("--title")
    update.add_argument("--content")
    update.add_argument("--summary")
    update.add_argument("--tags", nargs="*", default=None)
    update.add_argument("--source")
    update.add_argument("--importance", type=float)
    update.add_argument("--certainty", type=float)
    update.add_argument("--json", action="store_true", help="Return machine-readable output.")

    delete = subparsers.add_parser("delete", help="Delete a memory by id.")
    delete.add_argument("--id", required=True, dest="memory_id")
    delete.add_argument("--json", action="store_true", help="Return machine-readable output.")

    forget = subparsers.add_parser(
        "forget",
        help="Soft-archive a memory (hidden from recall, recoverable with restore).",
    )
    forget.add_argument("--id", required=True, dest="memory_id")
    forget.add_argument("--json", action="store_true", help="Return machine-readable output.")

    restore = subparsers.add_parser("restore", help="Restore a previously archived memory.")
    restore.add_argument("--id", required=True, dest="memory_id")
    restore.add_argument("--json", action="store_true", help="Return machine-readable output.")

    revise = subparsers.add_parser(
        "revise",
        help="Mark memory --id as superseding an older memory --supersedes.",
    )
    revise.add_argument("--id", required=True, dest="memory_id", help="The new memory that replaces the old one.")
    revise.add_argument("--supersedes", required=True, dest="superseded_id", help="The old memory being replaced.")
    revise.add_argument("--json", action="store_true", help="Return machine-readable output.")

    decay = subparsers.add_parser(
        "decay",
        help="Auto-archive weak, stale, rarely-used notes/facts (forgetting curve).",
    )
    decay.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be archived without changing anything.",
    )
    decay.add_argument("--min-age-days", type=int, default=None, help="Only decay memories older than this (default 30).")
    decay.add_argument("--max-access", type=int, default=None, help="Only decay memories accessed at most this many times (default 1).")
    decay.add_argument("--threshold", type=float, default=None, help="Retention threshold below which a memory decays (default 0.35).")
    decay.add_argument("--scope", default=None, help="Restrict decay to one scope.")
    decay.add_argument("--json", action="store_true", help="Return machine-readable output.")

    export = subparsers.add_parser("export", help="Export memories to json or jsonl.")
    export.add_argument("--scope")
    export.add_argument("--kind", choices=VALID_KINDS)
    export.add_argument("--tags", nargs="*", default=[])
    export.add_argument("--limit", type=int)
    export.add_argument("--format", choices=("json", "jsonl"), default="json")
    export.add_argument("--output", help="Write export to a file instead of stdout.")

    import_command = subparsers.add_parser("import", help="Import memories from json or jsonl.")
    import_command.add_argument("--file", required=True, help="Path to an export file.")
    import_command.add_argument(
        "--format",
        choices=("auto", "json", "jsonl"),
        default="auto",
        help="Import file format. Defaults to auto-detect.",
    )
    import_command.add_argument("--json", action="store_true", help="Return machine-readable output.")

    verify = subparsers.add_parser(
        "verify",
        help="Check database integrity (stems, fingerprints, FTS sync).",
    )
    verify.add_argument(
        "--repair",
        action="store_true",
        help="Recompute and fix any mismatches found.",
    )
    verify.add_argument("--json", action="store_true", help="Return machine-readable output.")

    completion = subparsers.add_parser(
        "completion",
        help="Print a shell completion script for memory-kernel.",
    )
    completion.add_argument("shell", choices=("bash", "powershell"))

    serve_mcp = subparsers.add_parser(
        "serve-mcp",
        help="Run an MCP server (stdio) exposing memory to LLM clients.",
    )
    serve_mcp.add_argument(
        "--db-path",
        dest="mcp_db",
        default=None,
        help="Database path for the MCP server (defaults to --db / MEMORY_KERNEL_DB).",
    )

    stats = subparsers.add_parser("stats", help="Show memory statistics.")
    stats.add_argument(
        "--since",
        help="Include recent-activity counts (e.g., '7d' for last seven days, or '2026-04-01').",
    )
    stats.add_argument("--json", action="store_true", help="Return machine-readable output.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    store = MemoryStore(args.db)
    try:
        if args.command == "init":
            store.init()
            print(f"initialized {args.db}")
            return 0

        if args.command == "remember":
            store.init()
            result = store.remember_result(
                MemoryInput(
                    scope=args.scope,
                    kind=args.kind,
                    title=args.title,
                    content=args.content,
                    summary=args.summary,
                    tags=args.tags,
                    source=args.source,
                    importance=args.importance,
                    certainty=args.certainty,
                )
            )
            payload = {
                "id": result.id,
                "scope": result.scope,
                "kind": result.kind,
                "title": result.title,
                "action": result.action,
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"{result.action} {result.id} [{result.kind}/{result.scope}] {result.title}")
            return 0

        if args.command == "ingest":
            if args.interactive:
                if args.text or args.file:
                    print(
                        "ingest: --interactive cannot be combined with --text or --file",
                        file=sys.stderr,
                    )
                    return 1
                return _run_interactive_ingest(store, args)

            if not args.scope:
                print("ingest: --scope is required (or use --interactive)", file=sys.stderr)
                return 1
            if not args.text and not args.file:
                print(
                    "ingest: provide --text or --file (or use --interactive)",
                    file=sys.stderr,
                )
                return 1

            if args.file:
                input_path = Path(args.file)
                text = input_path.read_text(encoding="utf-8-sig")
                source = args.source or str(input_path)
            else:
                text = args.text
                source = args.source

            if args.dry_run:
                report = store.preview_ingest(
                    text,
                    scope=args.scope,
                    source=source,
                    tags=args.tags,
                    max_items=args.max_items,
                    kind=args.kind,
                    importance=args.importance,
                    certainty=args.certainty,
                )
                if args.json:
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    _print_dry_run_report(report)
                return 0

            store.init()
            report = store.ingest_text(
                text,
                scope=args.scope,
                source=source,
                tags=args.tags,
                max_items=args.max_items,
                kind=args.kind,
                importance=args.importance,
                certainty=args.certainty,
            )
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                _print_ingest_report(report)
            return 0

        if args.command == "search":
            results = store.search(
                args.query,
                limit=args.limit,
                scope=args.scope,
                kind=args.kind,
                tags=args.tags,
            )
            if args.json:
                print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))
            else:
                _print_results(results)
            return 0

        if args.command == "context":
            pack = store.build_context_pack(
                args.query,
                budget_chars=args.budget_chars,
                limit=args.limit,
                scope=args.scope,
                kind=args.kind,
                tags=args.tags,
            )
            if args.json:
                print(json.dumps(pack, ensure_ascii=False, indent=2))
            else:
                print(pack["rendered"])
            return 0

        if args.command == "wake-up":
            pack = store.build_wake_up_pack(
                budget_chars=args.budget_chars,
                limit=args.limit,
                scope=args.scope,
            )
            if args.json:
                print(json.dumps(pack, ensure_ascii=False, indent=2))
            else:
                print(pack["rendered"])
            return 0

        if args.command == "list":
            records = store.list_memories(
                scope=args.scope,
                kind=args.kind,
                tags=args.tags,
                limit=args.limit,
                include_archived=args.include_archived,
            )
            if args.json:
                print(json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2))
            else:
                _print_list(records)
            return 0

        if args.command == "show":
            record = store.get_memory(args.memory_id)
            if record is None:
                print(f"memory not found: {args.memory_id}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
            else:
                _print_record(record)
            return 0

        if args.command == "update":
            update_kwargs = {
                key: value
                for key, value in {
                    "scope": args.scope,
                    "kind": args.kind,
                    "title": args.title,
                    "content": args.content,
                    "summary": args.summary,
                    "tags": args.tags,
                    "source": args.source,
                    "importance": args.importance,
                    "certainty": args.certainty,
                }.items()
                if value is not None
            }
            if not update_kwargs:
                print("update: at least one field must be provided", file=sys.stderr)
                return 1
            try:
                record = store.update_memory(args.memory_id, **update_kwargs)
            except KeyError as exc:
                print(str(exc).strip("'"), file=sys.stderr)
                return 1
            except ValueError as exc:
                print(f"update: {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(f"updated {record.id} [{record.kind}/{record.scope}] {record.title}")
            return 0

        if args.command == "delete":
            deleted = store.delete_memory(args.memory_id)
            if not deleted:
                print(f"memory not found: {args.memory_id}", file=sys.stderr)
                return 1
            payload = {"id": args.memory_id, "action": "deleted"}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"deleted {args.memory_id}")
            return 0

        if args.command == "forget":
            ok = store.archive_memory(args.memory_id)
            if not ok:
                print(f"memory not found: {args.memory_id}", file=sys.stderr)
                return 1
            payload = {"id": args.memory_id, "action": "archived"}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"archived {args.memory_id} (recover with: restore --id {args.memory_id})")
            return 0

        if args.command == "restore":
            ok = store.restore_memory(args.memory_id)
            if not ok:
                print(f"memory not found: {args.memory_id}", file=sys.stderr)
                return 1
            payload = {"id": args.memory_id, "action": "restored"}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"restored {args.memory_id}")
            return 0

        if args.command == "revise":
            try:
                record = store.revise_memory(args.memory_id, args.superseded_id)
            except KeyError as exc:
                print(str(exc).strip("'"), file=sys.stderr)
                return 1
            except ValueError as exc:
                print(f"revise: {exc}", file=sys.stderr)
                return 1
            payload = {
                "superseded_id": record.id,
                "superseded_by": args.memory_id,
                "action": "superseded",
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"{record.id} is now superseded by {args.memory_id}")
            return 0

        if args.command == "decay":
            decay_kwargs: dict = {"dry_run": args.dry_run, "scope": args.scope}
            if args.min_age_days is not None:
                decay_kwargs["min_age_days"] = args.min_age_days
            if args.max_access is not None:
                decay_kwargs["max_access"] = args.max_access
            if args.threshold is not None:
                decay_kwargs["threshold"] = args.threshold
            report = store.decay(**decay_kwargs)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                _print_decay_report(report)
            return 0

        if args.command == "export":
            memories = store.export_memories(
                scope=args.scope,
                kind=args.kind,
                tags=args.tags,
                limit=args.limit,
            )
            rendered = _render_export(
                memories=memories,
                export_format=args.format,
                database_path=Path(args.db),
                scope=args.scope,
                kind=args.kind,
                tags=args.tags,
                limit=args.limit,
            )
            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(rendered, encoding="utf-8")
                print(f"exported {len(memories)} memories to {output_path}")
            elif rendered:
                print(rendered, end="" if rendered.endswith("\n") else "\n")
            return 0

        if args.command == "import":
            input_path = Path(args.file)
            memories = _load_import_memories(input_path, args.format)
            report = store.import_memories(memories)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                _print_import_report(report, input_path)
            return 0

        if args.command == "completion":
            if args.shell == "bash":
                print(_build_bash_completion(parser))
            else:
                print(_build_powershell_completion(parser))
            return 0

        if args.command == "serve-mcp":
            try:
                from .mcp_server import run_server
            except ImportError:
                print(
                    "serve-mcp requires the 'mcp' package. "
                    "Install it with: pip install amormorri-memory-kernel[mcp]",
                    file=sys.stderr,
                )
                return 1
            run_server(db_path=args.mcp_db or args.db)
            return 0

        if args.command == "verify":
            report = store.verify(repair=args.repair)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                _print_verify(report)
            return 0 if report["healthy"] else 1

        if args.command == "stats":
            since = None
            if args.since:
                try:
                    since = _parse_since(args.since)
                except ValueError as exc:
                    print(f"stats: {exc}", file=sys.stderr)
                    return 1
            payload = store.stats(since=since)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"database: {payload['database']}")
                print(f"accelerator: {payload['accelerator']}")
                print(f"ranking engine: {payload['ranking_engine']}")
                print(f"upsert engine: {payload['upsert_engine']}")
                print(f"total memories: {payload['total_memories']}")
                print("by kind:")
                for kind, count in payload["by_kind"].items():
                    print(f"  - {kind}: {count}")
                print("top scopes:")
                for scope, count in payload["top_scopes"].items():
                    print(f"  - {scope}: {count}")
                if "since" in payload:
                    print()
                    print(f"since: {payload['since']}")
                    print(f"  created: {payload['created_since']}")
                    print(f"  updated: {payload['updated_since']}")
                    if payload["by_kind_since"]:
                        print("  by kind:")
                        for kind, count in payload["by_kind_since"].items():
                            print(f"    - {kind}: {count}")
            return 0

        parser.error("unknown command")
        return 1
    finally:
        store.close()


def _print_results(results: Sequence) -> None:
    if not results:
        print("no memories found")
        return

    for index, item in enumerate(results, start=1):
        print(f"[{index}] {item.id} [{item.kind}/{item.scope}] {item.title}")
        print(f"    score={item.score} importance={item.importance} certainty={item.certainty}")
        if item.tags:
            print(f"    tags={', '.join(item.tags)}")
        if item.source:
            print(f"    source={item.source}")
        print(f"    {item.excerpt}")


def _collect_subcommand_metadata(parser: argparse.ArgumentParser) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    subparsers_action = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)),
        None,
    )
    if subparsers_action is None:
        return metadata
    for name, sub in subparsers_action.choices.items():
        flags: list[str] = []
        choices_for_flag: dict[str, list[str]] = {}
        for action in sub._actions:
            for opt in action.option_strings:
                if opt.startswith("--") and opt not in flags:
                    flags.append(opt)
                    if action.choices is not None:
                        choices_for_flag[opt] = [str(c) for c in action.choices]
        metadata[name] = {"flags": sorted(flags), "choices": choices_for_flag}
    return metadata


def _build_bash_completion(parser: argparse.ArgumentParser) -> str:
    metadata = _collect_subcommand_metadata(parser)
    subcommands = " ".join(metadata.keys())

    branches: list[str] = []
    for name, info in metadata.items():
        flags_line = " ".join(info["flags"])
        choice_cases = []
        for flag, values in sorted(info["choices"].items()):
            values_line = " ".join(values)
            choice_cases.append(
                f'                {flag})\n'
                f'                    COMPREPLY=( $(compgen -W "{values_line}" -- "${{cur}}") )\n'
                f'                    return 0\n'
                f'                    ;;'
            )
        choice_block = "\n".join(choice_cases)
        choice_section = (
            f"            case \"${{prev}}\" in\n{choice_block}\n            esac\n"
            if choice_block
            else ""
        )
        branches.append(
            f"        {name})\n"
            f"{choice_section}"
            f"            if [[ \"${{cur}}\" == --* ]]; then\n"
            f"                COMPREPLY=( $(compgen -W \"{flags_line}\" -- \"${{cur}}\") )\n"
            f"            fi\n"
            f"            ;;"
        )

    case_block = "\n".join(branches)
    return (
        "# bash completion for memory-kernel — generated by `memory-kernel completion bash`\n"
        "_memory_kernel_complete() {\n"
        "    local cur prev cmd\n"
        "    COMPREPLY=()\n"
        "    cur=\"${COMP_WORDS[COMP_CWORD]}\"\n"
        "    prev=\"${COMP_WORDS[COMP_CWORD-1]}\"\n"
        "\n"
        "    if [[ ${COMP_CWORD} -eq 1 ]]; then\n"
        f"        COMPREPLY=( $(compgen -W \"{subcommands}\" -- \"${{cur}}\") )\n"
        "        return 0\n"
        "    fi\n"
        "\n"
        "    cmd=\"${COMP_WORDS[1]}\"\n"
        "    case \"${cmd}\" in\n"
        f"{case_block}\n"
        "    esac\n"
        "}\n"
        "complete -F _memory_kernel_complete memory-kernel\n"
    )


def _build_powershell_completion(parser: argparse.ArgumentParser) -> str:
    metadata = _collect_subcommand_metadata(parser)
    subcommand_array = ", ".join(f"'{name}'" for name in metadata.keys())

    branches: list[str] = []
    for name, info in metadata.items():
        flags_array = ", ".join(f"'{flag}'" for flag in info["flags"])
        choice_cases = []
        for flag, values in sorted(info["choices"].items()):
            values_array = ", ".join(f"'{v}'" for v in values)
            choice_cases.append(
                f"            '{flag}' {{\n"
                f"                @({values_array}) | Where-Object {{ $_ -like \"$wordToComplete*\" }} |\n"
                f"                    ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }}\n"
                f"                return\n"
                f"            }}"
            )
        choice_block = "\n".join(choice_cases)
        choice_section = (
            f"        switch ($previous) {{\n{choice_block}\n        }}\n"
            if choice_block
            else ""
        )
        branches.append(
            f"    '{name}' {{\n"
            f"{choice_section}"
            f"        @({flags_array}) | Where-Object {{ $_ -like \"$wordToComplete*\" }} |\n"
            f"            ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_) }}\n"
            f"        return\n"
            f"    }}"
        )

    case_block = "\n".join(branches)
    return (
        "# PowerShell completion for memory-kernel — generated by `memory-kernel completion powershell`\n"
        "Register-ArgumentCompleter -Native -CommandName memory-kernel -ScriptBlock {\n"
        "    param($wordToComplete, $commandAst, $cursorPosition)\n"
        "\n"
        "    $tokens = @($commandAst.CommandElements | ForEach-Object { $_.ToString() })\n"
        "    $previous = if ($tokens.Count -ge 2) { $tokens[-2] } else { '' }\n"
        "\n"
        "    if ($tokens.Count -le 2) {\n"
        f"        @({subcommand_array}) | Where-Object {{ $_ -like \"$wordToComplete*\" }} |\n"
        "            ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }\n"
        "        return\n"
        "    }\n"
        "\n"
        "    $cmd = $tokens[1]\n"
        "    switch ($cmd) {\n"
        f"{case_block}\n"
        "    }\n"
        "}\n"
    )


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{label}{suffix}: ").strip()
    return raw if raw else default


def _prompt_yes_no(question: str) -> bool:
    raw = input(f"{question} [y/N]: ").strip().lower()
    return raw.startswith("y")


def _read_multiline() -> str:
    print(
        "Paste your text below. Press Ctrl+D (Linux/macOS) or Ctrl+Z then Enter (Windows) to finish:",
        file=sys.stderr,
    )
    lines: list[str] = []
    while True:
        try:
            lines.append(input())
        except EOFError:
            break
    return "\n".join(lines)


def _run_interactive_ingest(store: MemoryStore, args: argparse.Namespace) -> int:
    scope = _prompt("Scope", default=args.scope or "")
    if not scope:
        print("ingest: scope is required", file=sys.stderr)
        return 1

    source = _prompt("Source (optional)", default=args.source or "")
    tags_raw = _prompt("Tags (space-separated, optional)", default=" ".join(args.tags or ()))
    tags = tags_raw.split() if tags_raw else []

    text = _read_multiline()
    if not text.strip():
        print("ingest: no text provided", file=sys.stderr)
        return 1

    preview = store.preview_ingest(
        text,
        scope=scope,
        source=source,
        tags=tags,
        max_items=args.max_items,
        kind=args.kind,
        importance=args.importance,
        certainty=args.certainty,
    )
    if preview["segments"] == 0:
        print("ingest: no valid segments found in input", file=sys.stderr)
        return 1

    print()
    _print_dry_run_report(preview)
    print()

    if not _prompt_yes_no(f"Save these {preview['segments']} memories?"):
        print("ingest: cancelled")
        return 0

    report = store.ingest_text(
        text,
        scope=scope,
        source=source,
        tags=tags,
        max_items=args.max_items,
        kind=args.kind,
        importance=args.importance,
        certainty=args.certainty,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_ingest_report(report)
    return 0


def _parse_since(value: str) -> datetime:
    value = value.strip()
    if not value:
        raise ValueError("--since must not be empty")
    relative = _SINCE_RELATIVE_RE.match(value)
    if relative:
        days = int(relative.group(1))
        return datetime.now(timezone.utc) - timedelta(days=days)
    try:
        parsed = parse_timestamp(value)
    except ValueError as exc:
        raise ValueError(
            f"--since must be like '7d' or an ISO timestamp, got {value!r}"
        ) from exc
    if parsed is None:
        raise ValueError(f"--since must be like '7d' or an ISO timestamp, got {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _print_verify(report: dict) -> None:
    print(f"checked: {report['checked_memories']} memories")
    if report["healthy"]:
        print("healthy: yes")
        if report.get("repaired_stems") or report.get("repaired_fingerprints") or report.get("rebuilt_fts"):
            print(
                f"repaired: stems={report.get('repaired_stems', 0)} "
                f"fingerprints={report.get('repaired_fingerprints', 0)} "
                f"fts_rebuilt={report.get('rebuilt_fts', False)}"
            )
        return
    print("healthy: no")
    if report["schema_issue"]:
        print(f"  schema: {report['schema_issue']}")
    if report["stems_text_mismatches"]:
        print(f"  stems_text mismatches: {len(report['stems_text_mismatches'])}")
        for memory_id in report["stems_text_mismatches"][:5]:
            print(f"    - {memory_id}")
        if len(report["stems_text_mismatches"]) > 5:
            print(f"    ... and {len(report['stems_text_mismatches']) - 5} more")
    if report["fingerprint_mismatches"]:
        print(f"  fingerprint mismatches: {len(report['fingerprint_mismatches'])}")
        for memory_id in report["fingerprint_mismatches"][:5]:
            print(f"    - {memory_id}")
        if len(report["fingerprint_mismatches"]) > 5:
            print(f"    ... and {len(report['fingerprint_mismatches']) - 5} more")
    if report["fts_count_mismatch"]:
        mismatch = report["fts_count_mismatch"]
        print(f"  fts count mismatch: memories={mismatch['memories']} fts={mismatch['fts']}")
    if "repaired_stems" in report:
        print(
            f"repaired: stems={report['repaired_stems']} "
            f"fingerprints={report['repaired_fingerprints']} "
            f"fts_rebuilt={report['rebuilt_fts']}"
        )
    print("hint: re-run with --repair to fix automatically")


def _print_list(records: Sequence[MemoryRecord]) -> None:
    if not records:
        print("no memories found")
        return
    for record in records:
        status = ""
        if record.superseded_by:
            status = f"  (superseded by {record.superseded_by})"
        elif record.archived_at:
            status = "  (archived)"
        print(f"{record.id} [{record.kind}/{record.scope}] {record.title}{status}")
        print(
            f"    updated_at={record.updated_at}"
            f"  importance={record.importance}  certainty={record.certainty}"
        )
        if record.tags:
            print(f"    tags={', '.join(record.tags)}")


def _print_decay_report(report: dict) -> None:
    verb = "would archive" if report["dry_run"] else "archived"
    print(
        f"scanned {report['scanned']} decayable memories, "
        f"{verb} {len(report['items'])} "
        f"(min_age_days={report['min_age_days']}, max_access={report['max_access']}, "
        f"threshold={report['threshold']})"
    )
    for item in report["items"]:
        print(
            f"  - {item['id']} [{item['kind']}/{item['scope']}] {item['title']}"
            f"  retention={item['retention']} age_days={item['age_days']}"
        )
    if report["dry_run"] and report["items"]:
        print("run without --dry-run to archive these (recoverable with restore).")


def _print_record(record: MemoryRecord) -> None:
    print(f"id: {record.id}")
    print(f"scope: {record.scope}")
    print(f"kind: {record.kind}")
    print(f"title: {record.title}")
    print(f"summary: {record.summary}")
    print(f"importance: {record.importance}  certainty: {record.certainty}")
    if record.tags:
        print(f"tags: {', '.join(record.tags)}")
    if record.source:
        print(f"source: {record.source}")
    print(f"created_at: {record.created_at}")
    print(f"updated_at: {record.updated_at}")
    if record.last_accessed_at:
        print(f"last_accessed_at: {record.last_accessed_at}")
    print(f"access_count: {record.access_count}")
    if record.archived_at:
        print(f"archived_at: {record.archived_at}")
    if record.superseded_by:
        print(f"superseded_by: {record.superseded_by}")
    print()
    print("content:")
    print(record.content)


def _print_ingest_report(report: dict) -> None:
    print(
        f"ingested {report['stored']} memories "
        f"({report['created']} created, {report['updated']} updated)"
    )
    for item in report["items"]:
        print(f"  - {item['action']}: [{item['kind']}/{report['scope']}] {item['title']}")


def _print_dry_run_report(report: dict) -> None:
    print(f"would ingest {report['segments']} segments into {report['scope']}")
    for index, item in enumerate(report["items"], start=1):
        print(f"  [{index}] [{item['kind']}] {item['title']}")
        print(
            f"        importance={item['importance']}  certainty={item['certainty']}"
        )
        if item["tags"]:
            print(f"        tags={', '.join(item['tags'])}")
        if item["summary"]:
            print(f"        summary: {item['summary']}")


def _render_export(
    *,
    memories: Sequence[dict],
    export_format: str,
    database_path: Path,
    scope: str | None,
    kind: str | None,
    tags: Sequence[str],
    limit: int | None,
) -> str:
    if export_format == "jsonl":
        if not memories:
            return ""
        return "\n".join(json.dumps(item, ensure_ascii=False) for item in memories) + "\n"

    payload = {
        "version": 1,
        "exported_at": utc_now_iso(),
        "database": str(database_path),
        "count": len(memories),
        "filters": {
            "scope": scope,
            "kind": kind,
            "tags": list(tags),
            "limit": limit,
        },
        "memories": list(memories),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _load_import_memories(path: Path, file_format: str) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    resolved_format = _resolve_import_format(path, file_format)
    if resolved_format == "jsonl":
        return [
            json.loads(line)
            for line in text.splitlines()
            if line.strip()
        ]

    payload = json.loads(text)
    if isinstance(payload, dict) and "memories" in payload:
        memories = payload["memories"]
    elif isinstance(payload, list):
        memories = payload
    elif isinstance(payload, dict):
        memories = [payload]
    else:
        raise ValueError("json import must be an object, a list, or an export snapshot")

    if not isinstance(memories, list):
        raise ValueError("import payload must contain a list of memories")
    return memories


def _resolve_import_format(path: Path, file_format: str) -> str:
    if file_format != "auto":
        return file_format
    if path.suffix.lower() == ".jsonl":
        return "jsonl"
    return "json"


def _print_import_report(report: dict, input_path: Path) -> None:
    print(
        f"imported {report['stored']} memories from {input_path} "
        f"({report['created']} created, {report['updated']} updated)"
    )
    for item in report["items"]:
        print(f"  - {item['action']}: [{item['kind']}/{item['scope']}] {item['title']}")


if __name__ == "__main__":
    raise SystemExit(main())
