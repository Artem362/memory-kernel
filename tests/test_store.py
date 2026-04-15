import memory_kernel.store as store_module
from memory_kernel.store import MemoryInput, MemoryStore


def build_store(tmp_path):
    db_path = tmp_path / "memory.db"
    store = MemoryStore(db_path)
    store.init()
    return store


def test_search_prefers_explicit_decision(tmp_path):
    store = build_store(tmp_path)
    store.remember(
        MemoryInput(
            scope="project.ai-memory",
            kind="note",
            title="General brainstorm",
            content="We discussed several storage ideas without making a final choice.",
            tags=("brainstorm",),
            importance=0.2,
            certainty=0.5,
        )
    )
    store.remember(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Switch to SQLite FTS5",
            content=(
                "We are replacing a heavier vector stack with SQLite FTS5 because "
                "the memory layer must stay local, cheap, and predictable."
            ),
            tags=("sqlite", "fts5", "performance", "retrieval"),
            importance=0.95,
            certainty=0.95,
        )
    )
    store.remember(
        MemoryInput(
            scope="project.ops",
            kind="decision",
            title="Keep Redis in staging",
            content="Redis remains a staging-only cache for unrelated deployment work.",
            tags=("redis", "cache"),
            importance=0.7,
            certainty=0.8,
        )
    )

    results = store.search(
        "sqlite retrieval performance",
        limit=3,
        scope="project.ai-memory",
    )

    assert results
    assert results[0].title == "Switch to SQLite FTS5"
    assert results[0].kind == "decision"


def test_context_pack_respects_budget(tmp_path):
    store = build_store(tmp_path)
    store.remember(
        MemoryInput(
            scope="project.ai-memory",
            kind="constraint",
            title="Prompt budget stays small",
            content=(
                "The agent should load a tiny wake-up pack and only fetch deeper memory "
                "when the active task needs it. This avoids wasting context on old chatter."
            ),
            tags=("budget", "prompt"),
            importance=0.9,
            certainty=0.9,
        )
    )
    store.remember(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Use context packs",
            content=(
                "Context packs are short, explicit, and bounded. They replace huge prompt "
                "dumps with a focused set of decisions and constraints."
            ),
            tags=("context", "retrieval"),
            importance=0.85,
            certainty=0.9,
        )
    )

    pack = store.build_context_pack(
        "How do we keep memory cheap?",
        budget_chars=220,
        limit=5,
        scope="project.ai-memory",
    )

    assert pack["items"]
    assert pack["used_chars"] <= 220
    assert len(pack["rendered"]) <= 220


def test_remember_merges_duplicate_memory(tmp_path):
    store = build_store(tmp_path)
    first_id = store.remember(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Switch to SQLite FTS5",
            content="We decided to switch to SQLite FTS5 for local deterministic retrieval.",
            tags=("sqlite", "retrieval"),
            importance=0.82,
            certainty=0.88,
        )
    )

    result = store.remember_result(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Switch to SQLite FTS5",
            content="We decided to switch to SQLite FTS5 for local deterministic retrieval.",
            tags=("fts5", "local"),
            importance=0.95,
            certainty=0.92,
        )
    )

    assert result.id == first_id
    assert result.action == "updated"
    assert store.stats()["total_memories"] == 1

    results = store.search("sqlite deterministic retrieval", limit=1, scope="project.ai-memory")

    assert results
    assert results[0].id == first_id
    assert set(results[0].tags) == {"sqlite", "retrieval", "fts5", "local"}
    assert results[0].importance >= 0.95


def test_ingest_text_extracts_and_deduplicates_memories(tmp_path):
    store = build_store(tmp_path)
    transcript = """
    - We decided to switch to SQLite FTS5 for local retrieval.
    - Memory must stay deterministic and cheap under a strict prompt budget.
    - TODO: add duplicate-aware transcript ingestion.
    """

    report = store.ingest_text(
        transcript,
        scope="project.ai-memory",
        source="session-001",
        tags=("kernel",),
    )

    assert report["stored"] == 3
    assert report["created"] == 3
    assert {item["kind"] for item in report["items"]} == {"decision", "constraint", "task"}

    repeat = store.ingest_text(
        transcript,
        scope="project.ai-memory",
        source="session-002",
        tags=("kernel",),
    )

    assert repeat["stored"] == 3
    assert repeat["updated"] == 3
    assert store.stats()["total_memories"] == 3


def test_duplicate_merge_prefers_richer_content_and_sources(tmp_path):
    store = build_store(tmp_path)
    store.remember_result(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Switch to Rust hot path",
            content="We decided to move the memory hot path to Rust.",
            tags=("rust", "memory"),
            source="session-001",
            importance=0.84,
            certainty=0.88,
        )
    )

    result = store.remember_result(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Switch to Rust hot path",
            content=(
                "We decided to move the memory hot path to Rust because ingest and "
                "ranking must stay fast under real production load."
            ),
            tags=("performance", "production"),
            source="session-002",
            importance=0.92,
            certainty=0.91,
        )
    )

    assert result.action == "updated"

    results = store.search("production load rust hot path", limit=1, scope="project.ai-memory")

    assert results
    assert "production load" in results[0].content
    assert results[0].source == "session-001; session-002"
    assert set(results[0].tags) == {"rust", "memory", "performance", "production"}
    assert results[0].importance >= 0.92


def test_duplicate_merge_prefers_richer_content_without_native(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "native_accel", None)
    store = build_store(tmp_path)
    store.remember_result(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Switch to Rust hot path",
            content="We decided to move the memory hot path to Rust.",
            tags=("rust", "memory"),
            source="session-001",
            importance=0.84,
            certainty=0.88,
        )
    )

    result = store.remember_result(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Switch to Rust hot path",
            content=(
                "We decided to move the memory hot path to Rust because ingest and "
                "ranking must stay fast under real production load."
            ),
            tags=("performance", "production"),
            source="session-002",
            importance=0.92,
            certainty=0.91,
        )
    )

    assert result.action == "updated"

    results = store.search("production load rust hot path", limit=1, scope="project.ai-memory")

    assert results
    assert "production load" in results[0].content
    assert results[0].source == "session-001; session-002"
    assert set(results[0].tags) == {"rust", "memory", "performance", "production"}
    assert results[0].importance >= 0.92


def test_wake_up_pack_prioritizes_hot_items(tmp_path):
    store = build_store(tmp_path)
    store.remember(
        MemoryInput(
            scope="project.ai-memory",
            kind="note",
            title="Old loose note",
            content="A vague note with low importance should not dominate the wake-up pack.",
            importance=0.1,
            certainty=0.3,
        )
    )
    store.remember(
        MemoryInput(
            scope="project.ai-memory",
            kind="constraint",
            title="Memory must stay deterministic",
            content="We favor explicit scopes, explicit kinds, and small context packs.",
            importance=0.98,
            certainty=0.95,
        )
    )

    pack = store.build_wake_up_pack(budget_chars=280, limit=3, scope="project.ai-memory")

    assert pack["items"]
    assert pack["items"][0]["title"] == "Memory must stay deterministic"


def test_store_close_releases_and_reopens_connection(tmp_path):
    db_path = tmp_path / "memory.db"
    store = MemoryStore(db_path)
    store.init()
    store.remember_result(
        MemoryInput(
            scope="project.ai-memory",
            kind="decision",
            title="Close connections",
            content="We need SQLite connections to close cleanly after each operation.",
            tags=("sqlite", "lifecycle"),
            importance=0.8,
            certainty=0.9,
        )
    )

    assert store._connection is not None
    assert store.search("close cleanly", limit=1, scope="project.ai-memory")

    store.close()
    assert store._connection is None

    assert store.search("close cleanly", limit=1, scope="project.ai-memory")
    assert store._connection is not None

    store.close()
    db_path.unlink()
    assert not db_path.exists()


def test_store_context_manager_closes_connection(tmp_path):
    db_path = tmp_path / "memory.db"
    with MemoryStore(db_path) as store:
        store.remember_result(
            MemoryInput(
                scope="project.ai-memory",
                kind="decision",
                title="Context-managed store",
                content="A persistent SQLite connection should close when the context exits.",
                tags=("sqlite", "context"),
                importance=0.75,
                certainty=0.85,
            )
        )
        assert store._connection is not None

    assert store._connection is None
