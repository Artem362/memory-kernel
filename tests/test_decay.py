from datetime import datetime, timedelta, timezone

import pytest

from memory_kernel.cli import main
from memory_kernel.store import MemoryInput, MemoryStore, retention_score


def _old_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def _seed_with_age(store, *, kind, title, content, days_old, access_count=0, importance=0.5):
    """Insert a memory and force its timestamps to simulate age."""
    rid = store.remember_result(
        MemoryInput(scope="decay.test", kind=kind, title=title, content=content, importance=importance)
    ).id
    old = _old_iso(days_old)
    with store._connect() as con:
        con.execute(
            "UPDATE memories SET created_at = ?, updated_at = ?, last_accessed_at = ?, access_count = ? WHERE id = ?",
            (old, old, None if access_count == 0 else old, access_count, rid),
        )
    return rid


def test_retention_score_high_for_important_recent():
    now = datetime.now(timezone.utc)
    fresh = retention_score(importance=0.9, access_count=5, last_seen=now.isoformat(), now=now)
    stale = retention_score(importance=0.3, access_count=0, last_seen=_old_iso(120), now=now)
    assert fresh > stale
    assert fresh >= 0.5
    assert stale < 0.35


def test_decay_archives_old_unused_note(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        rid = _seed_with_age(store, kind="note", title="Trivial", content="Якась дрібна нотатка без значення.", days_old=90)
        report = store.decay(dry_run=False)
        assert report["archived"] == 1
        assert report["items"][0]["id"] == rid
        # archived -> hidden from search
        assert store.get_memory(rid).archived_at is not None


def test_decay_protects_decisions_and_constraints(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        _seed_with_age(store, kind="decision", title="Big call", content="Старе важливе рішення.", days_old=200, importance=0.84)
        _seed_with_age(store, kind="constraint", title="Rule", content="Старе обмеження.", days_old=200, importance=0.82)
        report = store.decay(dry_run=False)
        assert report["scanned"] == 0  # decision/constraint not even eligible
        assert report["archived"] == 0


def test_decay_dry_run_does_not_write(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        rid = _seed_with_age(store, kind="fact", title="Old fact", content="Стародавній факт нікому не потрібен.", days_old=120)
        report = store.decay(dry_run=True)
        assert report["candidates"] == 1
        assert report["archived"] == 0
        assert store.get_memory(rid).archived_at is None


def test_decay_skips_recent_memories(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        _seed_with_age(store, kind="note", title="Recent", content="Свіжа нотатка створена щойно.", days_old=2)
        report = store.decay(dry_run=False, min_age_days=30)
        assert report["archived"] == 0


def test_decay_skips_frequently_accessed(tmp_path):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        _seed_with_age(store, kind="note", title="Hot note", content="Стара але часто згадувана нотатка.", days_old=120, access_count=9)
        report = store.decay(dry_run=False, max_access=1)
        assert report["archived"] == 0


def test_cli_decay_dry_run(tmp_path, capsys):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        _seed_with_age(store, kind="note", title="Stale", content="Стара нотатка для забуття.", days_old=99)
    exit_code = main(["--db", str(db), "decay", "--dry-run", "--json"])
    assert exit_code == 0
    import json

    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["candidates"] == 1
    assert report["archived"] == 0


def test_cli_decay_applies(tmp_path, capsys):
    db = tmp_path / "m.db"
    with MemoryStore(db) as store:
        rid = _seed_with_age(store, kind="fact", title="Forgotten", content="Факт, який час прибрати з памʼяті.", days_old=150)
    exit_code = main(["--db", str(db), "decay", "--json"])
    assert exit_code == 0
    import json

    report = json.loads(capsys.readouterr().out)
    assert report["archived"] == 1
    with MemoryStore(db) as store:
        assert store.get_memory(rid).archived_at is not None
