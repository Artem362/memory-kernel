import pytest

from memory_kernel.accelerator import native_accel
from memory_kernel.store import canonicalize_text


def test_canonicalize_text_strips_apostrophes_keeps_word():
    assert canonicalize_text("Обов'язково") == "обовязково"
    assert canonicalize_text("Памʼять") == "память"
    assert canonicalize_text("can't won't") == "cant wont"
    assert canonicalize_text("don’t") == "dont"


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
@pytest.mark.parametrize(
    "text,expected_kind",
    [
        ("Вирішили перенести гарячий шлях памяті у Rust.", "decision"),
        ("Памʼять повинно бути локально і дешево.", "constraint"),
        ("Треба зробити бенчмарк інжесту проти Python fallback.", "task"),
        ("Краще точний пошук, ніж розмитий векторний.", "preference"),
        ("Ядро використовує SQLite FTS5 для локального пошуку.", "fact"),
    ],
)
def test_native_ukrainian_infer_kind(text, expected_kind):
    assert native_accel.infer_kind(text) == expected_kind


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
def test_native_ukrainian_semantic_terms_filters_stop_words():
    text = "Ми вирішили перейти на Rust для продуктивності памяті."
    terms = native_accel.semantic_terms(text, -1)

    for stop in ("ми", "на", "для"):
        assert stop not in terms

    assert "вирішили" in terms
    assert "продуктивності" in terms


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
def test_native_ukrainian_extract_terms_and_fts():
    query = "бенчмарк продуктивності памяті"
    terms = native_accel.extract_terms(query)
    assert "бенчмарк" in terms
    assert "продуктивності" in terms

    fts = native_accel.build_fts_query(query)
    assert "бенчмарк*" in fts
    assert "продуктивності*" in fts


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
def test_native_ukrainian_derive_title_strips_prefix():
    title = native_accel.derive_title(
        "Вирішили перенести гарячий шлях у Rust", "decision", 10, 72
    )
    lowered = title.lower()
    assert not lowered.startswith("вирішили"), title


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
@pytest.mark.parametrize(
    "text,expected_kind",
    [
        ("Обов'язково тримаємо памʼять локально.", "constraint"),
        ("Пам'ять не можна виносити з машини.", "constraint"),
        ("Пам'ять обов'язково має бути локально.", "constraint"),
    ],
)
def test_native_apostrophe_does_not_break_classification(text, expected_kind):
    assert native_accel.infer_kind(text) == expected_kind


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
def test_native_apostrophe_keeps_word_intact():
    terms = native_accel.semantic_terms(
        "Обов'язково тримаємо пам'ять локально, маємо п'ять рішень.", -1
    )
    assert "обовязково" in terms
    assert "память" in terms
    assert "пять" in terms
    assert "обов" not in terms
    assert "ять" not in terms
    assert "пам" not in terms


@pytest.mark.skipif(native_accel is None, reason="native accelerator is not built")
def test_native_ukrainian_importance_and_certainty():
    text = "Памʼять повинно бути локально, це обовязково для продакшну."
    importance = native_accel.infer_importance(text, "constraint")
    certainty = native_accel.infer_certainty(text, "constraint")

    assert importance >= 0.85
    assert certainty >= 0.88


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
