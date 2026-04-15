from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .accelerator import (
    has_experimental_native_ranking,
    has_native_acceleration,
    native_accel,
)


VALID_KINDS = (
    "decision",
    "constraint",
    "preference",
    "task",
    "fact",
    "note",
)

ACTIONABILITY_BONUS = {
    "decision": 0.22,
    "constraint": 0.20,
    "task": 0.17,
    "preference": 0.14,
    "fact": 0.11,
    "note": 0.06,
}

TOKEN_RE = re.compile(r"\w+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")
BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s*")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
NON_WORD_RE = re.compile(r"[^\w\s-]+", re.UNICODE)
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "we",
    "what",
    "when",
    "where",
    "why",
    "with",
    "але",
    "без",
    "було",
    "бути",
    "в",
    "ви",
    "вже",
    "він",
    "вона",
    "воно",
    "для",
    "до",
    "є",
    "за",
    "з",
    "і",
    "й",
    "її",
    "їх",
    "коли",
    "ми",
    "на",
    "не",
    "ні",
    "про",
    "та",
    "те",
    "ти",
    "то",
    "у",
    "це",
    "цей",
    "ця",
    "що",
    "як",
}
MIN_INGEST_CHARS = 12
NATIVE_RANKING_MIN_CANDIDATES = 24
BASE_IMPORTANCE = {
    "decision": 0.84,
    "constraint": 0.82,
    "task": 0.78,
    "preference": 0.66,
    "fact": 0.63,
    "note": 0.46,
}
BASE_CERTAINTY = {
    "decision": 0.90,
    "constraint": 0.88,
    "task": 0.82,
    "preference": 0.80,
    "fact": 0.77,
    "note": 0.70,
}
KIND_HINTS = {
    "decision": (
        "we decided",
        "decision",
        "switch to",
        "replace",
        "adopt",
        "selected",
        "choose",
        "chosen",
        "agreed",
        "вирішили",
        "обрали",
        "переходимо",
        "замінюємо",
    ),
    "constraint": (
        "must",
        "must stay",
        "cannot",
        "can't",
        "never",
        "limit",
        "budget",
        "required",
        "should stay",
        "обовязково",
        "повинно",
        "має",
        "не можна",
        "ліміт",
        "бюджет",
    ),
    "task": (
        "todo",
        "next step",
        "follow up",
        "need to",
        "implement",
        "fix",
        "add",
        "ship",
        "зробити",
        "треба",
        "потрібно",
        "додати",
        "виправити",
        "реалізувати",
    ),
    "preference": (
        "prefer",
        "would rather",
        "want",
        "avoid",
        "ideally",
        "краще",
        "хочемо",
        "уникаємо",
        "бажано",
    ),
    "fact": (
        "currently",
        "today",
        "uses",
        "contains",
        "runs on",
        "станом",
        "використовує",
        "містить",
        "працює на",
    ),
}
STRONG_SIGNAL_WORDS = {
    "must",
    "critical",
    "production",
    "security",
    "deadline",
    "blocked",
    "important",
    "never",
    "обовязково",
    "критично",
    "дедлайн",
    "блокер",
}
HEDGE_WORDS = {
    "maybe",
    "might",
    "perhaps",
    "probably",
    "consider",
    "idea",
    "possibly",
    "можливо",
    "мабуть",
    "ідея",
}
TITLE_PREFIX_PATTERNS = {
    "decision": (
        r"^(?:we\s+decided\s+to|decided\s+to|decision:\s*|we\s+will\s+|switch\s+to\s+|adopt\s+|use\s+|вирішили\s+|обрали\s+|будемо\s+|переходимо\s+на\s+|замінюємо\s+)",
    ),
    "constraint": (
        r"^(?:must\s+|must\s+stay\s+|cannot\s+|never\s+|should\s+|обовязково\s+|повинно\s+|має\s+|не\s+можна\s+)",
    ),
    "task": (
        r"^(?:todo:\s*|todo\s+|need\s+to\s+|implement\s+|fix\s+|add\s+|зробити\s+|треба\s+|потрібно\s+|додати\s+|виправити\s+|реалізувати\s+)",
    ),
    "preference": (
        r"^(?:prefer\s+|want\s+|avoid\s+|краще\s+|хочемо\s+|уникаємо\s+|бажано\s+)",
    ),
}


@dataclass(frozen=True)
class MemoryInput:
    scope: str
    kind: str
    title: str
    content: str
    summary: str = ""
    tags: Sequence[str] = ()
    source: str = ""
    importance: float = 0.5
    certainty: float = 0.7


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    scope: str
    kind: str
    title: str
    summary: str
    content: str
    tags: tuple[str, ...]
    source: str
    importance: float
    certainty: float
    access_count: int
    created_at: str
    updated_at: str
    last_accessed_at: str | None
    score: float = 0.0
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True)
class RememberResult:
    id: str
    scope: str
    kind: str
    title: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ImportedMemoryRecord:
    id: str
    scope: str
    kind: str
    title: str
    summary: str
    content: str
    tags: tuple[str, ...]
    source: str
    importance: float
    certainty: float
    access_count: int
    created_at: str
    updated_at: str
    last_accessed_at: str | None


def can_use_native_text(*values: str) -> bool:
    return native_accel is not None and all(value.isascii() for value in values)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_space(value: str) -> str:
    cleaned = value.replace("\ufeff", " ").replace("\u200b", " ")
    return SPACE_RE.sub(" ", cleaned.strip())


def normalize_tags(tags: Sequence[str]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for tag in tags:
        item = normalize_space(tag).lower()
        if item and item not in cleaned:
            cleaned.append(item)
    return tuple(cleaned)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def derive_summary(text: str, max_chars: int = 180) -> str:
    if native_accel is not None:
        return native_accel.derive_summary(text, max_chars)
    lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
    if not lines:
        return ""
    source = lines[0]
    if len(source) <= max_chars:
        return source
    return source[: max_chars - 3].rstrip() + "..."


def canonicalize_text(value: str) -> str:
    lowered = normalize_space(value).lower()
    lowered = NON_WORD_RE.sub(" ", lowered)
    return normalize_space(lowered)


def semantic_terms(text: str, *, limit: int | None = None) -> list[str]:
    if can_use_native_text(text):
        native_limit = -1 if limit is None else limit
        return list(native_accel.semantic_terms(text, native_limit))
    seen: list[str] = []
    for token in TOKEN_RE.findall(canonicalize_text(text)):
        if len(token) < 3:
            continue
        if token in STOP_WORDS:
            continue
        if token not in seen:
            seen.append(token)
        if limit is not None and len(seen) >= limit:
            break
    return seen


def token_overlap_score(left: str, right: str) -> float:
    if can_use_native_text(left, right):
        return float(native_accel.token_overlap_score(left, right))
    left_terms = set(semantic_terms(left))
    right_terms = set(semantic_terms(right))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def duplicate_match_score(left: str, right: str) -> float:
    if native_accel is not None:
        return float(native_accel.duplicate_match_score(left, right))
    left_terms = set(semantic_terms(left))
    right_terms = set(semantic_terms(right))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / min(len(left_terms), len(right_terms))


def text_information_score(text: str) -> float:
    cleaned = normalize_space(text)
    return len(cleaned) + len(set(semantic_terms(cleaned))) * 12


def choose_richer_text(existing: str, candidate: str, *, max_chars: int | None = None) -> str:
    if native_accel is not None:
        native_limit = -1 if max_chars is None else max_chars
        return native_accel.choose_richer_text(existing, candidate, native_limit)
    existing_clean = normalize_space(existing)
    candidate_clean = normalize_space(candidate)
    best = max((existing_clean, candidate_clean), key=text_information_score)
    if max_chars is not None and len(best) > max_chars:
        best = best[:max_chars].rsplit(" ", 1)[0] or best[:max_chars]
    return best


def merge_sources(existing: str, candidate: str, *, max_chars: int = 240) -> str:
    if native_accel is not None:
        return native_accel.merge_sources(existing, candidate, max_chars)
    values: list[str] = []
    for raw in (existing, candidate):
        cleaned = normalize_space(raw)
        if not cleaned:
            continue
        for item in cleaned.split("; "):
            if item and item not in values:
                values.append(item)

    merged = "; ".join(values)
    if len(merged) <= max_chars:
        return merged
    return merged[: max_chars - 3].rstrip() + "..."


def compute_fingerprint(scope: str, kind: str, title: str, content: str) -> str:
    basis = "\n".join(
        [
            canonicalize_text(scope),
            canonicalize_text(kind),
            canonicalize_text(title),
            canonicalize_text(content),
        ]
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def derive_title(text: str, kind: str, max_words: int = 10, max_chars: int = 72) -> str:
    if can_use_native_text(text, kind):
        return native_accel.derive_title(text, kind, max_words, max_chars)
    candidate = normalize_space(text)
    for pattern in TITLE_PREFIX_PATTERNS.get(kind, ()):
        candidate = normalize_space(re.sub(pattern, "", candidate, flags=re.IGNORECASE))
    if not candidate:
        candidate = normalize_space(text)

    title = " ".join(candidate.split()[:max_words]).rstrip(" ,:;.-")
    if len(title) > max_chars:
        title = title[:max_chars].rsplit(" ", 1)[0] or title[:max_chars]
    return title or derive_summary(text, max_chars=max_chars)


def infer_kind(text: str) -> str:
    if can_use_native_text(text):
        return native_accel.infer_kind(text)
    lowered = canonicalize_text(text)
    scores = {kind: 0 for kind in VALID_KINDS}

    for kind, hints in KIND_HINTS.items():
        for hint in hints:
            if hint in lowered:
                scores[kind] += 2

    if lowered.startswith("todo") or lowered.startswith("next step"):
        scores["task"] += 4
    if lowered.startswith("note"):
        scores["note"] += 2
    if any(word in lowered for word in ("must", "never", "cannot", "повинно", "не можна")):
        scores["constraint"] += 1
    if any(word in lowered for word in ("decided", "switch to", "replace", "вирішили", "обрали")):
        scores["decision"] += 1

    best_kind = max(scores, key=scores.get)
    if scores[best_kind] <= 0:
        return "fact" if any(hint in lowered for hint in KIND_HINTS["fact"]) else "note"
    return best_kind


def infer_importance(text: str, kind: str) -> float:
    if can_use_native_text(text, kind):
        return float(native_accel.infer_importance(text, kind))
    score = BASE_IMPORTANCE.get(kind, 0.5)
    lowered = canonicalize_text(text)

    if any(word in lowered for word in STRONG_SIGNAL_WORDS):
        score += 0.10
    if len(semantic_terms(text)) >= 6:
        score += 0.05
    if kind == "note" and len(lowered) < 40:
        score -= 0.08

    return round(min(max(score, 0.05), 1.0), 2)


def infer_certainty(text: str, kind: str) -> float:
    if can_use_native_text(text, kind):
        return float(native_accel.infer_certainty(text, kind))
    score = BASE_CERTAINTY.get(kind, 0.7)
    lowered = canonicalize_text(text)

    if any(word in lowered for word in HEDGE_WORDS):
        score -= 0.18
    if any(word in lowered for word in STRONG_SIGNAL_WORDS):
        score += 0.06

    return round(min(max(score, 0.2), 0.99), 2)


def derive_candidate_tags(text: str, *, base_tags: Sequence[str] = (), limit: int = 6) -> tuple[str, ...]:
    if can_use_native_text(text, *base_tags):
        return tuple(native_accel.derive_candidate_tags(text, list(base_tags), limit))
    tags = list(normalize_tags(base_tags))
    for term in semantic_terms(text, limit=10):
        if term not in tags:
            tags.append(term)
        if len(tags) >= limit:
            break
    return tuple(tags)


def _split_ingest_chunk(text: str, *, max_chars: int = 320, force_sentences: bool = False) -> list[str]:
    cleaned = normalize_space(text)
    if not cleaned:
        return []

    pieces = [normalize_space(part) for part in SENTENCE_SPLIT_RE.split(cleaned) if normalize_space(part)]
    if force_sentences and len(pieces) > 1:
        return [piece if len(piece) <= max_chars else piece[: max_chars - 3].rstrip() + "..." for piece in pieces]

    if len(cleaned) <= max_chars:
        return [cleaned]
    if len(pieces) <= 1:
        return [cleaned[: max_chars - 3].rstrip() + "..."]

    results: list[str] = []
    buffer = ""
    for piece in pieces:
        candidate = f"{buffer} {piece}".strip() if buffer else piece
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            results.append(buffer)
        buffer = piece

    if buffer:
        results.append(buffer)
    return results


def split_memory_candidates(text: str, *, max_items: int = 24, max_chars: int = 320) -> list[str]:
    if native_accel is not None:
        return list(native_accel.split_memory_candidates(text, max_items, max_chars))
    raw_lines = [
        normalize_space(BULLET_PREFIX_RE.sub("", line))
        for line in text.replace("\r\n", "\n").splitlines()
    ]

    segments: list[str] = []
    for line in raw_lines:
        if not line:
            continue
        segments.extend(_split_ingest_chunk(line, max_chars=max_chars))

    if len(segments) <= 1:
        segments = _split_ingest_chunk(
            normalize_space(text),
            max_chars=max_chars,
            force_sentences=True,
        )

    seen: set[str] = set()
    unique_segments: list[str] = []
    for segment in segments:
        cleaned = normalize_space(segment)
        if len(cleaned) < MIN_INGEST_CHARS:
            continue
        canonical = canonicalize_text(cleaned)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        unique_segments.append(cleaned)
        if len(unique_segments) >= max_items:
            break

    return unique_segments


def extract_terms(query: str) -> list[str]:
    if can_use_native_text(query):
        return list(native_accel.extract_terms(query))
    seen: list[str] = []
    for token in TOKEN_RE.findall(query.lower()):
        if len(token) < 2:
            continue
        if token in STOP_WORDS:
            continue
        if token not in seen:
            seen.append(token)
        if len(seen) >= 8:
            break
    return seen


def build_fts_query(query: str) -> str:
    if can_use_native_text(query):
        return native_accel.build_fts_query(query)
    terms = extract_terms(query)
    return " OR ".join(f"{term}*" for term in terms)


def make_excerpt(summary: str, content: str, terms: Sequence[str], max_chars: int = 220) -> str:
    if native_accel is not None:
        return native_accel.make_excerpt(summary, content, list(terms), max_chars)
    text = normalize_space(summary or content)
    if len(text) <= max_chars:
        return text
    if not terms:
        return text[: max_chars - 3].rstrip() + "..."

    lower = text.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    if not positions:
        return text[: max_chars - 3].rstrip() + "..."

    start = max(min(positions) - 40, 0)
    excerpt = text[start : start + max_chars]
    if start > 0:
        excerpt = "..." + excerpt[3:]
    if start + max_chars < len(text):
        excerpt = excerpt[:-3].rstrip() + "..."
    return excerpt


class MemoryStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._initialized = False
        self._connection: sqlite3.Connection | None = None

    def init(self) -> None:
        if self._initialized and self.db_path.exists():
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(self._schema_sql())
            self._migrate_schema(connection)
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', '2')"
            )
        self._initialized = True

    def remember(self, payload: MemoryInput) -> str:
        return self.remember_result(payload).id

    def remember_result(self, payload: MemoryInput) -> RememberResult:
        self.init()
        record = self._validate_input(payload)
        with self._connect() as connection:
            return self._remember_validated(connection, record)

    def ingest_text(
        self,
        text: str,
        *,
        scope: str,
        source: str = "",
        tags: Sequence[str] = (),
        max_items: int = 24,
        kind: str | None = None,
        importance: float | None = None,
        certainty: float | None = None,
    ) -> dict[str, Any]:
        self.init()
        segments = split_memory_candidates(text, max_items=max_items)
        items: list[dict[str, str]] = []

        with self._connect() as connection:
            for segment in segments:
                item_kind = kind or infer_kind(segment)
                payload = MemoryInput(
                    scope=scope,
                    kind=item_kind,
                    title=derive_title(segment, item_kind),
                    content=segment,
                    summary=derive_summary(segment),
                    tags=derive_candidate_tags(segment, base_tags=tags),
                    source=source,
                    importance=importance if importance is not None else infer_importance(segment, item_kind),
                    certainty=certainty if certainty is not None else infer_certainty(segment, item_kind),
                )
                result = self._remember_validated(connection, self._validate_input(payload))
                items.append(result.to_dict())

        created = sum(1 for item in items if item["action"] == "created")
        return {
            "scope": scope,
            "source": source,
            "segments": len(segments),
            "stored": len(items),
            "created": created,
            "updated": len(items) - created,
            "items": items,
        }

    def search(
        self,
        query: str = "",
        *,
        limit: int = 5,
        scope: str | None = None,
        kind: str | None = None,
        tags: Sequence[str] = (),
    ) -> list[MemoryRecord]:
        self.init()
        normalized_tags = normalize_tags(tags)
        terms = extract_terms(query)
        fts_query = build_fts_query(query)

        with self._connect() as connection:
            if fts_query:
                rows = self._search_fts(
                    connection,
                    fts_query=fts_query,
                    limit=max(limit * 5, 25),
                    scope=scope,
                    kind=kind,
                    tags=normalized_tags,
                )
                if not rows:
                    rows = self._search_like(
                        connection,
                        query=query,
                        limit=max(limit * 5, 25),
                        scope=scope,
                        kind=kind,
                        tags=normalized_tags,
                    )
            else:
                rows = self._hot_rows(
                    connection,
                    limit=max(limit * 5, 25),
                    scope=scope,
                    kind=kind,
                    tags=normalized_tags,
                )

            top = self._rank_rows(rows, terms, limit=limit)
            self._record_access(connection, [item.id for item in top])
            return top

    def build_context_pack(
        self,
        query: str,
        *,
        budget_chars: int = 1200,
        limit: int = 5,
        scope: str | None = None,
        kind: str | None = None,
        tags: Sequence[str] = (),
    ) -> dict[str, Any]:
        results = self.search(
            query,
            limit=max(limit * 3, limit),
            scope=scope,
            kind=kind,
            tags=tags,
        )
        return self._render_pack(
            results=results,
            budget_chars=budget_chars,
            limit=limit,
            header=f"Context pack for: {query}",
        )

    def build_wake_up_pack(
        self,
        *,
        budget_chars: int = 800,
        limit: int = 6,
        scope: str | None = None,
    ) -> dict[str, Any]:
        results = self.search("", limit=max(limit * 3, limit), scope=scope)
        return self._render_pack(
            results=results,
            budget_chars=budget_chars,
            limit=limit,
            header="Wake-up pack",
        )

    def stats(self) -> dict[str, Any]:
        self.init()
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_kind = {
                row["kind"]: row["count"]
                for row in connection.execute(
                    "SELECT kind, COUNT(*) AS count FROM memories GROUP BY kind ORDER BY count DESC"
                ).fetchall()
            }
            by_scope = {
                row["scope"]: row["count"]
                for row in connection.execute(
                    "SELECT scope, COUNT(*) AS count FROM memories GROUP BY scope ORDER BY count DESC LIMIT 10"
                ).fetchall()
            }
        return {
            "database": str(self.db_path),
            "accelerator": "rust" if has_native_acceleration() else "python",
            "ranking_engine": self._ranking_engine_label(),
            "upsert_engine": self._upsert_engine_label(),
            "total_memories": total,
            "by_kind": by_kind,
            "top_scopes": by_scope,
        }

    def export_memories(
        self,
        *,
        scope: str | None = None,
        kind: str | None = None,
        tags: Sequence[str] = (),
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.init()
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than 0")

        normalized_tags = normalize_tags(tags)
        with self._connect() as connection:
            filter_sql, params = self._build_filters(
                scope=scope,
                kind=kind,
                tags=normalized_tags,
            )
            limit_sql = ""
            query_params: list[Any] = [*params]
            if limit is not None:
                limit_sql = "\n            LIMIT ?"
                query_params.append(limit)

            rows = connection.execute(
                f"""
                SELECT m.*
                FROM memories AS m
                WHERE 1 = 1
                {filter_sql}
                ORDER BY m.updated_at DESC, m.created_at DESC, m.rowid DESC
                {limit_sql}
                """,
                query_params,
            ).fetchall()

        return [self._row_to_export_dict(row) for row in rows]

    def import_memories(self, memories: Sequence[dict[str, Any]]) -> dict[str, Any]:
        self.init()
        items: list[dict[str, str]] = []

        with self._connect() as connection:
            for raw in memories:
                result = self._import_memory_record(
                    connection,
                    self._normalize_import_record(raw),
                )
                items.append(result.to_dict())

        created = sum(1 for item in items if item["action"] == "created")
        return {
            "stored": len(items),
            "created": created,
            "updated": len(items) - created,
            "items": items,
        }

    def close(self) -> None:
        if self._connection is None:
            return
        self._connection.close()
        self._connection = None

    def __enter__(self) -> MemoryStore:
        self.init()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = self._ensure_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA temp_store = MEMORY;
            PRAGMA foreign_keys = ON;
            """
        )
        self._connection = connection
        return connection

    def _schema_sql(self) -> str:
        return """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memories (
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

            CREATE INDEX IF NOT EXISTS idx_memories_scope_kind
                ON memories(scope, kind);
            CREATE INDEX IF NOT EXISTS idx_memories_hot
                ON memories(importance DESC, certainty DESC, access_count DESC, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memories_fingerprint
                ON memories(fingerprint);

            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                title,
                summary,
                content,
                tags_text,
                content='memories',
                content_rowid='rowid',
                tokenize='unicode61 remove_diacritics 2'
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memory_fts(rowid, title, summary, content, tags_text)
                VALUES (new.rowid, new.title, new.summary, new.content, new.tags_text);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, title, summary, content, tags_text)
                VALUES ('delete', old.rowid, old.title, old.summary, old.content, old.tags_text);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, title, summary, content, tags_text)
                VALUES ('delete', old.rowid, old.title, old.summary, old.content, old.tags_text);
                INSERT INTO memory_fts(rowid, title, summary, content, tags_text)
                VALUES (new.rowid, new.title, new.summary, new.content, new.tags_text);
            END;
        """

    def _validate_input(self, payload: MemoryInput) -> MemoryInput:
        scope = normalize_space(payload.scope)
        kind = normalize_space(payload.kind).lower()
        title = normalize_space(payload.title)
        content = normalize_space(payload.content)
        summary = normalize_space(payload.summary) or derive_summary(content)
        source = normalize_space(payload.source)
        tags = normalize_tags(payload.tags)

        if not scope:
            raise ValueError("scope is required")
        if kind not in VALID_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(VALID_KINDS)}")
        if not title:
            raise ValueError("title is required")
        if not content:
            raise ValueError("content is required")

        importance = float(payload.importance)
        certainty = float(payload.certainty)
        if not 0.0 <= importance <= 1.0:
            raise ValueError("importance must be between 0.0 and 1.0")
        if not 0.0 <= certainty <= 1.0:
            raise ValueError("certainty must be between 0.0 and 1.0")

        return MemoryInput(
            scope=scope,
            kind=kind,
            title=title,
            content=content,
            summary=summary,
            tags=tags,
            source=source,
            importance=importance,
            certainty=certainty,
        )

    def _search_fts(
        self,
        connection: sqlite3.Connection,
        *,
        fts_query: str,
        limit: int,
        scope: str | None,
        kind: str | None,
        tags: Sequence[str],
    ) -> list[sqlite3.Row]:
        filter_sql, params = self._build_filters(scope=scope, kind=kind, tags=tags)
        query = f"""
            SELECT m.*
            FROM memory_fts
            JOIN memories AS m ON m.rowid = memory_fts.rowid
            WHERE memory_fts MATCH ?
            {filter_sql}
            ORDER BY bm25(memory_fts, 5.0, 2.5, 1.0, 1.5) ASC
            LIMIT ?
        """
        return connection.execute(query, [fts_query, *params, limit]).fetchall()

    def _search_like(
        self,
        connection: sqlite3.Connection,
        *,
        query: str,
        limit: int,
        scope: str | None,
        kind: str | None,
        tags: Sequence[str],
    ) -> list[sqlite3.Row]:
        filter_sql, params = self._build_filters(scope=scope, kind=kind, tags=tags)
        pattern = f"%{query.lower()}%"
        query_sql = f"""
            SELECT m.*
            FROM memories AS m
            WHERE (
                lower(m.title) LIKE ?
                OR lower(m.summary) LIKE ?
                OR lower(m.content) LIKE ?
            )
            {filter_sql}
            ORDER BY m.importance DESC, m.certainty DESC, m.updated_at DESC
            LIMIT ?
        """
        return connection.execute(
            query_sql,
            [pattern, pattern, pattern, *params, limit],
        ).fetchall()

    def _hot_rows(
        self,
        connection: sqlite3.Connection,
        *,
        limit: int,
        scope: str | None,
        kind: str | None,
        tags: Sequence[str],
    ) -> list[sqlite3.Row]:
        filter_sql, params = self._build_filters(scope=scope, kind=kind, tags=tags)
        query = f"""
            SELECT m.*
            FROM memories AS m
            WHERE 1 = 1
            {filter_sql}
            ORDER BY m.importance DESC, m.certainty DESC, m.access_count DESC, m.updated_at DESC
            LIMIT ?
        """
        return connection.execute(query, [*params, limit]).fetchall()

    def _build_filters(
        self,
        *,
        scope: str | None,
        kind: str | None,
        tags: Sequence[str],
    ) -> tuple[str, list[Any]]:
        filters: list[str] = []
        params: list[Any] = []

        if scope:
            filters.append("AND m.scope = ?")
            params.append(scope)
        if kind:
            filters.append("AND m.kind = ?")
            params.append(kind)
        for tag in normalize_tags(tags):
            filters.append("AND lower(m.tags_text) LIKE ?")
            params.append(f"%{tag}%")

        return "\n".join(filters), params

    def _rank_rows(
        self,
        rows: Iterable[sqlite3.Row],
        terms: Sequence[str],
        *,
        limit: int,
    ) -> list[MemoryRecord]:
        row_list = list(rows)
        if self._should_use_native_ranking(len(row_list)):
            ranked_payload = native_accel.rank_rows_tuples(
                [
                    (
                        index,
                        row["kind"],
                        row["title"],
                        row["summary"],
                        row["content"],
                        row["tags_text"],
                        float(row["importance"]),
                        float(row["certainty"]),
                        int(row["access_count"]),
                        row["updated_at"],
                    )
                    for index, row in enumerate(row_list)
                ],
                list(terms),
                utc_now_iso(),
                limit,
            )
            return [
                self._row_to_record(
                    row_list[row_index],
                    score=score,
                    excerpt=excerpt,
                )
                for row_index, score, excerpt in ranked_payload
            ]

        ranked: list[MemoryRecord] = []

        for index, row in enumerate(row_list):
            tags = tuple(json.loads(row["tags_json"]))
            haystack = " ".join([row["title"], row["summary"], row["content"], row["tags_text"]]).lower()
            title = row["title"].lower()

            coverage = 0.0
            if terms:
                coverage = sum(1 for term in terms if term in haystack) / len(terms)

            title_bonus = 0.15 if any(term in title for term in terms) else 0.0
            recency_bonus = self._recency_score(row["updated_at"])
            access_bonus = min(row["access_count"], 8) / 8 * 0.14
            lexical_bonus = 1.15 / (index + 1)
            score = (
                lexical_bonus
                + coverage * 0.95
                + row["importance"] * 0.60
                + row["certainty"] * 0.25
                + recency_bonus * 0.22
                + access_bonus
                + title_bonus
                + ACTIONABILITY_BONUS.get(row["kind"], 0.05)
            )

            ranked.append(
                self._row_to_record(
                    row,
                    tags=tags,
                    score=round(score, 4),
                    excerpt=make_excerpt(row["summary"], row["content"], terms),
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    def _recency_score(self, timestamp: str | None) -> float:
        parsed = parse_timestamp(timestamp)
        if parsed is None:
            return 0.0
        age_days = max((datetime.now(timezone.utc) - parsed).total_seconds() / 86400, 0.0)
        return 1.0 / (1.0 + age_days / 14.0)

    def _record_access(self, connection: sqlite3.Connection, ids: Sequence[str]) -> None:
        if not ids:
            return
        now = utc_now_iso()
        connection.executemany(
            """
            UPDATE memories
            SET access_count = access_count + 1,
                last_accessed_at = ?
            WHERE id = ?
            """,
            [(now, memory_id) for memory_id in ids],
        )

    def _render_pack(
        self,
        *,
        results: Sequence[MemoryRecord],
        budget_chars: int,
        limit: int,
        header: str,
    ) -> dict[str, Any]:
        lines: list[str] = [header]
        items: list[dict[str, Any]] = []

        for result in results:
            if len(items) >= limit:
                break

            line = f"- [{result.kind}/{result.scope}] {result.title}: {result.excerpt}"
            if result.source:
                line += f" (source: {result.source})"

            candidate = "\n".join([*lines, line])
            if len(candidate) > budget_chars and items:
                break
            if len(candidate) > budget_chars:
                remaining = max(budget_chars - len("\n".join(lines)) - 1, 0)
                line = line[: max(remaining - 3, 0)].rstrip() + "..."

            items.append(
                {
                    "id": result.id,
                    "kind": result.kind,
                    "scope": result.scope,
                    "title": result.title,
                    "excerpt": result.excerpt,
                    "score": result.score,
                }
            )
            lines.append(line)

        rendered = "\n".join(lines)
        if len(rendered) > budget_chars:
            rendered = rendered[: max(budget_chars - 3, 0)].rstrip() + "..."

        return {
            "budget_chars": budget_chars,
            "used_chars": len(rendered),
            "items": items,
            "rendered": rendered,
        }

    def _should_use_native_ranking(self, candidate_count: int) -> bool:
        if native_accel is None:
            return False
        if has_experimental_native_ranking():
            return True
        return candidate_count >= NATIVE_RANKING_MIN_CANDIDATES

    def _ranking_engine_label(self) -> str:
        if native_accel is None:
            return "python"
        if has_experimental_native_ranking():
            return "rust-forced"
        return f"adaptive (rust when candidates >= {NATIVE_RANKING_MIN_CANDIDATES})"

    def _upsert_engine_label(self) -> str:
        if native_accel is None:
            return "python"
        return "rust-assisted duplicate merge"

    def _row_to_record(
        self,
        row: sqlite3.Row,
        *,
        tags: tuple[str, ...] | None = None,
        score: float,
        excerpt: str,
    ) -> MemoryRecord:
        resolved_tags = tags if tags is not None else tuple(json.loads(row["tags_json"]))
        return MemoryRecord(
            id=row["id"],
            scope=row["scope"],
            kind=row["kind"],
            title=row["title"],
            summary=row["summary"],
            content=row["content"],
            tags=resolved_tags,
            source=row["source"],
            importance=float(row["importance"]),
            certainty=float(row["certainty"]),
            access_count=int(row["access_count"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            score=score,
            excerpt=excerpt,
        )

    def _row_to_export_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scope": row["scope"],
            "kind": row["kind"],
            "title": row["title"],
            "summary": row["summary"],
            "content": row["content"],
            "tags": list(json.loads(row["tags_json"])),
            "source": row["source"],
            "importance": float(row["importance"]),
            "certainty": float(row["certainty"]),
            "access_count": int(row["access_count"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_accessed_at": row["last_accessed_at"],
        }

    def _normalize_import_record(self, payload: dict[str, Any]) -> ImportedMemoryRecord:
        now = utc_now_iso()
        validated = self._validate_input(
            MemoryInput(
                scope=str(payload.get("scope", "")),
                kind=str(payload.get("kind", "")),
                title=str(payload.get("title", "")),
                content=str(payload.get("content", "")),
                summary=str(payload.get("summary", "")),
                tags=tuple(payload.get("tags") or ()),
                source=str(payload.get("source", "")),
                importance=float(payload.get("importance", 0.5)),
                certainty=float(payload.get("certainty", 0.7)),
            )
        )
        created_at = self._coerce_import_timestamp(payload.get("created_at"), field_name="created_at", fallback=now)
        updated_at = self._coerce_import_timestamp(payload.get("updated_at"), field_name="updated_at", fallback=created_at)
        last_accessed_at = self._coerce_import_timestamp(
            payload.get("last_accessed_at"),
            field_name="last_accessed_at",
            fallback=None,
        )
        access_count = max(int(payload.get("access_count", 0)), 0)
        record_id = normalize_space(str(payload.get("id", ""))) or uuid.uuid4().hex

        return ImportedMemoryRecord(
            id=record_id,
            scope=validated.scope,
            kind=validated.kind,
            title=validated.title,
            summary=validated.summary,
            content=validated.content,
            tags=tuple(validated.tags),
            source=validated.source,
            importance=validated.importance,
            certainty=validated.certainty,
            access_count=access_count,
            created_at=created_at,
            updated_at=updated_at,
            last_accessed_at=last_accessed_at,
        )

    def _coerce_import_timestamp(
        self,
        value: Any,
        *,
        field_name: str,
        fallback: str | None,
    ) -> str | None:
        if value in (None, ""):
            return fallback
        cleaned = normalize_space(str(value))
        if parse_timestamp(cleaned) is None:
            raise ValueError(f"{field_name} must be a valid ISO-8601 timestamp")
        return cleaned

    def _import_memory_record(
        self,
        connection: sqlite3.Connection,
        record: ImportedMemoryRecord,
    ) -> RememberResult:
        existing = connection.execute(
            """
            SELECT id
            FROM memories
            WHERE id = ?
            """,
            (record.id,),
        ).fetchone()
        action = "updated" if existing is not None else "created"
        fingerprint = compute_fingerprint(record.scope, record.kind, record.title, record.content)
        connection.execute(
            """
            INSERT INTO memories (
                id, scope, kind, title, summary, content,
                tags_json, tags_text, source, importance, certainty,
                fingerprint, access_count, created_at, updated_at, last_accessed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                scope = excluded.scope,
                kind = excluded.kind,
                title = excluded.title,
                summary = excluded.summary,
                content = excluded.content,
                tags_json = excluded.tags_json,
                tags_text = excluded.tags_text,
                source = excluded.source,
                importance = excluded.importance,
                certainty = excluded.certainty,
                fingerprint = excluded.fingerprint,
                access_count = excluded.access_count,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                last_accessed_at = excluded.last_accessed_at
            """,
            (
                record.id,
                record.scope,
                record.kind,
                record.title,
                record.summary,
                record.content,
                json.dumps(record.tags, ensure_ascii=False),
                " ".join(record.tags),
                record.source,
                record.importance,
                record.certainty,
                fingerprint,
                record.access_count,
                record.created_at,
                record.updated_at,
                record.last_accessed_at,
            ),
        )
        return RememberResult(
            id=record.id,
            scope=record.scope,
            kind=record.kind,
            title=record.title,
            action=action,
        )

    def _remember_validated(
        self,
        connection: sqlite3.Connection,
        record: MemoryInput,
    ) -> RememberResult:
        memory_id = uuid.uuid4().hex
        fingerprint = compute_fingerprint(record.scope, record.kind, record.title, record.content)
        existing = self._find_existing_memory(connection, record, fingerprint)
        now = utc_now_iso()

        if existing is not None:
            return self._merge_existing_memory(
                connection,
                existing=existing,
                record=record,
                fingerprint=fingerprint,
                now=now,
            )

        tags_json = json.dumps(record.tags, ensure_ascii=False)
        tags_text = " ".join(record.tags)
        connection.execute(
            """
            INSERT INTO memories (
                id, scope, kind, title, summary, content,
                tags_json, tags_text, source, importance, certainty,
                fingerprint, created_at, updated_at, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                record.scope,
                record.kind,
                record.title,
                record.summary,
                record.content,
                tags_json,
                tags_text,
                record.source,
                record.importance,
                record.certainty,
                fingerprint,
                now,
                now,
                None,
            ),
        )
        return RememberResult(
            id=memory_id,
            scope=record.scope,
            kind=record.kind,
            title=record.title,
            action="created",
        )

    def _find_existing_memory(
        self,
        connection: sqlite3.Connection,
        record: MemoryInput,
        fingerprint: str,
    ) -> sqlite3.Row | None:
        row = connection.execute(
            "SELECT * FROM memories WHERE fingerprint = ? LIMIT 1",
            (fingerprint,),
        ).fetchone()
        if row is not None:
            return row

        candidates = connection.execute(
            """
            SELECT *
            FROM memories
            WHERE scope = ? AND kind = ? AND title = ?
            ORDER BY updated_at DESC
            LIMIT 6
            """,
            (record.scope, record.kind, record.title),
        ).fetchall()

        if native_accel is not None and candidates:
            matched_index = native_accel.find_duplicate_candidate(
                [(index, candidate["content"]) for index, candidate in enumerate(candidates)],
                record.content,
                0.72,
            )
            if matched_index is not None:
                return candidates[matched_index]

        for candidate in candidates:
            if duplicate_match_score(candidate["content"], record.content) >= 0.72:
                return candidate
        return None

    def _merge_existing_memory(
        self,
        connection: sqlite3.Connection,
        *,
        existing: sqlite3.Row,
        record: MemoryInput,
        fingerprint: str,
        now: str,
    ) -> RememberResult:
        existing_tags = tuple(json.loads(existing["tags_json"]))
        if native_accel is not None:
            (
                merged_title,
                merged_content,
                merged_summary,
                merged_tags_raw,
                merged_source,
                merged_importance,
                merged_certainty,
            ) = native_accel.merge_memory_fields(
                existing["title"],
                existing["content"],
                existing["source"],
                list(existing_tags),
                float(existing["importance"]),
                float(existing["certainty"]),
                record.title,
                record.content,
                record.source,
                list(record.tags),
                record.importance,
                record.certainty,
                72,
                240,
            )
            merged_tags = tuple(merged_tags_raw)
        else:
            merged_tags = normalize_tags([*existing_tags, *record.tags])
            merged_title = choose_richer_text(existing["title"], record.title, max_chars=72)
            merged_content = choose_richer_text(existing["content"], record.content)
            merged_summary = derive_summary(merged_content)
            merged_source = merge_sources(existing["source"], record.source)
            merged_importance = max(float(existing["importance"]), record.importance)
            merged_certainty = min(1.0, max(float(existing["certainty"]), record.certainty) + 0.02)
        merged_fingerprint = compute_fingerprint(
            existing["scope"],
            existing["kind"],
            merged_title,
            merged_content,
        )

        connection.execute(
            """
            UPDATE memories
            SET title = ?,
                summary = ?,
                content = ?,
                tags_json = ?,
                tags_text = ?,
                source = ?,
                importance = ?,
                certainty = ?,
                fingerprint = ?,
                updated_at = ?
            WHERE rowid = ?
            """,
            (
                merged_title,
                merged_summary,
                merged_content,
                json.dumps(merged_tags, ensure_ascii=False),
                " ".join(merged_tags),
                merged_source,
                merged_importance,
                merged_certainty,
                merged_fingerprint or fingerprint,
                now,
                existing["rowid"],
            ),
        )

        return RememberResult(
            id=existing["id"],
            scope=existing["scope"],
            kind=existing["kind"],
            title=merged_title,
            action="updated",
        )

    def _table_columns(self, connection: sqlite3.Connection, table_name: str) -> set[str]:
        return {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        columns = self._table_columns(connection, "memories")
        if "fingerprint" not in columns:
            connection.execute(
                "ALTER TABLE memories ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''"
            )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_fingerprint ON memories(fingerprint)"
        )

        missing = connection.execute(
            """
            SELECT rowid, scope, kind, title, content
            FROM memories
            WHERE fingerprint = '' OR fingerprint IS NULL
            """
        ).fetchall()
        if not missing:
            return

        connection.executemany(
            "UPDATE memories SET fingerprint = ? WHERE rowid = ?",
            [
                (
                    compute_fingerprint(
                        row["scope"],
                        row["kind"],
                        row["title"],
                        row["content"],
                    ),
                    row["rowid"],
                )
                for row in missing
            ],
        )
