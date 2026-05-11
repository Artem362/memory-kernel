# Changelog

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
