import json

from memory_kernel.cli import main
from memory_kernel.store import MemoryInput, MemoryStore


def build_store(tmp_path):
    db_path = tmp_path / "memory.db"
    with MemoryStore(db_path) as store:
        store.remember_result(
            MemoryInput(
                scope="project.ai-memory",
                kind="decision",
                title="Switch to Rust hot path",
                content="We decided to move the memory hot path to Rust for lower overhead.",
                tags=("rust", "memory"),
                source="session-001",
                importance=0.91,
                certainty=0.9,
            )
        )
        store.remember_result(
            MemoryInput(
                scope="project.ops",
                kind="fact",
                title="Keep staging cache",
                content="Redis remains a staging-only cache for deployment rehearsal.",
                tags=("redis", "staging"),
                source="ops-notes",
                importance=0.62,
                certainty=0.82,
            )
        )
    return db_path


def test_export_memories_respects_filters(tmp_path):
    db_path = build_store(tmp_path)
    with MemoryStore(db_path) as store:
        payload = store.export_memories(scope="project.ai-memory", tags=("rust",))

    assert len(payload) == 1
    assert payload[0]["title"] == "Switch to Rust hot path"
    assert payload[0]["scope"] == "project.ai-memory"
    assert payload[0]["tags"] == ["rust", "memory"]
    assert "score" not in payload[0]
    assert "excerpt" not in payload[0]


def test_cli_export_writes_jsonl(tmp_path):
    db_path = build_store(tmp_path)
    export_path = tmp_path / "exports" / "memory.jsonl"

    exit_code = main(
        [
            "--db",
            str(db_path),
            "export",
            "--scope",
            "project.ai-memory",
            "--format",
            "jsonl",
            "--output",
            str(export_path),
        ]
    )

    assert exit_code == 0
    lines = [
        json.loads(line)
        for line in export_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["scope"] == "project.ai-memory"
    assert lines[0]["title"] == "Switch to Rust hot path"


def test_cli_import_roundtrip_json_snapshot(tmp_path):
    source_db_path = build_store(tmp_path / "source")
    export_path = tmp_path / "exports" / "memory.json"
    target_db_path = tmp_path / "target" / "memory.db"

    export_code = main(
        [
            "--db",
            str(source_db_path),
            "export",
            "--format",
            "json",
            "--output",
            str(export_path),
        ]
    )
    assert export_code == 0

    import_code = main(
        [
            "--db",
            str(target_db_path),
            "import",
            "--file",
            str(export_path),
        ]
    )
    assert import_code == 0

    with MemoryStore(source_db_path) as source_store:
        source_payload = source_store.export_memories()
    with MemoryStore(target_db_path) as target_store:
        target_payload = target_store.export_memories()

    assert sorted(item["id"] for item in target_payload) == sorted(
        item["id"] for item in source_payload
    )
    assert sorted(item["title"] for item in target_payload) == sorted(
        item["title"] for item in source_payload
    )


def test_cli_import_roundtrip_jsonl_auto_detect(tmp_path):
    source_db_path = build_store(tmp_path / "source-jsonl")
    export_path = tmp_path / "exports" / "memory.jsonl"
    target_db_path = tmp_path / "target-jsonl" / "memory.db"

    export_code = main(
        [
            "--db",
            str(source_db_path),
            "export",
            "--format",
            "jsonl",
            "--output",
            str(export_path),
        ]
    )
    assert export_code == 0

    import_code = main(
        [
            "--db",
            str(target_db_path),
            "import",
            "--file",
            str(export_path),
        ]
    )
    assert import_code == 0

    with MemoryStore(target_db_path) as target_store:
        payload = target_store.export_memories()

    assert len(payload) == 2
    assert payload[0]["title"] in {"Switch to Rust hot path", "Keep staging cache"}
