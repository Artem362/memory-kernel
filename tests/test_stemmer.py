import pytest

from memory_kernel.store import (
    MemoryInput,
    MemoryStore,
    build_fts_query,
    light_stem,
)


@pytest.mark.parametrize(
    "term,expected",
    [
        ("вирішили", "виріш"),
        ("вирішила", "виріш"),
        ("вирішую", "вирішую"),
        ("рішення", "ріш"),
        ("створюються", "створ"),
        ("вирішується", "виріш"),
        ("використання", "використ"),
        ("оптимізування", "оптиміз"),
        ("творіння", "твор"),
        ("красивого", "красив"),
    ],
)
def test_light_stem_strips_common_ukrainian_suffixes(term, expected):
    assert light_stem(term) == expected


@pytest.mark.parametrize(
    "term",
    ["memory", "decision", "rust", "data", "running", "items"],
)
def test_light_stem_passes_english_through(term):
    assert light_stem(term) == term


@pytest.mark.parametrize("term", ["ріш", "так", "ні", "ок"])
def test_light_stem_keeps_short_terms(term):
    assert light_stem(term) == term


def test_light_stem_refuses_to_overstrip_short_roots():
    assert light_stem("дія") == "дія"
    assert light_stem("суди") == "суди"


def test_build_fts_query_uses_stems_for_ukrainian():
    fts = build_fts_query("вирішили вирішення вирішує")
    assert "виріш*" in fts
    assert fts.count("виріш*") >= 1


def test_build_fts_query_keeps_english_unchanged():
    fts = build_fts_query("memory budget rust")
    assert "memory*" in fts
    assert "budget*" in fts
    assert "rust*" in fts


def test_search_recall_bridges_ukrainian_inflections_with_shared_prefix(tmp_path):
    db_path = tmp_path / "memory.db"
    samples = [
        ("Ми вирішили перейти на Postgres.", "decision"),
        ("Прийнято вирішення мігрувати базу даних.", "decision"),
        ("Команда вирішує питання резервування памʼяті.", "task"),
        ("Вирішена проблема з памʼяттю не повторюється.", "fact"),
        ("Цей проєкт використовує SQLite FTS5.", "fact"),
    ]

    with MemoryStore(db_path) as store:
        for index, (content, kind) in enumerate(samples):
            store.remember_result(
                MemoryInput(
                    scope="recall.test",
                    kind=kind,
                    title=f"Sample {index}",
                    content=content,
                )
            )

        for query in ("вирішили", "вирішення", "вирішує", "вирішена"):
            results = store.search(query, limit=10)
            titles = {r.title for r in results}
            related = {"Sample 0", "Sample 1", "Sample 2", "Sample 3"}
            assert related.issubset(titles), f"query={query!r} titles={titles}"
            assert "Sample 4" not in titles, f"query={query!r} titles={titles}"


def test_search_recall_bridges_across_different_prefixes(tmp_path):
    db_path = tmp_path / "memory.db"
    samples = [
        ("Ми вирішили перейти на Postgres.", "decision"),
        ("Прийнято рішення мігрувати базу даних.", "decision"),
        ("Невирішене питання залишається відкритим.", "note"),
        ("Цей проєкт використовує SQLite FTS5.", "fact"),
    ]

    with MemoryStore(db_path) as store:
        for index, (content, kind) in enumerate(samples):
            store.remember_result(
                MemoryInput(
                    scope="bridge.test",
                    kind=kind,
                    title=f"Sample {index}",
                    content=content,
                )
            )

        for query in ("рішення", "вирішили", "невирішене"):
            results = store.search(query, limit=10)
            titles = {r.title for r in results}
            related = {"Sample 0", "Sample 1", "Sample 2"}
            assert related.issubset(titles), f"query={query!r} titles={titles}"
            assert "Sample 3" not in titles, f"query={query!r} titles={titles}"


def test_compute_stems_text_includes_deep_stems():
    from memory_kernel.store import compute_stems_text, deep_stem

    stems = compute_stems_text(
        title="Вирішили перейти на Postgres",
        content="Прийнято рішення мігрувати базу.",
        tags=("міграція",),
    )
    tokens = stems.split()
    assert deep_stem("вирішили") in tokens
    assert deep_stem("рішення") in tokens
    assert tokens[0] == tokens[0].lower()


def test_v2_database_migrates_to_v3_with_stems_backfilled(tmp_path):
    import sqlite3

    db_path = tmp_path / "memory.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
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
            title, summary, content, tags_text,
            content='memories', content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memory_fts(rowid, title, summary, content, tags_text)
            VALUES (new.rowid, new.title, new.summary, new.content, new.tags_text);
        END;
        CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, title, summary, content, tags_text)
            VALUES ('delete', old.rowid, old.title, old.summary, old.content, old.tags_text);
        END;
        CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, title, summary, content, tags_text)
            VALUES ('delete', old.rowid, old.title, old.summary, old.content, old.tags_text);
            INSERT INTO memory_fts(rowid, title, summary, content, tags_text)
            VALUES (new.rowid, new.title, new.summary, new.content, new.tags_text);
        END;
        INSERT INTO meta(key, value) VALUES ('schema_version', '2');
        """
    )
    connection.execute(
        """
        INSERT INTO memories (
            id, scope, kind, title, summary, content, tags_json, tags_text,
            source, importance, certainty, fingerprint, created_at, updated_at
        ) VALUES (
            'legacy-1', 'legacy.scope', 'decision',
            'Legacy decision', 'Legacy decision summary',
            'Прийнято рішення мігрувати базу.',
            '["міграція"]', 'міграція',
            '', 0.8, 0.85, 'fp-legacy',
            '2026-04-01T00:00:00+00:00', '2026-04-01T00:00:00+00:00'
        )
        """
    )
    connection.commit()
    connection.close()

    with MemoryStore(db_path) as store:
        stats = store.stats()
        assert stats["total_memories"] == 1

        results = store.search("вирішили", limit=10)

    titles = {r.title for r in results}
    assert "Legacy decision" in titles, titles


def test_v1_database_without_meta_migrates_through_to_v3(tmp_path):
    import sqlite3

    db_path = tmp_path / "memory.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
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
            source TEXT NOT NULL DEFAULT '',
            importance REAL NOT NULL DEFAULT 0.5,
            certainty REAL NOT NULL DEFAULT 0.7,
            access_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_accessed_at TEXT
        );
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            title, summary, content, tags_text,
            content='memories', content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memory_fts(rowid, title, summary, content, tags_text)
            VALUES (new.rowid, new.title, new.summary, new.content, new.tags_text);
        END;
        """
    )
    connection.execute(
        """
        INSERT INTO memories (
            id, scope, kind, title, summary, content, tags_json, tags_text,
            source, importance, certainty, created_at, updated_at
        ) VALUES (
            'legacy-v1', 'v1.scope', 'decision',
            'V1 era decision', 'Pre-versioning summary',
            'Прийнято рішення тримати старий запис.',
            '[]', '',
            '', 0.7, 0.8,
            '2026-04-01T00:00:00+00:00', '2026-04-01T00:00:00+00:00'
        )
        """
    )
    connection.commit()
    connection.close()

    with MemoryStore(db_path) as store:
        stats = store.stats()
        assert stats["total_memories"] == 1
        verify_report = store.verify()

    assert verify_report["healthy"], verify_report

    import sqlite3
    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    version = raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    cols = [r[1] for r in raw.execute("PRAGMA table_info(memories)")]
    raw.close()

    assert version["value"] == "3"
    assert "fingerprint" in cols
    assert "stems_text" in cols


def test_disabled_stemmer_falls_back_to_exact_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_KERNEL_DISABLE_STEMMER", "1")
    from importlib import reload

    import memory_kernel.accelerator as accelerator_module
    import memory_kernel.store as store_module

    reload(accelerator_module)
    reload(store_module)

    fts = store_module.build_fts_query("вирішили")
    assert "вирішили*" in fts
    assert "виріш*" not in fts.replace("вирішили*", "")

    monkeypatch.delenv("MEMORY_KERNEL_DISABLE_STEMMER")
    reload(accelerator_module)
    reload(store_module)
