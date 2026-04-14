# Memory Kernel

`Memory Kernel` is a lightweight local-first memory core for AI agents.

Practical guide in Ukrainian, including the operating principle and architecture/data-flow schemas:
[docs/OPERATING_GUIDE_UK.md](docs/OPERATING_GUIDE_UK.md)

It was built with the same useful instinct behind MemPalace in mind: keep memory on the user's machine and retrieve exact context when needed. The difference is that this project deliberately avoids a heavy vector stack and fuzzy always-on retrieval. Instead, it uses:

- explicit memory kinds: `decision`, `constraint`, `preference`, `task`, `fact`, `note`
- `SQLite` + `FTS5` for cheap local full-text search
- deterministic ranking that favors actionable memories over vague notes
- deterministic transcript ingestion with duplicate-aware updates
- optional `Rust` accelerator for ingest, duplicate-aware upsert heuristics, and retrieval hot paths
- context packs with a hard character budget so only useful memory reaches the model

For embedded Python usage, `MemoryStore` keeps a long-lived SQLite connection for throughput. Prefer `with MemoryStore(...) as store:` or call `store.close()` when you're done.

## Start In 5 Minutes

If you do not want to learn the internals first, use it like this:

1. Install it: `pip install -e .`
2. Create the local memory database: `memory-kernel init`
3. Save one important thing:
   `memory-kernel remember --scope my.project --kind decision --title "What we decided" --content "We will keep memory local on the user's machine."`
4. Ask for it back later:
   `memory-kernel search "local memory"`
5. Export a backup:
   `memory-kernel export --format json --output exports\memory.json`

That is enough to start using the project without understanding `FTS5`, ranking formulas, or context packing.

## Project Status

Current stage: working alpha.

- the package layout, CLI, docs, tests, export/import, and optional Rust accelerator already exist
- the Python fallback works without Rust
- the core workflows are usable today for local experimentation and integration
- packaging for easy end-user distribution is not finished yet

Near-term product gaps:

- prebuilt wheels for major platforms
- a simpler guided ingest flow for non-technical users
- lighter onboarding for people who do not care about implementation details

## Who This Is For

This is a good fit when the end user wants:

- local-first memory on their own machine
- exact, inspectable records instead of a black-box memory layer
- small, controlled context instead of always sending a large memory dump
- backup and restore through plain export files

This is a weaker fit when the end user mainly wants:

- a fully hosted managed memory platform
- plug-and-play onboarding with no local setup
- automatic structure from messy notes without reviewing what was saved

## Why this direction

Most AI memory systems fail in two ways:

- they are fuzzy, so low-signal notes come back with the important ones
- they are heavy, so the memory layer becomes more expensive than the work it is meant to support

This project pushes in the opposite direction:

- store exact text locally
- require clear scope and kind for every memory
- rank by lexical match, actionability, certainty, importance, recency, and reuse
- build small context packs instead of dumping everything into the prompt

## End-User Positioning

For an end user, the value proposition is simple:

- your memory stays on your machine
- you can inspect what was saved
- you can export it and move it
- retrieval is intentionally small and predictable

The tradeoff is also simple:

- this product currently expects a bit more structure and discipline than a consumer-first app
- the best experience today is for teams and advanced users who want control, not maximum automation

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]

memory-kernel init

memory-kernel remember ^
  --scope project.ai-memory ^
  --kind decision ^
  --title "Switch to SQLite FTS5" ^
  --content "We are replacing a heavier vector stack with SQLite FTS5 because memory retrieval must stay local, fast, and predictable." ^
  --tags sqlite performance retrieval ^
  --importance 0.95 ^
  --certainty 0.95

memory-kernel search "sqlite retrieval performance"
memory-kernel context "How should the agent remember architecture decisions?"
memory-kernel wake-up
memory-kernel stats
memory-kernel export --format json --output exports\memory.json
memory-kernel import --file exports\memory.json

memory-kernel ingest ^
  --scope project.ai-memory ^
  --file notes.txt ^
  --source sprint-review ^
  --tags transcript planning
```

## CLI

### `init`

Create the local database in `.memory-kernel/memory.db`.

```bash
memory-kernel init
```

### `remember`

Store one memory record.

```bash
memory-kernel remember \
  --scope project.ai-memory \
  --kind constraint \
  --title "Prompt budget stays small" \
  --content "The agent should load a tiny wake-up pack and fetch deeper memory only when the current task requires it." \
  --tags prompt context-budget
```

### `search`

Find the most relevant exact memories for a query.

```bash
memory-kernel search "context budget for the agent"
```

### `ingest`

Turn raw text, notes, or transcript fragments into structured memories without using an LLM.

```bash
memory-kernel ingest \
  --scope project.ai-memory \
  --file notes.txt \
  --source sprint-review \
  --tags transcript planning
```

### `context`

Build a small pack for an agent prompt with a hard budget.

```bash
memory-kernel context "How do we keep memory cheap?" --budget-chars 700
```

### `wake-up`

Return the currently hottest memories without a search query.

```bash
memory-kernel wake-up --budget-chars 500
```

### `export`

Export memories for backup, migration, or offline inspection.

```bash
memory-kernel export --format json --output exports\memory.json
memory-kernel export --scope project.ai-memory --format jsonl --output exports\ai-memory.jsonl
```

`json` writes one structured export document with metadata and filters.
`jsonl` writes one memory per line and is convenient for pipelines or later processing.

### `import`

Restore memories from a previous export.

```bash
memory-kernel import --file exports\memory.json
memory-kernel import --file exports\ai-memory.jsonl
```

`import` is idempotent for the same exported records because it upserts by memory `id`.

## Typical Workflow

1. Run `memory-kernel init` once for a new database.
2. Save precise decisions with `remember`, or large raw notes with `ingest`.
3. Before an agent task, use `search`, `context`, or `wake-up` to fetch only the needed memory.
4. Periodically run `export` to keep a portable backup of the memory base.
5. On another machine or a fresh database, run `import` to restore the exported memory.

## Schema

Each memory has:

- `scope`: where it belongs, for example `project.ai-memory` or `team.core`
- `kind`: one of the supported kinds
- `title`: short stable label
- `content`: exact source text
- `summary`: short deterministic summary
- `tags`: searchable labels
- `importance`: how important this memory is to outcomes
- `certainty`: how reliable the memory is

Those fields are intentional. They make retrieval sharper than a flat blob store while staying much lighter than a full vector database.

## Tests

```bash
pytest
```

## Native Accelerator

The Python core is the stable fallback. When you want lower overhead on the ingest and heuristic ranking path, build the optional `Rust` module:

```powershell
.\scripts\build_native.ps1
```

After that, `memory-kernel stats` will report `accelerator: rust` and show which ranking/upsert engines are active.

By default, the `Rust` path accelerates ingest and text heuristics. Experimental native ranking / pack rendering is available, but kept off by default because the current JSON bridge is only worth profiling on larger candidate batches:

```powershell
$env:MEMORY_KERNEL_EXPERIMENTAL_NATIVE_RANK=1
```

To compare the heuristic ingest path against the Python fallback:

```powershell
python .\scripts\benchmark_ingest.py
```

To benchmark duplicate-aware upsert throughput:

```powershell
python .\scripts\benchmark_upsert.py
```
