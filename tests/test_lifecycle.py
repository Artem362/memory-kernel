import json
import sqlite3

import pytest

from memory_kernel.cli import main
from memory_kernel.store import MemoryInput, MemoryStore


def _seed(tmp_path):
    db_path = tmp_path / "memory.db"
    with MemoryStore(db_path) as store:
        old = store.remember_result(
            MemoryInput(scope="proj", kind="decision", title="Use Redis", content="Вирішили використати Redis для кешу.")
        ).id
        new = store.remember_result(
            MemoryInput(scope="proj", kind="decision", title="Use Postgres", content="Перейшли на Postgres замість Redis.")
        ).id
    return db_path, old, new


def test_archive_hides_from_search_and_sets_timestamp(tmp_path):
    db_path, old, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        assert store.archive_memory(old) is True
        titles = {r.title for r in store.search("Redis", limit=10)}
        assert "Use Redis" not in titles
        assert store.get_memory(old).archived_at is not None


def test_restore_brings_back_into_recall(tmp_path):
    db_path, old, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        store.archive_memory(old)
        assert store.restore_memory(old) is True
        titles = {r.title for r in store.search("Redis", limit=10)}
        assert "Use Redis" in titles
        assert store.get_memory(old).archived_at is None


def test_archive_missing_returns_false(tmp_path):
    db_path, _, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        assert store.archive_memory("nope") is False
        assert store.restore_memory("nope") is False


def test_revise_supersedes_and_hides_old(tmp_path):
    db_path, old, new = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        record = store.revise_memory(new, old)
        assert record.superseded_by == new
        titles = {r.title for r in store.search("Redis", limit=10)}
        assert "Use Redis" not in titles
        assert "Use Postgres" in titles


def test_revise_self_raises(tmp_path):
    db_path, old, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        with pytest.raises(ValueError):
            store.revise_memory(old, old)


def test_revise_missing_raises(tmp_path):
    db_path, old, new = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        with pytest.raises(KeyError):
            store.revise_memory(new, "nope")
        with pytest.raises(KeyError):
            store.revise_memory("nope", old)


def test_list_excludes_archived_by_default_includes_with_flag(tmp_path):
    db_path, old, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        store.archive_memory(old)
        default = {r.title for r in store.list_memories(limit=10)}
        assert "Use Redis" not in default
        full = {r.title for r in store.list_memories(limit=10, include_archived=True)}
        assert "Use Redis" in full


def test_export_includes_archived_and_superseded(tmp_path):
    db_path, old, new = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        store.revise_memory(new, old)
        payload = store.export_memories()
    assert len(payload) == 2
    superseded = next(p for p in payload if p["id"] == old)
    assert superseded["superseded_by"] == new


def test_import_roundtrip_preserves_lifecycle_state(tmp_path):
    db_path, old, new = _seed(tmp_path)
    target = tmp_path / "target.db"
    with MemoryStore(db_path) as store:
        store.archive_memory(old)
        payload = store.export_memories()
    with MemoryStore(target) as store:
        store.import_memories(payload)
        restored = store.get_memory(old)
    assert restored.archived_at is not None


def test_re_remember_resurrects_archived(tmp_path):
    db_path, old, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        store.archive_memory(old)
        # saving the same memory again should merge and clear the archive flag
        store.remember_result(
            MemoryInput(scope="proj", kind="decision", title="Use Redis", content="Вирішили використати Redis для кешу.")
        )
        assert store.get_memory(old).archived_at is None
        assert "Use Redis" in {r.title for r in store.search("Redis", limit=10)}


def test_cli_forget_restore_roundtrip(tmp_path, capsys):
    db_path, old, _ = _seed(tmp_path)
    assert main(["--db", str(db_path), "forget", "--id", old, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "archived"

    assert main(["--db", str(db_path), "restore", "--id", old, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "restored"


def test_cli_revise(tmp_path, capsys):
    db_path, old, new = _seed(tmp_path)
    code = main(["--db", str(db_path), "revise", "--id", new, "--supersedes", old, "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["superseded_id"] == old
    assert payload["superseded_by"] == new


def test_cli_list_include_archived_flag(tmp_path, capsys):
    db_path, old, _ = _seed(tmp_path)
    main(["--db", str(db_path), "forget", "--id", old])
    capsys.readouterr()
    main(["--db", str(db_path), "list", "--json"])
    default = json.loads(capsys.readouterr().out)
    assert all(item["id"] != old for item in default)
    main(["--db", str(db_path), "list", "--include-archived", "--json"])
    full = json.loads(capsys.readouterr().out)
    assert any(item["id"] == old for item in full)


def test_cli_forget_missing_returns_nonzero(tmp_path, capsys):
    db_path, _, _ = _seed(tmp_path)
    assert main(["--db", str(db_path), "forget", "--id", "nope"]) == 1
    assert "memory not found" in capsys.readouterr().err


def test_v3_database_migrates_to_v4(tmp_path):
    db_path = tmp_path / "memory.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE memories (
            rowid INTEGER PRIMARY KEY,
            id TEXT NOT NULL UNIQUE,
            scope TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            content TEXT NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            tags_text TEXT NOT NULL DEFAULT '',
            stems_text TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            importance REAL NOT NULL DEFAULT 0.5,
            certainty REAL NOT NULL DEFAULT 0.7,
            fingerprint TEXT NOT NULL DEFAULT '',
            access_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_accessed_at TEXT
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            title, summary, content, tags_text, stems_text,
            content='memories', content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memory_fts(rowid, title, summary, content, tags_text, stems_text)
            VALUES (new.rowid, new.title, new.summary, new.content, new.tags_text, new.stems_text);
        END;
        INSERT INTO meta(key, value) VALUES ('schema_version', '3');
        INSERT INTO memories (id, scope, kind, title, summary, content, created_at, updated_at)
        VALUES ('v3-1', 's', 'fact', 'V3 row', 'sum', 'Старий запис до міграції.',
                '2026-05-01T00:00:00+00:00', '2026-05-01T00:00:00+00:00');
        """
    )
    con.commit()
    con.close()

    with MemoryStore(db_path) as store:
        assert store.stats()["total_memories"] == 1
        store.archive_memory("v3-1")
        assert store.get_memory("v3-1").archived_at is not None

    raw = sqlite3.connect(db_path)
    cols = [r[1] for r in raw.execute("PRAGMA table_info(memories)")]
    version = raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    raw.close()
    assert "archived_at" in cols
    assert "superseded_by" in cols
    assert version == "4"
