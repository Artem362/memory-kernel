from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

from .accelerator import (
    has_experimental_native_ranking,
    has_native_acceleration,
    light_stem_enabled,
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
APOSTROPHE_TRANSLATE = str.maketrans("", "", "'’‘ʼ")
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
CURRENT_SCHEMA_VERSION = 4
UKRAINIAN_SUFFIXES = (
    "ування", "аються", "ається", "юються", "ується",
    "ються", "ється",
    # soft-group feminine noun declensions (памʼять/памʼяті/памʼяттю/памʼятей);
    # kept before the shorter -ями/-ям/-ях/-ять so the longer form wins
    "ятями", "яттю", "ятей", "ятям", "ятях", "яті", "яте",
    "ення", "ання", "іння", "ивши", "авши", "уючи",
    "ила", "или", "ило", "ати", "яти", "ити", "іти", "ути",
    "ого", "ому", "ими", "ями",
    "ена", "ане", "ені", "ані", "ене",
    "ить", "ать", "ять", "ють", "уть", "ємо",
    "ою", "ів", "ам", "ом", "ах", "их", "ує",
)
UKRAINIAN_PREFIXES = (
    "пере",
    "роз", "при", "над", "під", "про", "від",
    "ви", "за", "на", "по", "до", "не", "об",
)
LIGHT_STEM_MIN_LEN = 3
DEEP_STEM_MIN_LEN = 3
CONTEXT_DEDUP_THRESHOLD = 0.72
RETENTION_HALF_LIFE_DAYS = 30.0
DECAYABLE_KINDS = ("note", "fact")
DEFAULT_DECAY_THRESHOLD = 0.35
DEFAULT_DECAY_MIN_AGE_DAYS = 30
DEFAULT_DECAY_MAX_ACCESS = 1
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
        "прийнято рішення",
        "ухвалено рішення",
        "рішення",
        "ухвалили",
        "вирішено",
        "ухвалено",
    ),
    "constraint": (
        "must",
        "must stay",
        "cannot",
        "cant",
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
        "надає перевагу",
        "віддає перевагу",
        "надаю перевагу",
        "волію",
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
        r"^(?:we\s+decided\s+to|decided\s+to|decision:\s*|we\s+will\s+|switch\s+to\s+|adopt\s+|use\s+|вирішили\s+|обрали\s+|будемо\s+|переходимо\s+на\s+|замінюємо\s+|прийнято\s+рішення\s+|ухвалено\s+рішення\s+|вирішено\s+|ухвалили\s+)",
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
    archived_at: str | None = None
    superseded_by: str | None = None

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
    archived_at: str | None = None
    superseded_by: str | None = None


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
    lowered = lowered.translate(APOSTROPHE_TRANSLATE)
    lowered = NON_WORD_RE.sub(" ", lowered)
    return normalize_space(lowered)


def semantic_terms(text: str, *, limit: int | None = None) -> list[str]:
    if native_accel is not None:
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
    if native_accel is not None:
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
    if native_accel is not None:
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
    if native_accel is not None:
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
    if any(word in lowered for word in ("decided", "switch to", "replace", "вирішили", "обрали", "рішення", "ухвалили")):
        scores["decision"] += 1

    best_kind = max(scores, key=scores.get)
    if scores[best_kind] <= 0:
        return "fact" if any(hint in lowered for hint in KIND_HINTS["fact"]) else "note"
    return best_kind


def infer_importance(text: str, kind: str) -> float:
    if native_accel is not None:
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
    if native_accel is not None:
        return float(native_accel.infer_certainty(text, kind))
    score = BASE_CERTAINTY.get(kind, 0.7)
    lowered = canonicalize_text(text)

    if any(word in lowered for word in HEDGE_WORDS):
        score -= 0.18
    if any(word in lowered for word in STRONG_SIGNAL_WORDS):
        score += 0.06

    return round(min(max(score, 0.2), 0.99), 2)


def derive_candidate_tags(text: str, *, base_tags: Sequence[str] = (), limit: int = 6) -> tuple[str, ...]:
    if native_accel is not None:
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
    if native_accel is not None:
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


def light_stem(term: str, *, min_stem_len: int = LIGHT_STEM_MIN_LEN) -> str:
    if native_accel is not None and min_stem_len == LIGHT_STEM_MIN_LEN:
        return native_accel.light_stem(term)
    if len(term) <= min_stem_len:
        return term
    for suffix in UKRAINIAN_SUFFIXES:
        if term.endswith(suffix) and len(term) - len(suffix) >= min_stem_len:
            return term[: -len(suffix)]
    return term


def strip_ukrainian_prefix(
    term: str,
    *,
    min_stem_len: int = DEEP_STEM_MIN_LEN,
    max_iterations: int = 2,
) -> str:
    current = term
    for _ in range(max_iterations):
        if len(current) <= min_stem_len:
            break
        stripped = None
        for prefix in UKRAINIAN_PREFIXES:
            if current.startswith(prefix) and len(current) - len(prefix) >= min_stem_len:
                stripped = current[len(prefix):]
                break
        if stripped is None or stripped == current:
            break
        current = stripped
    return current


def deep_stem(term: str) -> str:
    if native_accel is not None:
        return native_accel.deep_stem(term)
    return strip_ukrainian_prefix(light_stem(term))


def retention_score(
    *,
    importance: float,
    access_count: int,
    last_seen: str | None,
    now: datetime | None = None,
) -> float:
    """Estimate how strongly a memory should be retained (0.0 - 1.0).

    Models a simple forgetting curve: base importance, reinforced by how often
    the memory has been recalled, decayed by how long since it was last seen.
    Frequently-recalled or important memories stay strong; old, untouched,
    low-importance ones fade.
    """
    now = now or datetime.now(timezone.utc)
    reinforcement = min(max(access_count, 0), 10) / 10.0
    parsed = parse_timestamp(last_seen)
    if parsed is None:
        freshness = 0.0
    else:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_days = max((now - parsed).total_seconds() / 86400.0, 0.0)
        freshness = 0.5 ** (age_days / RETENTION_HALF_LIFE_DAYS)
    score = 0.5 * importance + 0.2 * reinforcement + 0.3 * freshness
    return round(min(max(score, 0.0), 1.0), 4)


def compute_stems_text(title: str, content: str, tags: Sequence[str]) -> str:
    if native_accel is not None:
        return native_accel.compute_stems_text(title, content, list(tags))
    parts = [title, content]
    if tags:
        parts.append(" ".join(tags))
    combined = " ".join(parts)
    seen: set[str] = set()
    stems: list[str] = []
    for term in semantic_terms(combined):
        stem = deep_stem(term)
        if stem and stem not in seen:
            seen.add(stem)
            stems.append(stem)
    return " ".join(stems)


def build_fts_query(query: str) -> str:
    terms = extract_terms(query)
    if not light_stem_enabled():
        return " OR ".join(f"{term}*" for term in terms)
    parts: list[str] = []
    seen_stems: set[str] = set()
    for term in terms:
        light = light_stem(term)
        parts.append(f"{light}*")
        deep = deep_stem(term)
        if deep and deep != light and deep not in seen_stems:
            seen_stems.add(deep)
            parts.append(f"stems_text:{deep}")
    return " OR ".join(parts)


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
            connection.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            existing_version = self._get_schema_version(connection)
            if existing_version == 0 and self._memories_table_exists(connection):
                existing_version = 1
            if existing_version == 0:
                self._create_fresh_schema(connection)
            elif existing_version < CURRENT_SCHEMA_VERSION:
                self._apply_migrations(connection, existing_version)
        self._initialized = True

    def _memories_table_exists(self, connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchone()
        return row is not None

    def _create_fresh_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(self._memories_schema_sql())
        connection.executescript(self._fts_schema_sql())
        self._set_schema_version(connection, CURRENT_SCHEMA_VERSION)

    def _apply_migrations(
        self, connection: sqlite3.Connection, current_version: int
    ) -> None:
        steps: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
            (2, self._migrate_v1_to_v2),
            (3, self._migrate_v2_to_v3),
            (4, self._migrate_v3_to_v4),
        ]
        for target_version, migrate in steps:
            if current_version < target_version:
                migrate(connection)
                self._set_schema_version(connection, target_version)
                current_version = target_version

    def _set_schema_version(self, connection: sqlite3.Connection, version: int) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )

    def _migrate_v1_to_v2(self, connection: sqlite3.Connection) -> None:
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
                        row["scope"], row["kind"], row["title"], row["content"]
                    ),
                    row["rowid"],
                )
                for row in missing
            ],
        )

    def _migrate_v2_to_v3(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            DROP TRIGGER IF EXISTS memories_ai;
            DROP TRIGGER IF EXISTS memories_ad;
            DROP TRIGGER IF EXISTS memories_au;
            DROP TABLE IF EXISTS memory_fts;
            """
        )
        columns = self._table_columns(connection, "memories")
        if "stems_text" not in columns:
            connection.execute(
                "ALTER TABLE memories ADD COLUMN stems_text TEXT NOT NULL DEFAULT ''"
            )
        self._backfill_stems_text(connection)
        connection.executescript(self._fts_schema_sql())
        connection.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")

    def _migrate_v3_to_v4(self, connection: sqlite3.Connection) -> None:
        columns = self._table_columns(connection, "memories")
        if "archived_at" not in columns:
            connection.execute("ALTER TABLE memories ADD COLUMN archived_at TEXT")
        if "superseded_by" not in columns:
            connection.execute("ALTER TABLE memories ADD COLUMN superseded_by TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_active "
            "ON memories(archived_at, superseded_by)"
        )

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

    def preview_ingest(
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
        segments = split_memory_candidates(text, max_items=max_items)
        items: list[dict[str, Any]] = []
        for segment in segments:
            item_kind = kind or infer_kind(segment)
            derived_title = derive_title(segment, item_kind)
            derived_summary = derive_summary(segment)
            derived_tags = derive_candidate_tags(segment, base_tags=tags)
            derived_importance = (
                importance if importance is not None else infer_importance(segment, item_kind)
            )
            derived_certainty = (
                certainty if certainty is not None else infer_certainty(segment, item_kind)
            )
            items.append(
                {
                    "kind": item_kind,
                    "title": derived_title,
                    "summary": derived_summary,
                    "content": segment,
                    "tags": list(derived_tags),
                    "importance": derived_importance,
                    "certainty": derived_certainty,
                }
            )
        return {
            "scope": scope,
            "source": source,
            "segments": len(segments),
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
        dedup_threshold: float = CONTEXT_DEDUP_THRESHOLD,
    ) -> dict[str, Any]:
        results = self.search(
            query,
            limit=max(limit * 4, limit),
            scope=scope,
            kind=kind,
            tags=tags,
        )
        header = f"Context pack for: {query}"
        if not results and query.strip():
            # no lexical match — fall back to hot memories (same as wake-up)
            # so a broad query like "наш проєкт" still yields useful context
            results = self.search("", limit=max(limit * 4, limit), scope=scope, kind=kind, tags=tags)
            header = f"Context pack for: {query} (no direct match; showing hot memories)"
        return self._render_pack(
            results=results,
            budget_chars=budget_chars,
            limit=limit,
            header=header,
            dedup_threshold=dedup_threshold,
        )

    def build_wake_up_pack(
        self,
        *,
        budget_chars: int = 800,
        limit: int = 6,
        scope: str | None = None,
        dedup_threshold: float = CONTEXT_DEDUP_THRESHOLD,
    ) -> dict[str, Any]:
        results = self.search("", limit=max(limit * 4, limit), scope=scope)
        return self._render_pack(
            results=results,
            budget_chars=budget_chars,
            limit=limit,
            header="Wake-up pack",
            dedup_threshold=dedup_threshold,
        )

    def verify(self, *, repair: bool = False) -> dict[str, Any]:
        self.init()
        with self._connect() as connection:
            initial = self._collect_verification(connection)
            repaired_stems = 0
            repaired_fingerprints = 0
            rebuilt_fts = False
            if repair and not initial["healthy"]:
                rows = connection.execute(
                    "SELECT rowid, id, scope, kind, title, content, tags_json FROM memories"
                ).fetchall()
                stems_updates: list[tuple[str, int]] = []
                fingerprint_updates: list[tuple[str, int]] = []
                bad_stems = set(initial["stems_text_mismatches"])
                bad_fps = set(initial["fingerprint_mismatches"])
                for row in rows:
                    if row["id"] in bad_stems:
                        tags = tuple(json.loads(row["tags_json"] or "[]"))
                        stems_updates.append(
                            (
                                compute_stems_text(row["title"], row["content"], tags),
                                row["rowid"],
                            )
                        )
                    if row["id"] in bad_fps:
                        fingerprint_updates.append(
                            (
                                compute_fingerprint(
                                    row["scope"], row["kind"], row["title"], row["content"]
                                ),
                                row["rowid"],
                            )
                        )
                if stems_updates:
                    connection.executemany(
                        "UPDATE memories SET stems_text = ? WHERE rowid = ?",
                        stems_updates,
                    )
                    repaired_stems = len(stems_updates)
                if fingerprint_updates:
                    connection.executemany(
                        "UPDATE memories SET fingerprint = ? WHERE rowid = ?",
                        fingerprint_updates,
                    )
                    repaired_fingerprints = len(fingerprint_updates)
                if initial["fts_count_mismatch"] is not None:
                    connection.execute(
                        "INSERT INTO memory_fts(memory_fts) VALUES('rebuild')"
                    )
                    rebuilt_fts = True
                report = self._collect_verification(connection)
            else:
                report = initial

        if repair:
            report["repaired_stems"] = repaired_stems
            report["repaired_fingerprints"] = repaired_fingerprints
            report["rebuilt_fts"] = rebuilt_fts
        return report

    def _collect_verification(self, connection: sqlite3.Connection) -> dict[str, Any]:
        version = self._get_schema_version(connection)
        schema_issue = (
            None
            if version == CURRENT_SCHEMA_VERSION
            else f"expected schema_version {CURRENT_SCHEMA_VERSION}, got {version}"
        )

        rows = connection.execute(
            """
            SELECT rowid, id, scope, kind, title, content,
                   tags_json, stems_text, fingerprint
            FROM memories
            """
        ).fetchall()

        stems_mismatches: list[str] = []
        fingerprint_mismatches: list[str] = []
        for row in rows:
            tags = tuple(json.loads(row["tags_json"] or "[]"))
            expected_stems = compute_stems_text(row["title"], row["content"], tags)
            if expected_stems != row["stems_text"]:
                stems_mismatches.append(row["id"])
            expected_fp = compute_fingerprint(
                row["scope"], row["kind"], row["title"], row["content"]
            )
            if expected_fp != row["fingerprint"]:
                fingerprint_mismatches.append(row["id"])

        memories_count = len(rows)
        fts_count = connection.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
        fts_mismatch = (
            {"memories": memories_count, "fts": fts_count}
            if memories_count != fts_count
            else None
        )

        healthy = (
            schema_issue is None
            and not stems_mismatches
            and not fingerprint_mismatches
            and fts_mismatch is None
        )
        return {
            "checked_memories": memories_count,
            "schema_issue": schema_issue,
            "stems_text_mismatches": stems_mismatches,
            "fingerprint_mismatches": fingerprint_mismatches,
            "fts_count_mismatch": fts_mismatch,
            "healthy": healthy,
        }

    def stats(self, *, since: datetime | None = None) -> dict[str, Any]:
        self.init()
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            archived = connection.execute(
                "SELECT COUNT(*) FROM memories "
                "WHERE archived_at IS NOT NULL OR superseded_by IS NOT NULL"
            ).fetchone()[0]
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
            payload: dict[str, Any] = {
                "database": str(self.db_path),
                "accelerator": "rust" if has_native_acceleration() else "python",
                "ranking_engine": self._ranking_engine_label(),
                "upsert_engine": self._upsert_engine_label(),
                "total_memories": total,
                "active_memories": total - archived,
                "archived_memories": archived,
                "by_kind": by_kind,
                "top_scopes": by_scope,
            }
            if since is not None:
                cutoff = since.isoformat()
                payload["since"] = cutoff
                payload["created_since"] = connection.execute(
                    "SELECT COUNT(*) FROM memories WHERE created_at >= ?",
                    (cutoff,),
                ).fetchone()[0]
                payload["updated_since"] = connection.execute(
                    "SELECT COUNT(*) FROM memories WHERE updated_at >= ?",
                    (cutoff,),
                ).fetchone()[0]
                payload["by_kind_since"] = {
                    row["kind"]: row["count"]
                    for row in connection.execute(
                        """
                        SELECT kind, COUNT(*) AS count
                        FROM memories
                        WHERE updated_at >= ?
                        GROUP BY kind
                        ORDER BY count DESC
                        """,
                        (cutoff,),
                    ).fetchall()
                }
        return payload

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        self.init()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row, score=0.0, excerpt="")

    def delete_memory(self, memory_id: str) -> bool:
        self.init()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE id = ?",
                (memory_id,),
            )
        return cursor.rowcount > 0

    def archive_memory(self, memory_id: str) -> bool:
        """Soft-forget a memory: hide it from recall but keep it recoverable."""
        self.init()
        now = utc_now_iso()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memories
                SET archived_at = ?, updated_at = ?
                WHERE id = ? AND archived_at IS NULL
                """,
                (now, now, memory_id),
            )
            if cursor.rowcount == 0:
                exists = connection.execute(
                    "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
                ).fetchone()
                if exists is None:
                    return False
        return True

    def restore_memory(self, memory_id: str) -> bool:
        """Bring an archived memory back into recall."""
        self.init()
        now = utc_now_iso()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memories
                SET archived_at = NULL, updated_at = ?
                WHERE id = ? AND archived_at IS NOT NULL
                """,
                (now, memory_id),
            )
            if cursor.rowcount == 0:
                exists = connection.execute(
                    "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
                ).fetchone()
                if exists is None:
                    return False
        return True

    def revise_memory(self, new_id: str, superseded_id: str) -> MemoryRecord:
        """Mark ``superseded_id`` as replaced by ``new_id``.

        The superseded memory is hidden from recall (like an archive) but kept
        for history, with a pointer to the memory that replaced it.
        """
        self.init()
        if new_id == superseded_id:
            raise ValueError("a memory cannot supersede itself")
        now = utc_now_iso()
        with self._connect() as connection:
            new_row = connection.execute(
                "SELECT id FROM memories WHERE id = ?", (new_id,)
            ).fetchone()
            if new_row is None:
                raise KeyError(f"superseding memory not found: {new_id}")
            old_row = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (superseded_id,)
            ).fetchone()
            if old_row is None:
                raise KeyError(f"memory not found: {superseded_id}")
            connection.execute(
                """
                UPDATE memories
                SET superseded_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_id, now, superseded_id),
            )
            updated = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (superseded_id,)
            ).fetchone()
        return self._row_to_record(updated, score=0.0, excerpt="")

    def decay(
        self,
        *,
        dry_run: bool = True,
        min_age_days: int = DEFAULT_DECAY_MIN_AGE_DAYS,
        max_access: int = DEFAULT_DECAY_MAX_ACCESS,
        threshold: float = DEFAULT_DECAY_THRESHOLD,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Auto-archive weak, stale, rarely-recalled memories (forgetting curve).

        Only low-value kinds (note, fact) are eligible; decisions, constraints,
        tasks, and preferences are never decayed. A memory is archived only when
        it is old enough, barely accessed, and its retention score is below the
        threshold. Archiving is recoverable via ``restore_memory``.
        """
        self.init()
        now = datetime.now(timezone.utc)
        placeholders = ",".join("?" for _ in DECAYABLE_KINDS)
        params: list[Any] = list(DECAYABLE_KINDS)
        scope_sql = ""
        if scope:
            scope_sql = "AND scope = ?"
            params.append(scope)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, kind, scope, title, importance, access_count,
                       created_at, last_accessed_at
                FROM memories
                WHERE archived_at IS NULL AND superseded_by IS NULL
                  AND kind IN ({placeholders})
                  {scope_sql}
                """,
                params,
            ).fetchall()

            candidates: list[dict[str, Any]] = []
            for row in rows:
                last_seen = row["last_accessed_at"] or row["created_at"]
                parsed = parse_timestamp(last_seen)
                age_days = 0.0
                if parsed is not None:
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    age_days = max((now - parsed).total_seconds() / 86400.0, 0.0)
                if age_days < min_age_days:
                    continue
                if int(row["access_count"]) > max_access:
                    continue
                retention = retention_score(
                    importance=float(row["importance"]),
                    access_count=int(row["access_count"]),
                    last_seen=last_seen,
                    now=now,
                )
                if retention >= threshold:
                    continue
                candidates.append(
                    {
                        "id": row["id"],
                        "kind": row["kind"],
                        "scope": row["scope"],
                        "title": row["title"],
                        "retention": retention,
                        "age_days": round(age_days, 1),
                    }
                )

            archived = 0
            if not dry_run and candidates:
                now_iso = utc_now_iso()
                connection.executemany(
                    "UPDATE memories SET archived_at = ?, updated_at = ? WHERE id = ?",
                    [(now_iso, now_iso, item["id"]) for item in candidates],
                )
                archived = len(candidates)

        return {
            "dry_run": dry_run,
            "scanned": len(rows),
            "candidates": len(candidates),
            "archived": archived,
            "min_age_days": min_age_days,
            "max_access": max_access,
            "threshold": threshold,
            "items": candidates,
        }

    def update_memory(
        self,
        memory_id: str,
        *,
        scope: str | None = None,
        kind: str | None = None,
        title: str | None = None,
        content: str | None = None,
        summary: str | None = None,
        tags: Sequence[str] | None = None,
        source: str | None = None,
        importance: float | None = None,
        certainty: float | None = None,
    ) -> MemoryRecord:
        self.init()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(f"memory not found: {memory_id}")

            merged = MemoryInput(
                scope=scope if scope is not None else existing["scope"],
                kind=kind if kind is not None else existing["kind"],
                title=title if title is not None else existing["title"],
                content=content if content is not None else existing["content"],
                summary=summary if summary is not None else existing["summary"],
                tags=tuple(tags) if tags is not None else tuple(json.loads(existing["tags_json"])),
                source=source if source is not None else existing["source"],
                importance=importance if importance is not None else float(existing["importance"]),
                certainty=certainty if certainty is not None else float(existing["certainty"]),
            )
            validated = self._validate_input(merged)
            new_fingerprint = compute_fingerprint(
                validated.scope, validated.kind, validated.title, validated.content
            )
            new_stems_text = compute_stems_text(
                validated.title, validated.content, validated.tags
            )
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE memories
                SET scope = ?, kind = ?, title = ?, summary = ?, content = ?,
                    tags_json = ?, tags_text = ?, stems_text = ?, source = ?,
                    importance = ?, certainty = ?,
                    fingerprint = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    validated.scope,
                    validated.kind,
                    validated.title,
                    validated.summary,
                    validated.content,
                    json.dumps(validated.tags, ensure_ascii=False),
                    " ".join(validated.tags),
                    new_stems_text,
                    validated.source,
                    validated.importance,
                    validated.certainty,
                    new_fingerprint,
                    now,
                    memory_id,
                ),
            )
            updated_row = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_record(updated_row, score=0.0, excerpt="")

    def list_memories(
        self,
        *,
        scope: str | None = None,
        kind: str | None = None,
        tags: Sequence[str] = (),
        limit: int = 20,
        include_archived: bool = False,
    ) -> list[MemoryRecord]:
        self.init()
        normalized_tags = normalize_tags(tags)
        with self._connect() as connection:
            filter_sql, params = self._build_filters(
                scope=scope, kind=kind, tags=normalized_tags, include_archived=include_archived
            )
            rows = connection.execute(
                f"""
                SELECT m.*
                FROM memories AS m
                WHERE 1 = 1
                {filter_sql}
                ORDER BY m.updated_at DESC, m.created_at DESC, m.rowid DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [self._row_to_record(row, score=0.0, excerpt="") for row in rows]

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
                include_archived=True,
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

    def _memories_schema_sql(self) -> str:
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
                stems_text TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                importance REAL NOT NULL DEFAULT 0.5,
                certainty REAL NOT NULL DEFAULT 0.7,
                fingerprint TEXT NOT NULL DEFAULT '',
                access_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT,
                archived_at TEXT,
                superseded_by TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_memories_scope_kind
                ON memories(scope, kind);
            CREATE INDEX IF NOT EXISTS idx_memories_hot
                ON memories(importance DESC, certainty DESC, access_count DESC, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memories_fingerprint
                ON memories(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_memories_active
                ON memories(archived_at, superseded_by);
        """

    def _fts_schema_sql(self) -> str:
        return """
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                title,
                summary,
                content,
                tags_text,
                stems_text,
                content='memories',
                content_rowid='rowid',
                tokenize='unicode61 remove_diacritics 2'
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memory_fts(rowid, title, summary, content, tags_text, stems_text)
                VALUES (new.rowid, new.title, new.summary, new.content, new.tags_text, new.stems_text);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, title, summary, content, tags_text, stems_text)
                VALUES ('delete', old.rowid, old.title, old.summary, old.content, old.tags_text, old.stems_text);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, title, summary, content, tags_text, stems_text)
                VALUES ('delete', old.rowid, old.title, old.summary, old.content, old.tags_text, old.stems_text);
                INSERT INTO memory_fts(rowid, title, summary, content, tags_text, stems_text)
                VALUES (new.rowid, new.title, new.summary, new.content, new.tags_text, new.stems_text);
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
        include_archived: bool = False,
    ) -> list[sqlite3.Row]:
        filter_sql, params = self._build_filters(
            scope=scope, kind=kind, tags=tags, include_archived=include_archived
        )
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
        include_archived: bool = False,
    ) -> list[sqlite3.Row]:
        filter_sql, params = self._build_filters(
            scope=scope, kind=kind, tags=tags, include_archived=include_archived
        )
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
        include_archived: bool = False,
    ) -> list[sqlite3.Row]:
        filter_sql, params = self._build_filters(
            scope=scope, kind=kind, tags=tags, include_archived=include_archived
        )
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
        include_archived: bool = False,
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
        if not include_archived:
            filters.append("AND m.archived_at IS NULL AND m.superseded_by IS NULL")

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
        dedup_threshold: float = CONTEXT_DEDUP_THRESHOLD,
    ) -> dict[str, Any]:
        lines: list[str] = [header]
        items: list[dict[str, Any]] = []
        kept_contents: list[str] = []

        for result in results:
            if len(items) >= limit:
                break

            # drop near-duplicates so each pack entry carries distinct signal
            if dedup_threshold < 1.0 and any(
                token_overlap_score(result.content, kept) >= dedup_threshold
                for kept in kept_contents
            ):
                continue

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
            kept_contents.append(result.content)

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
        keys = row.keys()
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
            archived_at=row["archived_at"] if "archived_at" in keys else None,
            superseded_by=row["superseded_by"] if "superseded_by" in keys else None,
        )

    def _row_to_export_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        keys = row.keys()
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
            "archived_at": row["archived_at"] if "archived_at" in keys else None,
            "superseded_by": row["superseded_by"] if "superseded_by" in keys else None,
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
        archived_at = self._coerce_import_timestamp(
            payload.get("archived_at"), field_name="archived_at", fallback=None
        )
        superseded_raw = payload.get("superseded_by")
        superseded_by = normalize_space(str(superseded_raw)) if superseded_raw else None

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
            archived_at=archived_at,
            superseded_by=superseded_by,
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
        stems_text = compute_stems_text(record.title, record.content, record.tags)
        connection.execute(
            """
            INSERT INTO memories (
                id, scope, kind, title, summary, content,
                tags_json, tags_text, stems_text, source, importance, certainty,
                fingerprint, access_count, created_at, updated_at, last_accessed_at,
                archived_at, superseded_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                scope = excluded.scope,
                kind = excluded.kind,
                title = excluded.title,
                summary = excluded.summary,
                content = excluded.content,
                tags_json = excluded.tags_json,
                tags_text = excluded.tags_text,
                stems_text = excluded.stems_text,
                source = excluded.source,
                importance = excluded.importance,
                certainty = excluded.certainty,
                fingerprint = excluded.fingerprint,
                access_count = excluded.access_count,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                last_accessed_at = excluded.last_accessed_at,
                archived_at = excluded.archived_at,
                superseded_by = excluded.superseded_by
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
                stems_text,
                record.source,
                record.importance,
                record.certainty,
                fingerprint,
                record.access_count,
                record.created_at,
                record.updated_at,
                record.last_accessed_at,
                record.archived_at,
                record.superseded_by,
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
        stems_text = compute_stems_text(record.title, record.content, record.tags)
        connection.execute(
            """
            INSERT INTO memories (
                id, scope, kind, title, summary, content,
                tags_json, tags_text, stems_text, source, importance, certainty,
                fingerprint, created_at, updated_at, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                stems_text,
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

        merged_stems_text = compute_stems_text(merged_title, merged_content, merged_tags)
        connection.execute(
            """
            UPDATE memories
            SET title = ?,
                summary = ?,
                content = ?,
                tags_json = ?,
                tags_text = ?,
                stems_text = ?,
                source = ?,
                importance = ?,
                certainty = ?,
                fingerprint = ?,
                updated_at = ?,
                archived_at = NULL
            WHERE rowid = ?
            """,
            (
                merged_title,
                merged_summary,
                merged_content,
                json.dumps(merged_tags, ensure_ascii=False),
                " ".join(merged_tags),
                merged_stems_text,
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

    def _get_schema_version(self, connection: sqlite3.Connection) -> int:
        try:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        if row is None:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def _backfill_stems_text(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT rowid, title, content, tags_json FROM memories"
        ).fetchall()
        if not rows:
            return
        updates = []
        for row in rows:
            tags = tuple(json.loads(row["tags_json"] or "[]"))
            stems = compute_stems_text(row["title"], row["content"], tags)
            updates.append((stems, row["rowid"]))
        connection.executemany(
            "UPDATE memories SET stems_text = ? WHERE rowid = ?",
            updates,
        )
