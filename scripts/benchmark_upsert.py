from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

BENCH_CODE = textwrap.dedent(
    f"""
    import json
    import sys
    import tempfile
    from pathlib import Path
    from time import perf_counter

    sys.path.insert(0, {str(SRC)!r})

    from memory_kernel.accelerator import has_native_acceleration
    from memory_kernel.store import MemoryInput, MemoryStore

    variants = [
        "We decided to move the memory hot path to Rust.",
        "We decided to move the memory hot path to Rust because ingest must stay fast.",
        "We decided to move the memory hot path to Rust because ingest and ranking must stay fast under production load.",
    ]

    loops = 3000

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "upsert.db"
        with MemoryStore(db_path) as store:
            created = 0
            updated = 0

            for idx in range(24):
                store.remember_result(
                    MemoryInput(
                        scope="project.ai-memory",
                        kind="decision",
                        title=f"Switch to Rust hot path #{{idx}}",
                        content=variants[0],
                        tags=("rust", "memory"),
                        source="seed",
                        importance=0.84,
                        certainty=0.88,
                    )
                )

            start = perf_counter()
            for step in range(loops):
                idx = step % 24
                variant = variants[(step % (len(variants) - 1)) + 1]
                result = store.remember_result(
                    MemoryInput(
                        scope="project.ai-memory",
                        kind="decision",
                        title=f"Switch to Rust hot path #{{idx}}",
                        content=variant,
                        tags=("performance", "production"),
                        source=f"session-{{step % 8}}",
                        importance=0.92,
                        certainty=0.91,
                    )
                )
                created += result.action == "created"
                updated += result.action == "updated"
            elapsed = perf_counter() - start
            total_memories = store.stats()["total_memories"]

    print(json.dumps({{
        "accelerator": "rust" if has_native_acceleration() else "python",
        "loops": loops,
        "created": created,
        "updated": updated,
        "total_memories": total_memories,
        "elapsed_sec": round(elapsed, 4),
        "updates_per_sec": round(loops / elapsed, 2),
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

    speedup = rust_case["updates_per_sec"] / python_case["updates_per_sec"]
    payload = {
        "python": python_case,
        "rust": rust_case,
        "speedup_vs_python": round(speedup, 2),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
