import pytest

from memory_kernel.accelerator import native_accel


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
def test_native_accelerator_smoke():
    assert native_accel.infer_kind("We decided to switch to SQLite FTS5.") == "decision"
    assert native_accel.build_fts_query("sqlite retrieval performance") == "sqlite* OR retrieval* OR performance*"


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
def test_native_rank_rows_tuples():
    rows = [
        (
            0,
            "constraint",
            "Budget stays tight",
            "Memory must stay cheap under a strict prompt budget.",
            "Memory must stay cheap under a strict prompt budget.",
            "memory budget",
            0.98,
            0.95,
            2,
            "2026-04-12T20:00:00+00:00",
        ),
        (
            1,
            "decision",
            "Switch to Rust",
            "We decided to move the memory hot path to Rust.",
            "We decided to move the memory hot path to Rust.",
            "rust memory",
            0.88,
            0.91,
            1,
            "2026-04-12T20:00:00+00:00",
        ),
    ]

    ranked = native_accel.rank_rows_tuples(
        rows,
        ["memory", "budget", "rust"],
        "2026-04-12T20:00:00+00:00",
        2,
    )

    assert ranked[0][0] == 0
    assert ranked[0][1] >= ranked[1][1]
    assert "prompt budget" in ranked[0][2].lower()


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
def test_native_duplicate_and_merge_helpers():
    assert native_accel.duplicate_match_score(
        "We decided to move the memory hot path to Rust.",
        "We decided to move the memory hot path to Rust for production workloads.",
    ) >= 0.72

    matched = native_accel.find_duplicate_candidate(
        [
            (0, "We decided to move the memory hot path to Rust."),
            (1, "Completely unrelated deployment note."),
        ],
        "We decided to move the memory hot path to Rust for production workloads.",
        0.72,
    )

    merged = native_accel.merge_memory_fields(
        "Switch to Rust hot path",
        "We decided to move the memory hot path to Rust.",
        "session-001",
        ["rust", "memory"],
        0.84,
        0.88,
        "Switch to Rust hot path",
        "We decided to move the memory hot path to Rust because ingest must stay fast under production load.",
        "session-002",
        ["performance", "production"],
        0.92,
        0.91,
        72,
        240,
    )

    assert matched == 0
    assert "production load" in merged[1]
    assert merged[3] == ["rust", "memory", "performance", "production"]
    assert merged[4] == "session-001; session-002"
