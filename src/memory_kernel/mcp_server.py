#!/usr/bin/env python3
"""MCP server for Memory Kernel.

Exposes the local memory store to MCP-compatible clients (Claude Desktop,
Claude Code, Cursor, ...) over stdio so an LLM can save and recall memories
during a session.

The server is intentionally read-mostly: it exposes saving, recall, and a
reversible soft-forget, but not destructive edits. Deleting or rewriting
memories stays in the human-driven CLI (`memory-kernel delete` / `update` /
`revise`), in line with the project's inspect / control / trust philosophy.

Tools take flat parameters (not a nested object) so the model sees each field
directly in the tool schema.

Database path resolution (first match wins):
  1. the path passed to ``run_server`` / the ``--db`` CLI flag
  2. the ``MEMORY_KERNEL_DB`` environment variable
  3. ``.memory-kernel/memory.db`` relative to the working directory
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional, Sequence

from pydantic import Field

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised via friendly CLI error
    raise ImportError(
        "The 'mcp' package is required to run the Memory Kernel MCP server. "
        "Install it with: pip install amormorri-memory-kernel[mcp]"
    ) from exc

from .store import VALID_KINDS, MemoryInput, MemoryRecord, MemoryStore

DEFAULT_DB_PATH = Path(".memory-kernel") / "memory.db"

mcp = FastMCP("memory_kernel_mcp")

# Set by run_server(); falls back to env var / default when None.
_db_override: Optional[Path] = None


def _resolve_db_path() -> Path:
    if _db_override is not None:
        return _db_override
    return Path(os.getenv("MEMORY_KERNEL_DB", str(DEFAULT_DB_PATH)))


def _open_store() -> MemoryStore:
    """Open a short-lived store for a single tool call.

    A fresh connection per call keeps SQLite access thread-safe regardless of
    how the MCP framework schedules tool execution.
    """
    return MemoryStore(_resolve_db_path())


class MemoryKind(str, Enum):
    """Allowed memory kinds, mirroring VALID_KINDS in the store."""

    decision = "decision"
    constraint = "constraint"
    preference = "preference"
    task = "task"
    fact = "fact"
    note = "note"


class ResponseFormat(str, Enum):
    """Output format for read tools."""

    markdown = "markdown"
    json = "json"


assert {k.value for k in MemoryKind} == set(VALID_KINDS), (
    "MemoryKind enum is out of sync with store.VALID_KINDS"
)


def _parse_since(value: str) -> datetime:
    value = value.strip()
    if not value:
        raise ValueError("since must not be empty")
    if value.endswith("d") and value[:-1].isdigit():
        days = int(value[:-1])
        return datetime.now(timezone.utc) - timedelta(days=days)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"since must be like '7d' or an ISO timestamp, got {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _record_to_markdown(record: MemoryRecord, *, include_excerpt: bool) -> str:
    body = record.excerpt if (include_excerpt and record.excerpt) else record.content
    lines = [f"- **{record.title}**  `[{record.kind}/{record.scope}]`  id=`{record.id}`"]
    lines.append(f"  {body}")
    meta = f"  importance={record.importance} certainty={record.certainty} updated={record.updated_at}"
    if record.tags:
        meta += f" tags={', '.join(record.tags)}"
    lines.append(meta)
    return "\n".join(lines)


def _records_to_response(
    records: Sequence[MemoryRecord],
    response_format: ResponseFormat,
    *,
    header: str,
    include_excerpt: bool,
) -> str:
    if response_format == ResponseFormat.json:
        return json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2)
    if not records:
        return f"{header}\n\n(no memories found)"
    blocks = [header, ""]
    blocks.extend(_record_to_markdown(r, include_excerpt=include_excerpt) for r in records)
    return "\n".join(blocks)


def _error(exc: Exception) -> str:
    return f"Error: unexpected {type(exc).__name__}: {exc}"


@mcp.tool(
    name="memory_remember",
    annotations={
        "title": "Save a precise memory",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def memory_remember(
    scope: Annotated[str, Field(description="Namespace for the memory, e.g. 'project.alpha' or 'user.preferences'.", min_length=1, max_length=200)],
    kind: Annotated[MemoryKind, Field(description="Memory type: decision, constraint, preference, task, fact, or note.")],
    title: Annotated[str, Field(description="Short headline for the memory.", min_length=1, max_length=200)],
    content: Annotated[str, Field(description="Full memory text.", min_length=1, max_length=10000)],
    summary: Annotated[str, Field(description="Optional one-line summary; derived if empty.", max_length=500)] = "",
    tags: Annotated[Optional[list[str]], Field(description="Optional tags for filtering.")] = None,
    source: Annotated[str, Field(description="Optional provenance, e.g. 'session-2026-05-12'.", max_length=200)] = "",
    importance: Annotated[float, Field(description="Importance 0.0-1.0.", ge=0.0, le=1.0)] = 0.5,
    certainty: Annotated[float, Field(description="Confidence 0.0-1.0.", ge=0.0, le=1.0)] = 0.7,
) -> str:
    """Save one well-formed memory to the local store.

    Use this when you already know exactly what to remember (a decision, a
    constraint, a user preference, a fact). The store deduplicates: saving the
    same memory again merges into the existing record, so repeated calls are safe.

    Returns a confirmation with the stored memory id and whether it was
    'created' or 'updated'. On failure: "Error: <message>".
    """
    try:
        with _open_store() as store:
            result = store.remember_result(
                MemoryInput(
                    scope=scope,
                    kind=kind.value,
                    title=title,
                    content=content,
                    summary=summary,
                    tags=tuple(tags or ()),
                    source=source,
                    importance=importance,
                    certainty=certainty,
                )
            )
        return f"{result.action} {result.id} [{result.kind}/{result.scope}] {result.title}"
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return _error(exc)


@mcp.tool(
    name="memory_ingest",
    annotations={
        "title": "Ingest raw text into structured memories",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def memory_ingest(
    text: Annotated[str, Field(description="Raw notes/transcript to split into memories.", min_length=1, max_length=50000)],
    scope: Annotated[str, Field(description="Namespace for the resulting memories.", min_length=1, max_length=200)],
    source: Annotated[str, Field(description="Optional provenance for all extracted memories.", max_length=200)] = "",
    tags: Annotated[Optional[list[str]], Field(description="Base tags applied to every memory.")] = None,
    max_items: Annotated[int, Field(description="Maximum memories to extract.", ge=1, le=100)] = 24,
    kind: Annotated[Optional[MemoryKind], Field(description="Force a kind for all memories; inferred per-segment when omitted.")] = None,
) -> str:
    """Split raw notes or a transcript into structured memories and save them.

    Use this to capture a chunk of conversation, meeting notes, or planning text
    without structuring it yourself. Each segment gets an inferred kind, title,
    tags, importance, and certainty. Deduplication applies per segment.

    Returns a summary of how many memories were stored (created vs updated)
    followed by one line per memory. On failure: "Error: <message>".
    """
    try:
        with _open_store() as store:
            report = store.ingest_text(
                text,
                scope=scope,
                source=source,
                tags=tuple(tags or ()),
                max_items=max_items,
                kind=kind.value if kind else None,
            )
        lines = [
            f"ingested {report['stored']} memories "
            f"({report['created']} created, {report['updated']} updated) into {report['scope']}"
        ]
        for item in report["items"]:
            lines.append(f"  - {item['action']}: {item['id']} [{item['kind']}] {item['title']}")
        return "\n".join(lines)
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return _error(exc)


@mcp.tool(
    name="memory_forget",
    annotations={
        "title": "Archive (soft-forget) a memory",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def memory_forget(
    memory_id: Annotated[str, Field(description="Id of the memory to archive.", min_length=1, max_length=64)],
) -> str:
    """Archive a memory so it stops surfacing in recall, while keeping it recoverable.

    This is a soft forget, not a delete: the memory is hidden from search,
    context, wake-up, and list, but the data is preserved and a human can bring
    it back from the CLI (`memory-kernel restore`). Use this when a memory is
    stale or no longer relevant. Hard deletion is not available over MCP.

    Returns a confirmation, or a not-found message. On failure: "Error: <message>".
    """
    try:
        with _open_store() as store:
            ok = store.archive_memory(memory_id)
        if not ok:
            return f"memory not found: {memory_id}"
        return f"archived {memory_id} (recoverable via CLI: memory-kernel restore --id {memory_id})"
    except Exception as exc:  # pragma: no cover - defensive
        return _error(exc)


@mcp.tool(
    name="memory_search",
    annotations={
        "title": "Search memories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def memory_search(
    query: Annotated[str, Field(description="Search text. Ukrainian word forms are bridged by stemming.", min_length=1, max_length=500)],
    limit: Annotated[int, Field(description="Maximum results.", ge=1, le=50)] = 5,
    scope: Annotated[Optional[str], Field(description="Restrict to this scope.", max_length=200)] = None,
    kind: Annotated[Optional[MemoryKind], Field(description="Restrict to this kind.")] = None,
    tags: Annotated[Optional[list[str]], Field(description="Require these tags.")] = None,
    response_format: Annotated[ResponseFormat, Field(description="'markdown' for human/LLM-readable, 'json' for structured data.")] = ResponseFormat.markdown,
) -> str:
    """Find the few memories most relevant to a query.

    Ranking is deterministic (lexical match, importance, certainty, recency,
    access frequency). Ukrainian inflections are bridged: a query like 'рішення'
    also matches stored 'вирішили'. Archived and superseded memories are excluded.

    Returns a markdown list (title, kind/scope, id, excerpt, metadata) or a JSON
    array of full memory records. On failure: "Error: <message>".
    """
    try:
        with _open_store() as store:
            records = store.search(
                query,
                limit=limit,
                scope=scope,
                kind=kind.value if kind else None,
                tags=tuple(tags or ()),
            )
        return _records_to_response(
            records,
            response_format,
            header=f"# Search results for: {query}",
            include_excerpt=True,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return _error(exc)


@mcp.tool(
    name="memory_build_context",
    annotations={
        "title": "Build a context pack",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def memory_build_context(
    query: Annotated[str, Field(description="What the agent is about to work on.", min_length=1, max_length=500)],
    budget_chars: Annotated[int, Field(description="Hard character budget for the pack.", ge=100, le=20000)] = 1200,
    limit: Annotated[int, Field(description="Maximum memories in the pack.", ge=1, le=50)] = 5,
    scope: Annotated[Optional[str], Field(description="Restrict to this scope.", max_length=200)] = None,
    kind: Annotated[Optional[MemoryKind], Field(description="Restrict to this kind.")] = None,
    tags: Annotated[Optional[list[str]], Field(description="Require these tags.")] = None,
) -> str:
    """Assemble a compact, budget-limited context pack for the current task.

    Returns a single rendered block sized to fit ``budget_chars`` that you can
    drop straight into a prompt. Near-duplicate memories are dropped so the pack
    carries distinct signal. Prefer this over raw search when you want a
    ready-to-inject summary rather than a list to reason over.

    Returns a JSON object with 'budget_chars', 'used_chars', 'items', and
    'rendered' (the text block to inject). On failure: "Error: <message>".
    """
    try:
        with _open_store() as store:
            pack = store.build_context_pack(
                query,
                budget_chars=budget_chars,
                limit=limit,
                scope=scope,
                kind=kind.value if kind else None,
                tags=tuple(tags or ()),
            )
        return json.dumps(pack, ensure_ascii=False, indent=2)
    except Exception as exc:  # pragma: no cover - defensive
        return _error(exc)


@mcp.tool(
    name="memory_wake_up",
    annotations={
        "title": "Build a wake-up pack",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def memory_wake_up(
    budget_chars: Annotated[int, Field(description="Hard character budget.", ge=100, le=20000)] = 800,
    limit: Annotated[int, Field(description="Maximum memories.", ge=1, le=50)] = 6,
    scope: Annotated[Optional[str], Field(description="Restrict to this scope.", max_length=200)] = None,
) -> str:
    """Build a small 'hot memory' pack to load at the start of a session.

    Returns the most important/certain/recent memories with no query, sized to
    ``budget_chars``. Use this once when a session begins to prime the agent.

    Returns a JSON object with 'budget_chars', 'used_chars', 'items', and
    'rendered'. On failure: "Error: <message>".
    """
    try:
        with _open_store() as store:
            pack = store.build_wake_up_pack(
                budget_chars=budget_chars,
                limit=limit,
                scope=scope,
            )
        return json.dumps(pack, ensure_ascii=False, indent=2)
    except Exception as exc:  # pragma: no cover - defensive
        return _error(exc)


@mcp.tool(
    name="memory_list",
    annotations={
        "title": "List recent memories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def memory_list(
    scope: Annotated[Optional[str], Field(description="Restrict to this scope.", max_length=200)] = None,
    kind: Annotated[Optional[MemoryKind], Field(description="Restrict to this kind.")] = None,
    tags: Annotated[Optional[list[str]], Field(description="Require these tags.")] = None,
    limit: Annotated[int, Field(description="Maximum results.", ge=1, le=100)] = 20,
    response_format: Annotated[ResponseFormat, Field(description="'markdown' or 'json'.")] = ResponseFormat.markdown,
) -> str:
    """List recent memories (most recently updated first) with optional filters.

    Use this to browse what is stored rather than to answer a specific query.
    Archived and superseded memories are excluded.

    Returns a markdown list or JSON array of memory records. On failure:
    "Error: <message>".
    """
    try:
        with _open_store() as store:
            records = store.list_memories(
                scope=scope,
                kind=kind.value if kind else None,
                tags=tuple(tags or ()),
                limit=limit,
            )
        return _records_to_response(
            records,
            response_format,
            header="# Recent memories",
            include_excerpt=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return _error(exc)


@mcp.tool(
    name="memory_stats",
    annotations={
        "title": "Memory store statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def memory_stats(
    since: Annotated[Optional[str], Field(description="Optional window for recent-activity counts: '7d' style or an ISO date.", max_length=40)] = None,
    response_format: Annotated[ResponseFormat, Field(description="'markdown' or 'json'.")] = ResponseFormat.markdown,
) -> str:
    """Report store statistics: total count, breakdown by kind and scope.

    Pass ``since`` ('7d' or an ISO date) to also get recent-activity counts.

    Returns a markdown summary or JSON object with totals and breakdowns. On
    failure: "Error: <message>".
    """
    try:
        parsed_since = _parse_since(since) if since else None
    except ValueError as exc:
        return f"Error: {exc}"
    try:
        with _open_store() as store:
            payload = store.stats(since=parsed_since)
    except Exception as exc:  # pragma: no cover - defensive
        return _error(exc)

    if response_format == ResponseFormat.json:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [
        "# Memory store stats",
        "",
        f"- database: {payload['database']}",
        f"- accelerator: {payload['accelerator']}",
        f"- total memories: {payload['total_memories']}",
        "- by kind:",
    ]
    for kind, count in payload["by_kind"].items():
        lines.append(f"  - {kind}: {count}")
    lines.append("- top scopes:")
    for scope, count in payload["top_scopes"].items():
        lines.append(f"  - {scope}: {count}")
    if "since" in payload:
        lines.append("")
        lines.append(f"- since {payload['since']}: {payload['created_since']} created, {payload['updated_since']} updated")
    return "\n".join(lines)


def run_server(db_path: Optional[str | Path] = None) -> None:
    """Run the MCP server over stdio.

    Args:
        db_path: Optional explicit database path. When omitted, the server uses
            the MEMORY_KERNEL_DB environment variable or the default location.
    """
    global _db_override
    if db_path is not None:
        _db_override = Path(db_path)
    mcp.run()


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="memory-kernel-mcp",
        description="Run the Memory Kernel MCP server (stdio transport).",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to the SQLite database (overrides MEMORY_KERNEL_DB).",
    )
    args = parser.parse_args(argv)
    run_server(db_path=args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
