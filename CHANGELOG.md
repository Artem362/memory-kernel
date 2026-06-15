# Changelog

## 0.3.3 - 2026-06-15

Polish from a live real-AI test session (a model using the MCP server end-to-end).

- `ingest`/classification: the preference idioms "надає перевагу", "віддає перевагу", "надаю перевагу", "волію" now classify as `preference` (previously fell through to `note`). Mirrored in the Rust accelerator.
- `stats` now reports `active_memories` and `archived_memories` alongside `total_memories`, so the count of memories actually surfacing in recall is visible (the total still counts archived/superseded rows). Shown in the CLI and the `memory_stats` MCP tool.

No schema or API breaking changes.

## 0.3.2 - 2026-06-11

- License change: this and future versions are licensed under the Apache License 2.0 (previously the Unlicense). Versions up to and including 0.3.1 remain available under the Unlicense. Added NOTICE and CONTRIBUTING.md (DCO sign-off required for contributions).
- Fixed the MCP Registry `mcp-name` marker to match the case-sensitive namespace (`io.github.Artem362`).

No functional changes.

## 0.3.1 - 2026-06-11

Metadata patch for the official MCP Registry submission.

- README now carries the `mcp-name: io.github.artem362/memory-kernel` verification marker required for PyPI package ownership validation in the [MCP Registry](https://registry.modelcontextprotocol.io).
- New console-script alias `amormorri-memory-kernel` (same as `memory-kernel-mcp`), so `uvx amormorri-memory-kernel` starts the MCP server directly — the invocation MCP clients derive from the registry entry.
- Added `server.json` registry manifest to the repository.

No functional changes.

## 0.3.0 - 2026-06-01

Adds an MCP server so LLM clients can use Memory Kernel directly.

- New `memory-kernel-mcp` console command and `memory-kernel serve-mcp` subcommand run an [MCP](https://modelcontextprotocol.io) server over stdio, compatible with Claude Desktop, Claude Code, Cursor, and other MCP clients.
- Eight tools exposed: `memory_remember`, `memory_ingest`, `memory_forget`, `memory_search`, `memory_build_context`, `memory_wake_up`, `memory_list`, `memory_stats`.
- Tools take flat parameters (the model sees `scope`, `kind`, `title`, ... directly), not a nested object.
- Read tools are annotated `readOnlyHint`; the write tools are non-destructive (dedup-merge, and a reversible soft-forget). Destructive edits (`delete`, `update`, `revise`) are intentionally kept out of the MCP surface and remain CLI-only.
- Verified end-to-end over the real MCP protocol (`scripts/mcp_smoke.py`, `tests/test_mcp_e2e.py`): a client subprocess does the initialize handshake, lists tools, and calls them over stdio JSON-RPC. See `docs/REAL_AI_TEST.md` for connecting Claude Desktop / Claude Code and a hand-test script.
- Database path comes from `--db` / `MEMORY_KERNEL_DB` / the default `.memory-kernel/memory.db`.
- `mcp` is an optional dependency: `pip install "amormorri-memory-kernel[mcp]"`. The core package stays dependency-free.
- README and the Ukrainian operating guide gained an MCP integration section with `claude_desktop_config.json` / `.mcp.json` examples.

Memory that fades and stays lean:

- New `decay` command applies a forgetting curve. Each memory gets a retention score from importance + recall reinforcement (access count) + time decay since last seen. `decay` auto-archives `note`/`fact` memories that are old, barely accessed, and below the retention threshold; `decision`/`constraint`/`task`/`preference` are never decayed. Tunable with `--min-age-days` / `--max-access` / `--threshold` / `--scope`, previewable with `--dry-run`, and recoverable (it archives, not deletes).
- `context` and `wake-up` packs now drop near-duplicate memories (token-overlap above `dedup_threshold`, default 0.72), so a pack carries more distinct signal under the same character budget — less redundant context to the model.
- When a context query has no lexical match (e.g. a broad "наш проєкт"), the pack falls back to hot memories instead of returning empty, with the header marking the fallback.

Memory lifecycle (schema v4):

- `forget --id` soft-archives a memory: hidden from `search` / `context` / `wake-up` / `list` but kept and recoverable with `restore --id`. Re-saving the same memory resurrects it.
- `revise --id <new> --supersedes <old>` marks the old memory as replaced — hidden from recall, kept for history with a pointer to its replacement.
- `list --include-archived` and `show` surface archived/superseded status.
- Recall now excludes archived and superseded memories by default, so stale entries fade out instead of accumulating as noise. `export` still includes everything for faithful backup, and import preserves lifecycle state.
- New `memory_forget` MCP tool (reversible, so safe for an agent). `delete` / `update` / `revise` stay CLI-only.
- Schema bumped 3 → 4 (new `archived_at` and `superseded_by` columns); migration is automatic.

Ukrainian quality fixes (found by dogfooding):

- "прийнято рішення ...", "ухвалено рішення", "рішення", "ухвалили", "вирішено" now classify as `decision` (previously fell through to `note`). The decision title prefixes were extended too, so "Прийнято рішення перенести X" gets the title "перенести X".
- Soft-group feminine noun declensions now share a stem: `памʼять` / `памʼяті` / `памʼяттю` / `памʼятей` all collapse to `пам`, so searching any case form finds the others. Previously a search for `памʼяттю` returned nothing.

Tests: 96 → 122.

## 0.2.0 - 2026-05-10

Second release. Focused on Ukrainian-language quality, day-to-day inspectability, and write-path performance.

New CLI commands:

- `list` — browse recent memories with `--scope` / `--kind` / `--tags` / `--limit` filters.
- `show --id` — print one full record by id.
- `update --id` — change individual fields without re-importing.
- `delete --id` — remove a single memory.
- `verify [--repair]` — check that derived columns (`stems_text`, `fingerprint`) and the FTS5 index are consistent with the source content; optionally fix in place.
- `completion {bash,powershell}` — print a shell completion script generated dynamically from the parser.
- `ingest --dry-run` — preview the segments and inferred fields without writing.
- `stats --since 7d` (or ISO date) — per-window activity counters.

Ukrainian-language quality:

- `canonicalize_text` strips apostrophes (`'`, `'`, `'`, `ʼ`) before tokenization, so `обов'язково` and `пам'ять` stay as single tokens and match the kind hints.
- Removed the ASCII gate that forced all Cyrillic content through the slower Python path. Ukrainian word lists (stop words, kind hints, prefixes, signal words, hedges) ported into Rust.
- Query-side suffix stem expands each search term (`вирішили` → `виріш*`).
- Content-side deep stem (suffix + iterative prefix stripping) is computed at write time and stored in a new `stems_text` column inside the FTS5 index. Search now bridges across different prefixes — `рішення` finds `вирішили` and `невирішене`, all collapsing to the same `ріш` stem.
- `MEMORY_KERNEL_DISABLE_STEMMER=1` disables the stemmer on the query side without a rebuild.
- Windows stdout is reconfigured to UTF-8 at CLI entry so Cyrillic JSON output is no longer mangled.

Schema and migration:

- Schema bumped from `2` to `3`. New `stems_text` column on `memories` and as a 5th FTS5 indexed column.
- Migration framework rewritten: `init()` detects the existing version (including pre-versioning v1 databases that have no `schema_version` row) and applies an explicit list of `(version, migration)` steps. Each migration is a named method (`_migrate_v1_to_v2`, `_migrate_v2_to_v3`).
- Adding a future migration is a one-line addition to the registry.

Performance:

- Native Rust now covers `light_stem`, `deep_stem`, and `compute_stems_text` in addition to the previous heuristics.
- Microbenchmark on `compute_stems_text` for Cyrillic title+content+tags: Python 4,771 calls/s → Rust 30,758 calls/s (**6.45x**).
- Public benchmark (bilingual EN+UA, now includes `compute_stems_text` per segment): Rust ingest **5.19x** vs Python; rank **3.87x**.

Documentation:

- README expanded with sections for every new command plus a "Ukrainian Inflection Bridging" subsection.
- `docs/OPERATING_GUIDE_UK.md` refreshed with all new commands and a new "Робота з українською мовою" section covering apostrophe handling, stems, and the cross-prefix bridge.

Tests: 16 → 91.

Known gaps for the next iterations:

- prebuilt wheels for major platforms
- guided ingest for less technical users
- simpler first-run onboarding and demo flow

## 0.1.0 - 2026-04-15

First public release on PyPI.

Highlights:

- local-first memory store for AI agents
- `memory-kernel` CLI for `remember`, `ingest`, `search`, `context`, `wake-up`, `stats`
- deterministic export and import flows
- optional Rust accelerator for hot paths
- documentation for setup, usage, backup, and restore

Published package name:

- `amormorri-memory-kernel`

Installed CLI command:

- `memory-kernel`

Known gaps for the next iterations:

- prebuilt wheels for major platforms
- guided ingest for less technical users
- simpler first-run onboarding and demo flow
