import json

import pytest

from memory_kernel.cli import main
from memory_kernel.store import MemoryInput, MemoryStore


def _seed(tmp_path):
    db_path = tmp_path / "memory.db"
    with MemoryStore(db_path) as store:
        result = store.remember_result(
            MemoryInput(
                scope="project.alpha",
                kind="decision",
                title="Switch to Rust hot path",
                content="We decided to move the memory hot path to Rust for lower overhead.",
                tags=("rust", "memory"),
                source="session-001",
                importance=0.91,
                certainty=0.9,
            )
        )
    return db_path, result.id


def test_get_memory_returns_record(tmp_path):
    db_path, memory_id = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        record = store.get_memory(memory_id)
    assert record is not None
    assert record.id == memory_id
    assert record.title == "Switch to Rust hot path"
    assert record.tags == ("rust", "memory")


def test_get_memory_returns_none_for_unknown(tmp_path):
    db_path, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        assert store.get_memory("does-not-exist") is None


def test_delete_memory_removes_row(tmp_path):
    db_path, memory_id = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        assert store.delete_memory(memory_id) is True
        assert store.get_memory(memory_id) is None


def test_delete_memory_returns_false_for_unknown(tmp_path):
    db_path, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        assert store.delete_memory("does-not-exist") is False


def test_update_memory_changes_fields_and_keeps_others(tmp_path):
    db_path, memory_id = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        record = store.update_memory(
            memory_id,
            title="Switch hot path to Rust accelerator",
            importance=0.95,
        )
    assert record.title == "Switch hot path to Rust accelerator"
    assert record.importance == 0.95
    assert record.kind == "decision"
    assert record.tags == ("rust", "memory")


def test_update_memory_clears_tags_when_empty_sequence(tmp_path):
    db_path, memory_id = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        record = store.update_memory(memory_id, tags=[])
    assert record.tags == ()


def test_update_memory_raises_for_unknown(tmp_path):
    db_path, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        with pytest.raises(KeyError):
            store.update_memory("does-not-exist", title="anything")


def test_update_memory_validates_kind(tmp_path):
    db_path, memory_id = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        with pytest.raises(ValueError):
            store.update_memory(memory_id, kind="bogus")


def test_update_memory_changes_fingerprint_so_remember_dedupes(tmp_path):
    db_path, memory_id = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        store.update_memory(memory_id, title="Brand new title", content="Brand new content body.")
        result = store.remember_result(
            MemoryInput(
                scope="project.alpha",
                kind="decision",
                title="Brand new title",
                content="Brand new content body.",
                tags=("rust", "memory"),
                source="session-002",
                importance=0.5,
                certainty=0.7,
            )
        )
    assert result.id == memory_id
    assert result.action == "updated"


def test_cli_show_prints_record(tmp_path, capsys):
    db_path, memory_id = _seed(tmp_path)
    exit_code = main(["--db", str(db_path), "show", "--id", memory_id, "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == memory_id
    assert payload["title"] == "Switch to Rust hot path"


def test_cli_show_missing_returns_nonzero(tmp_path, capsys):
    db_path, _ = _seed(tmp_path)
    exit_code = main(["--db", str(db_path), "show", "--id", "missing"])
    assert exit_code == 1
    assert "memory not found" in capsys.readouterr().err


def test_cli_update_changes_title(tmp_path, capsys):
    db_path, memory_id = _seed(tmp_path)
    exit_code = main(
        [
            "--db",
            str(db_path),
            "update",
            "--id",
            memory_id,
            "--title",
            "Renamed via CLI",
            "--json",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Renamed via CLI"

    with MemoryStore(db_path) as store:
        record = store.get_memory(memory_id)
    assert record.title == "Renamed via CLI"


def test_cli_update_no_fields_returns_nonzero(tmp_path, capsys):
    db_path, memory_id = _seed(tmp_path)
    exit_code = main(["--db", str(db_path), "update", "--id", memory_id])
    assert exit_code == 1
    assert "at least one field" in capsys.readouterr().err


def test_cli_delete_removes_memory(tmp_path, capsys):
    db_path, memory_id = _seed(tmp_path)
    exit_code = main(["--db", str(db_path), "delete", "--id", memory_id, "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"id": memory_id, "action": "deleted"}

    with MemoryStore(db_path) as store:
        assert store.get_memory(memory_id) is None


def test_cli_delete_missing_returns_nonzero(tmp_path, capsys):
    db_path, _ = _seed(tmp_path)
    exit_code = main(["--db", str(db_path), "delete", "--id", "missing"])
    assert exit_code == 1
    assert "memory not found" in capsys.readouterr().err


def test_list_memories_returns_records_ordered_by_updated_at(tmp_path):
    db_path, first_id = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        second = store.remember_result(
            MemoryInput(
                scope="project.beta",
                kind="task",
                title="Second memory",
                content="Add a second memory for ordering test.",
                tags=("ordering",),
            )
        )
        records = store.list_memories(limit=10)

    assert len(records) == 2
    assert records[0].id == second.id
    assert records[1].id == first_id


def test_list_memories_filters_by_scope_and_kind(tmp_path):
    db_path, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        store.remember_result(
            MemoryInput(
                scope="project.beta",
                kind="task",
                title="Beta task",
                content="Unrelated task in beta scope.",
            )
        )
        scoped = store.list_memories(scope="project.alpha")
        kinded = store.list_memories(kind="task")

    assert len(scoped) == 1
    assert scoped[0].scope == "project.alpha"
    assert len(kinded) == 1
    assert kinded[0].kind == "task"


def test_list_memories_respects_limit(tmp_path):
    db_path = tmp_path / "memory.db"
    with MemoryStore(db_path) as store:
        for index in range(5):
            store.remember_result(
                MemoryInput(
                    scope="bulk", kind="note",
                    title=f"Note {index}", content=f"Content {index}",
                )
            )
        records = store.list_memories(limit=3)
    assert len(records) == 3


def test_cli_list_returns_json(tmp_path, capsys):
    db_path, memory_id = _seed(tmp_path)
    exit_code = main(["--db", str(db_path), "list", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert any(item["id"] == memory_id for item in payload)


def test_preview_ingest_does_not_write(tmp_path):
    db_path = tmp_path / "memory.db"
    with MemoryStore(db_path) as store:
        report = store.preview_ingest(
            "Прийнято рішення мігрувати. Треба написати тести.",
            scope="dryrun.test",
        )
        assert report["segments"] == 2
        assert len(report["items"]) == 2
        assert all(set(item.keys()) >= {"kind", "title", "tags", "importance", "certainty"} for item in report["items"])
        assert store.list_memories(limit=10) == []


def test_cli_ingest_dry_run_skips_database_writes(tmp_path, capsys):
    db_path = tmp_path / "memory.db"
    exit_code = main(
        [
            "--db", str(db_path),
            "ingest",
            "--scope", "dryrun.cli",
            "--text", "Прийнято рішення мігрувати.\nТреба написати тести.",
            "--dry-run",
            "--json",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "dryrun.cli"
    assert payload["segments"] == 2

    with MemoryStore(db_path) as store:
        assert store.list_memories(limit=10) == []


def test_stats_with_since_includes_recent_counts(tmp_path):
    from datetime import datetime, timedelta, timezone

    db_path, _ = _seed(tmp_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    with MemoryStore(db_path) as store:
        payload = store.stats(since=cutoff)

    assert "since" in payload
    assert payload["created_since"] == 1
    assert payload["updated_since"] == 1
    assert payload["by_kind_since"] == {"decision": 1}


def test_cli_stats_since_relative_works(tmp_path, capsys):
    db_path, _ = _seed(tmp_path)
    exit_code = main(["--db", str(db_path), "stats", "--since", "7d", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "since" in payload
    assert payload["created_since"] == 1


def test_cli_stats_since_invalid_returns_nonzero(tmp_path, capsys):
    db_path, _ = _seed(tmp_path)
    exit_code = main(["--db", str(db_path), "stats", "--since", "garbage"])
    assert exit_code == 1
    assert "--since" in capsys.readouterr().err


def test_verify_clean_database_is_healthy(tmp_path):
    db_path, _ = _seed(tmp_path)
    with MemoryStore(db_path) as store:
        report = store.verify()
    assert report["healthy"] is True
    assert report["stems_text_mismatches"] == []
    assert report["fingerprint_mismatches"] == []
    assert report["fts_count_mismatch"] is None


def test_verify_detects_stems_text_drift(tmp_path):
    import sqlite3

    db_path, memory_id = _seed(tmp_path)
    with sqlite3.connect(db_path) as raw:
        raw.execute(
            "UPDATE memories SET stems_text = 'corrupted' WHERE id = ?",
            (memory_id,),
        )
    with MemoryStore(db_path) as store:
        report = store.verify()
    assert report["healthy"] is False
    assert memory_id in report["stems_text_mismatches"]


def test_verify_repair_fixes_stems_text(tmp_path):
    import sqlite3

    db_path, memory_id = _seed(tmp_path)
    with sqlite3.connect(db_path) as raw:
        raw.execute(
            "UPDATE memories SET stems_text = 'corrupted' WHERE id = ?",
            (memory_id,),
        )
    with MemoryStore(db_path) as store:
        report = store.verify(repair=True)
    assert report["healthy"] is True
    assert report["repaired_stems"] == 1


def test_verify_detects_fingerprint_drift_and_repairs(tmp_path):
    import sqlite3

    db_path, memory_id = _seed(tmp_path)
    with sqlite3.connect(db_path) as raw:
        raw.execute(
            "UPDATE memories SET fingerprint = 'wrong' WHERE id = ?",
            (memory_id,),
        )
    with MemoryStore(db_path) as store:
        before = store.verify()
        repaired = store.verify(repair=True)

    assert before["healthy"] is False
    assert memory_id in before["fingerprint_mismatches"]
    assert repaired["healthy"] is True
    assert repaired["repaired_fingerprints"] == 1


def test_cli_verify_returns_nonzero_when_unhealthy(tmp_path, capsys):
    import sqlite3

    db_path, memory_id = _seed(tmp_path)
    with sqlite3.connect(db_path) as raw:
        raw.execute(
            "UPDATE memories SET stems_text = 'corrupted' WHERE id = ?",
            (memory_id,),
        )
    exit_code = main(["--db", str(db_path), "verify"])
    assert exit_code == 1


_END_OF_INPUT = object()


def _make_input_mock(scripted):
    iterator = iter(scripted)

    def mock(prompt: str = "") -> str:
        try:
            value = next(iterator)
        except StopIteration:
            raise EOFError()
        if value is _END_OF_INPUT:
            raise EOFError()
        return value

    return mock


def test_interactive_ingest_creates_memories_after_confirmation(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "memory.db"
    scripted = [
        "interactive.test",
        "session-001",
        "tag1 tag2",
        "Прийнято рішення мігрувати базу.",
        "Треба написати тести міграції.",
        _END_OF_INPUT,
        "y",
    ]
    monkeypatch.setattr("builtins.input", _make_input_mock(scripted))

    exit_code = main(["--db", str(db_path), "ingest", "--interactive"])
    assert exit_code == 0

    with MemoryStore(db_path) as store:
        records = store.list_memories(limit=10)
    assert len(records) == 2
    titles = {r.title for r in records}
    assert any("міграц" in t.lower() or "тести" in t.lower() for t in titles)


def test_interactive_ingest_cancel_writes_nothing(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    scripted = [
        "interactive.cancel",
        "",
        "",
        "Прийнято рішення мігрувати.",
        _END_OF_INPUT,
        "n",
    ]
    monkeypatch.setattr("builtins.input", _make_input_mock(scripted))

    exit_code = main(["--db", str(db_path), "ingest", "--interactive"])
    assert exit_code == 0

    with MemoryStore(db_path) as store:
        assert store.list_memories(limit=10) == []


def test_interactive_ingest_rejects_empty_scope(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "memory.db"
    monkeypatch.setattr("builtins.input", _make_input_mock([""]))
    exit_code = main(["--db", str(db_path), "ingest", "--interactive"])
    assert exit_code == 1
    assert "scope is required" in capsys.readouterr().err


def test_interactive_ingest_rejects_combo_with_text(tmp_path, capsys):
    exit_code = main(
        ["--db", str(tmp_path / "memory.db"), "ingest", "--interactive", "--text", "anything"]
    )
    assert exit_code == 1
    assert "cannot be combined" in capsys.readouterr().err


def test_ingest_without_scope_or_interactive_returns_nonzero(tmp_path, capsys):
    exit_code = main(
        ["--db", str(tmp_path / "memory.db"), "ingest", "--text", "some text"]
    )
    assert exit_code == 1
    assert "--scope is required" in capsys.readouterr().err


def test_completion_bash_lists_all_subcommands(capsys):
    exit_code = main(["completion", "bash"])
    assert exit_code == 0
    out = capsys.readouterr().out
    for cmd in [
        "init", "remember", "ingest", "search", "context", "wake-up",
        "list", "show", "update", "delete", "verify", "stats",
        "export", "import", "completion",
    ]:
        assert cmd in out, f"bash completion missing {cmd!r}"
    assert "decision constraint preference task fact note" in out
    assert "complete -F _memory_kernel_complete memory-kernel" in out


def test_completion_powershell_lists_all_subcommands(capsys):
    exit_code = main(["completion", "powershell"])
    assert exit_code == 0
    out = capsys.readouterr().out
    for cmd in [
        "init", "remember", "ingest", "search", "list", "show",
        "update", "delete", "verify", "stats", "export", "import",
    ]:
        assert f"'{cmd}'" in out, f"powershell completion missing {cmd!r}"
    assert "Register-ArgumentCompleter" in out
    assert "'decision'" in out


def test_cli_verify_repair_returns_zero(tmp_path, capsys):
    import sqlite3

    db_path, memory_id = _seed(tmp_path)
    with sqlite3.connect(db_path) as raw:
        raw.execute(
            "UPDATE memories SET stems_text = 'corrupted' WHERE id = ?",
            (memory_id,),
        )
    exit_code = main(["--db", str(db_path), "verify", "--repair", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["healthy"] is True
    assert payload["repaired_stems"] == 1
