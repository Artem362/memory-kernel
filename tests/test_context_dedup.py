from memory_kernel.store import MemoryInput, MemoryStore


def _seed(store, items):
    for i, (title, content) in enumerate(items):
        store.remember_result(
            MemoryInput(scope="dedup.test", kind="note", title=title, content=content, importance=0.5 + i * 0.01)
        )


def test_context_pack_drops_near_duplicates(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        _seed(
            store,
            [
                ("A1", "Ми вирішили перенести гарячий шлях памʼяті у Rust для швидкості."),
                ("A2", "Вирішили перенести гарячий шлях памʼяті у Rust заради швидкості."),  # near-dup of A1
                ("B", "Контекст-пак має жорсткий бюджет символів для економії токенів."),
            ],
        )
        pack = store.build_context_pack("Rust памʼять бюджет", budget_chars=2000, limit=5)
    titles = {item["title"] for item in pack["items"]}
    # only one of the near-duplicate pair should be present
    assert len(titles & {"A1", "A2"}) == 1
    assert "B" in titles


def test_dedup_can_be_disabled_with_threshold_one(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        _seed(
            store,
            [
                ("A1", "Ми вирішили перенести гарячий шлях памʼяті у Rust для швидкості."),
                ("A2", "Вирішили перенести гарячий шлях памʼяті у Rust заради швидкості."),
            ],
        )
        pack = store.build_context_pack("Rust памʼять", budget_chars=2000, limit=5, dedup_threshold=1.0)
    titles = {item["title"] for item in pack["items"]}
    assert {"A1", "A2"}.issubset(titles)


def test_distinct_memories_all_kept(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        _seed(
            store,
            [
                ("X", "Памʼять зберігається локально у SQLite."),
                ("Y", "Ранжування детерміноване, без векторів."),
                ("Z", "Бюджет контексту обмежує розмір паку."),
            ],
        )
        pack = store.build_context_pack("памʼять ранжування бюджет", budget_chars=2000, limit=5)
    titles = {item["title"] for item in pack["items"]}
    assert {"X", "Y", "Z"}.issubset(titles)


def test_dedup_respects_budget(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        _seed(
            store,
            [
                ("X", "Памʼять зберігається локально у SQLite та FTS5 для пошуку."),
                ("Y", "Ранжування детерміноване, без векторів і без фаззі-логіки."),
            ],
        )
        pack = store.build_context_pack("памʼять", budget_chars=120, limit=5)
    assert pack["used_chars"] <= 120


def test_context_pack_falls_back_to_hot_memories_when_no_match(tmp_path):
    from memory_kernel.store import MemoryInput, MemoryStore

    db_path = tmp_path / "memory.db"
    with MemoryStore(db_path) as store:
        store.remember_result(
            MemoryInput(
                scope="demo", kind="constraint", title="Local only",
                content="Памʼять обовʼязково локальна.", importance=0.95,
            )
        )
        pack = store.build_context_pack("наш проєкт", budget_chars=600, limit=5)

    assert pack["items"], pack
    assert pack["items"][0]["title"] == "Local only"
    assert "no direct match" in pack["rendered"].splitlines()[0]


def test_context_pack_no_fallback_when_query_matches(tmp_path):
    from memory_kernel.store import MemoryInput, MemoryStore

    db_path = tmp_path / "memory.db"
    with MemoryStore(db_path) as store:
        store.remember_result(
            MemoryInput(scope="demo", kind="fact", title="FTS5", content="Ядро використовує SQLite FTS5.")
        )
        pack = store.build_context_pack("FTS5", budget_chars=600, limit=5)

    assert pack["items"]
    assert "no direct match" not in pack["rendered"]
