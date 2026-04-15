from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .store import MemoryInput, MemoryStore, VALID_KINDS, utc_now_iso


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
    ingest.add_argument("--scope", required=True)
    ingest_source = ingest.add_mutually_exclusive_group(required=True)
    ingest_source.add_argument("--text")
    ingest_source.add_argument("--file")
    ingest.add_argument("--source", default="")
    ingest.add_argument("--kind", choices=VALID_KINDS)
    ingest.add_argument("--tags", nargs="*", default=[])
    ingest.add_argument("--max-items", type=int, default=24)
    ingest.add_argument("--importance", type=float)
    ingest.add_argument("--certainty", type=float)
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

    stats = subparsers.add_parser("stats", help="Show memory statistics.")
    stats.add_argument("--json", action="store_true", help="Return machine-readable output.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
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
            store.init()
            if args.file:
                input_path = Path(args.file)
                text = input_path.read_text(encoding="utf-8-sig")
                source = args.source or str(input_path)
            else:
                text = args.text
                source = args.source

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

        if args.command == "stats":
            payload = store.stats()
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
        print(f"[{index}] [{item.kind}/{item.scope}] {item.title}")
        print(f"    score={item.score} importance={item.importance} certainty={item.certainty}")
        if item.tags:
            print(f"    tags={', '.join(item.tags)}")
        if item.source:
            print(f"    source={item.source}")
        print(f"    {item.excerpt}")


def _print_ingest_report(report: dict) -> None:
    print(
        f"ingested {report['stored']} memories "
        f"({report['created']} created, {report['updated']} updated)"
    )
    for item in report["items"]:
        print(f"  - {item['action']}: [{item['kind']}/{report['scope']}] {item['title']}")


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
