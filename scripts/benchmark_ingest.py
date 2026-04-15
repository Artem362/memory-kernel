from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

SAMPLE_TEXT = """
- We decided to move the memory hot path to Rust for lower overhead.
- Memory must stay deterministic, local, and cheap under a strict prompt budget.
- TODO: benchmark ingest throughput against the Python fallback.
- We prefer exact retrieval with SQLite FTS5 over fuzzy always-on vector search.
- The current kernel stores decisions, constraints, tasks, preferences, facts, and notes.
""".strip()


BENCH_CODE = textwrap.dedent(
    f"""
    import json
    import sys
    from time import perf_counter

    sys.path.insert(0, {str(SRC)!r})

    from memory_kernel.accelerator import has_native_acceleration
    from memory_kernel.store import (
        MemoryStore,
        derive_candidate_tags,
        derive_summary,
        derive_title,
        infer_certainty,
        infer_importance,
        infer_kind,
        split_memory_candidates,
    )

    text = {SAMPLE_TEXT!r}
    loops = 2000
    total_items = 0
    now_iso = "2026-04-12T20:00:00+00:00"
    base_rows = [
        ("decision", "Switch to Rust", "We decided to move the memory hot path to Rust.", 0.91, 0.93),
        ("constraint", "Budget stays tight", "Memory must stay deterministic and cheap under a strict prompt budget.", 0.98, 0.95),
        ("task", "Add benchmark coverage", "TODO: benchmark ranking and context pack throughput.", 0.84, 0.87),
        ("preference", "Prefer exact retrieval", "We prefer exact retrieval over fuzzy always-on vector recall.", 0.73, 0.82),
        ("fact", "Kernel uses SQLite FTS5", "The kernel uses SQLite FTS5 for local lexical search.", 0.69, 0.79),
    ]
    rows = []
    for idx in range(120):
        kind, title, content, importance, certainty = base_rows[idx % len(base_rows)]
        rows.append(
            {{
                "id": f"id-{{idx}}",
                "scope": "project.ai-memory",
                "kind": kind,
                "title": f"{{title}} #{{idx}}",
                "summary": content,
                "content": content,
                "tags_json": "[\\"memory\\", \\"benchmark\\"]",
                "tags_text": "memory benchmark",
                "source": "benchmark",
                "importance": importance,
                "certainty": certainty,
                "access_count": idx % 4,
                "created_at": now_iso,
                "updated_at": now_iso,
                "last_accessed_at": None,
            }}
        )
    store = MemoryStore("benchmark.db")

    ingest_start = perf_counter()
    for _ in range(loops):
        segments = split_memory_candidates(text, max_items=32, max_chars=320)
        for segment in segments:
            kind = infer_kind(segment)
            derive_title(segment, kind)
            derive_summary(segment)
            infer_importance(segment, kind)
            infer_certainty(segment, kind)
            derive_candidate_tags(segment, base_tags=("benchmark", "memory"))
            total_items += 1
    ingest_elapsed = perf_counter() - ingest_start

    rank_loops = 4000
    ranked_items = 0
    rank_start = perf_counter()
    for _ in range(rank_loops):
        ranked = store._rank_rows(rows, ["memory", "budget", "rust"], limit=24)
        store._render_pack(results=ranked, budget_chars=420, limit=3, header="Benchmark pack")
        ranked_items += len(ranked)
    rank_elapsed = perf_counter() - rank_start

    print(json.dumps({{
        "accelerator": "rust" if has_native_acceleration() else "python",
        "ingest_loops": loops,
        "ingest_items": total_items,
        "ingest_elapsed_sec": round(ingest_elapsed, 4),
        "ingest_items_per_sec": round(total_items / ingest_elapsed, 2),
        "rank_loops": rank_loops,
        "rank_items": ranked_items,
        "rank_elapsed_sec": round(rank_elapsed, 4),
        "rank_items_per_sec": round(ranked_items / rank_elapsed, 2),
    }}))
    """
)


def run_case(*, disable_native: bool) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    if disable_native:
        env["MEMORY_KERNEL_DISABLE_NATIVE"] = "1"
    else:
        env.pop("MEMORY_KERNEL_DISABLE_NATIVE", None)

    result = subprocess.run(
        [sys.executable, "-c", BENCH_CODE],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    python_case = run_case(disable_native=True)
    rust_case = run_case(disable_native=False)

    ingest_speedup = rust_case["ingest_items_per_sec"] / python_case["ingest_items_per_sec"]
    rank_speedup = rust_case["rank_items_per_sec"] / python_case["rank_items_per_sec"]
    payload = {
        "python": python_case,
        "rust": rust_case,
        "ingest_speedup_vs_python": round(ingest_speedup, 2),
        "rank_speedup_vs_python": round(rank_speedup, 2),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
