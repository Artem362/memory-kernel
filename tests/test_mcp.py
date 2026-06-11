import asyncio
import json

import pytest

pytest.importorskip("mcp")

from memory_kernel import mcp_server as m


@pytest.fixture
def server_db(tmp_path, monkeypatch):
    db_path = tmp_path / "mcp.db"
    monkeypatch.setattr(m, "_db_override", db_path)
    return db_path


def test_all_expected_tools_registered():
    tools = asyncio.run(m.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "memory_remember",
        "memory_ingest",
        "memory_forget",
        "memory_search",
        "memory_build_context",
        "memory_wake_up",
        "memory_list",
        "memory_stats",
    }


def test_tools_expose_flat_parameters():
    tools = {t.name: t for t in asyncio.run(m.mcp.list_tools())}
    props = tools["memory_remember"].inputSchema["properties"]
    # flat schema: the model sees fields directly, not nested under "params"
    assert {"scope", "kind", "title", "content"}.issubset(props.keys())
    assert "params" not in props
    assert set(tools["memory_remember"].inputSchema["required"]) == {"scope", "kind", "title", "content"}


def test_read_tools_marked_read_only():
    tools = {t.name: t for t in asyncio.run(m.mcp.list_tools())}
    for name in ("memory_search", "memory_build_context", "memory_wake_up", "memory_list", "memory_stats"):
        assert tools[name].annotations.readOnlyHint is True, name
    for name in ("memory_remember", "memory_ingest", "memory_forget"):
        assert tools[name].annotations.readOnlyHint is False, name
        assert tools[name].annotations.destructiveHint is False, name


def test_memory_kind_enum_matches_store():
    from memory_kernel.store import VALID_KINDS

    assert {k.value for k in m.MemoryKind} == set(VALID_KINDS)


def test_memory_forget_archives_and_hides(server_db):
    out = m.memory_remember(scope="proj", kind=m.MemoryKind.decision, title="Use Redis", content="Вирішили використати Redis.")
    memory_id = out.split()[1]
    forget_out = m.memory_forget(memory_id=memory_id)
    assert "archived" in forget_out
    assert "Use Redis" not in m.memory_search(query="Redis")


def test_memory_forget_missing_reports_not_found(server_db):
    out = m.memory_forget(memory_id="nope")
    assert "not found" in out


def test_remember_then_search_finds_record(server_db):
    out = m.memory_remember(
        scope="proj",
        kind=m.MemoryKind.decision,
        title="Use FTS5",
        content="Вирішили використовувати SQLite FTS5 замість векторної бази.",
        tags=["sqlite", "пошук"],
    )
    assert out.startswith("created ")
    result = m.memory_search(query="рішення", limit=5)
    assert "Use FTS5" in result
    assert "decision/proj" in result


def test_search_json_format_returns_array(server_db):
    m.memory_remember(scope="proj", kind=m.MemoryKind.fact, title="Kernel uses Rust", content="Ядро використовує Rust акселератор.")
    out = m.memory_search(query="Rust", response_format=m.ResponseFormat.json)
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert payload[0]["title"] == "Kernel uses Rust"
    assert "score" in payload[0]


def test_remember_dedup_reports_updated(server_db):
    kw = dict(scope="proj", kind=m.MemoryKind.decision, title="Use FTS5", content="We will use SQLite FTS5 for retrieval.")
    first = m.memory_remember(**kw)
    second = m.memory_remember(**kw)
    assert first.startswith("created ")
    assert second.startswith("updated ")


def test_ingest_splits_into_multiple(server_db):
    out = m.memory_ingest(
        text="Треба додати MCP сервер. Памʼять має лишатись локальною. Вирішили робити stdio транспорт.",
        scope="proj",
    )
    assert "ingested 3 memories" in out


def test_build_context_respects_budget(server_db):
    for i in range(5):
        m.memory_remember(scope="proj", kind=m.MemoryKind.note, title=f"Note {i}", content=f"Контент номер {i} про памʼять і пошук.")
    out = m.memory_build_context(query="памʼять", budget_chars=300, limit=5)
    pack = json.loads(out)
    assert pack["used_chars"] <= 300
    assert "rendered" in pack


def test_wake_up_returns_pack(server_db):
    m.memory_remember(scope="proj", kind=m.MemoryKind.constraint, title="Local only", content="Памʼять обовʼязково локальна.", importance=0.97)
    out = m.memory_wake_up(budget_chars=400, limit=3)
    pack = json.loads(out)
    assert pack["items"]
    assert pack["items"][0]["title"] == "Local only"


def test_list_and_stats(server_db):
    for i in range(3):
        m.memory_remember(scope="proj", kind=m.MemoryKind.task, title=f"Task {i}", content=f"Зробити крок {i}.")
    listing = m.memory_list(limit=10)
    assert "Task 2" in listing
    stats = m.memory_stats(since="7d")
    assert "total memories: 3" in stats
    assert "created" in stats


def test_stats_invalid_since_returns_error(server_db):
    out = m.memory_stats(since="garbage")
    assert out.startswith("Error:")
