use chrono::{DateTime, Utc};
use pyo3::prelude::*;
use pyo3::types::PyModule;
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::HashSet;

const STOP_WORDS: &[&str] = &[
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from", "how", "if", "in",
    "into", "is", "it", "of", "on", "or", "that", "the", "this", "to", "we", "what", "when",
    "where", "why", "with",
    "але", "без", "було", "бути", "в", "ви", "вже", "він", "вона", "воно", "для", "до", "є",
    "за", "з", "і", "й", "її", "їх", "коли", "ми", "на", "не", "ні", "про", "та", "те", "ти",
    "то", "у", "це", "цей", "ця", "що", "як",
];

const KIND_HINTS_DECISION: &[&str] = &[
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
];

const KIND_HINTS_CONSTRAINT: &[&str] = &[
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
];

const KIND_HINTS_TASK: &[&str] = &[
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
];

const KIND_HINTS_PREFERENCE: &[&str] = &[
    "prefer",
    "would rather",
    "want",
    "avoid",
    "ideally",
    "краще",
    "хочемо",
    "уникаємо",
    "бажано",
];

const KIND_HINTS_FACT: &[&str] = &[
    "currently",
    "today",
    "uses",
    "contains",
    "runs on",
    "станом",
    "використовує",
    "містить",
    "працює на",
];

const STRONG_SIGNAL_WORDS: &[&str] = &[
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
];

const UKRAINIAN_SUFFIXES: &[&str] = &[
    "ування", "аються", "ається", "юються", "ується",
    "ються", "ється",
    "ення", "ання", "іння", "ивши", "авши", "уючи",
    "ила", "или", "ило", "ати", "яти", "ити", "іти", "ути",
    "ого", "ому", "ими", "ями",
    "ена", "ане", "ені", "ані", "ене",
    "ить", "ать", "ять", "ють", "уть", "ємо",
    "ою", "ів", "ам", "ом", "ах", "их", "ує",
];

const UKRAINIAN_PREFIXES: &[&str] = &[
    "пере",
    "роз", "при", "над", "під", "про", "від",
    "ви", "за", "на", "по", "до", "не", "об",
];

const LIGHT_STEM_MIN_LEN: usize = 3;
const DEEP_STEM_MIN_LEN: usize = 3;
const DEEP_STEM_MAX_ITERATIONS: usize = 2;

const HEDGE_WORDS: &[&str] = &[
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
];

const DECISION_PREFIXES: &[&str] = &[
    "we decided to",
    "decided to",
    "decision:",
    "we will",
    "switch to",
    "adopt",
    "use",
    "вирішили",
    "обрали",
    "будемо",
    "переходимо на",
    "замінюємо",
];

const CONSTRAINT_PREFIXES: &[&str] = &[
    "must",
    "must stay",
    "cannot",
    "never",
    "should",
    "обовязково",
    "повинно",
    "має",
    "не можна",
];
const TASK_PREFIXES: &[&str] = &[
    "todo:",
    "todo",
    "need to",
    "implement",
    "fix",
    "add",
    "зробити",
    "треба",
    "потрібно",
    "додати",
    "виправити",
    "реалізувати",
];
const PREFERENCE_PREFIXES: &[&str] = &[
    "prefer",
    "want",
    "avoid",
    "краще",
    "хочемо",
    "уникаємо",
    "бажано",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RankCandidate {
    id: String,
    scope: String,
    kind: String,
    title: String,
    summary: String,
    content: String,
    tags: Vec<String>,
    source: String,
    importance: f64,
    certainty: f64,
    access_count: i64,
    created_at: String,
    updated_at: String,
    last_accessed_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RankedCandidate {
    id: String,
    scope: String,
    kind: String,
    title: String,
    summary: String,
    content: String,
    tags: Vec<String>,
    source: String,
    importance: f64,
    certainty: f64,
    access_count: i64,
    created_at: String,
    updated_at: String,
    last_accessed_at: Option<String>,
    score: f64,
    excerpt: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PackItem {
    id: String,
    kind: String,
    scope: String,
    title: String,
    excerpt: String,
    score: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PackOutput {
    budget_chars: usize,
    used_chars: usize,
    items: Vec<PackItem>,
    rendered: String,
}

fn normalize_space(value: &str) -> String {
    let cleaned = value.replace('\u{feff}', " ").replace('\u{200b}', " ");
    cleaned.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn canonicalize_text(value: &str) -> String {
    let lowered = value
        .chars()
        .flat_map(|ch| ch.to_lowercase())
        .filter(|ch| !matches!(ch, '\'' | '\u{2019}' | '\u{2018}' | '\u{02bc}'))
        .map(|ch| {
            if ch.is_alphanumeric() || ch == '_' || ch == '-' || ch.is_whitespace() {
                ch
            } else {
                ' '
            }
        })
        .collect::<String>();
    normalize_space(&lowered)
}

fn take_chars(value: &str, max_chars: usize) -> String {
    value.chars().take(max_chars).collect()
}

fn truncate_with_ellipsis(value: &str, max_chars: usize) -> String {
    let count = value.chars().count();
    if count <= max_chars {
        return value.to_string();
    }
    if max_chars <= 3 {
        return ".".repeat(max_chars);
    }
    let mut truncated = take_chars(value, max_chars - 3);
    truncated = truncated.trim_end().to_string();
    truncated.push_str("...");
    truncated
}

fn contains_word(haystack: &str, words: &[&str]) -> bool {
    words.iter().any(|word| haystack.contains(word))
}

fn actionability_bonus(kind: &str) -> f64 {
    match kind {
        "decision" => 0.22,
        "constraint" => 0.20,
        "task" => 0.17,
        "preference" => 0.14,
        "fact" => 0.11,
        _ => 0.06,
    }
}

fn count_chars(value: &str) -> usize {
    value.chars().count()
}

fn text_information_score_internal(text: &str) -> usize {
    let cleaned = normalize_space(text);
    let unique_terms = semantic_terms_internal(&cleaned, None)
        .into_iter()
        .collect::<HashSet<_>>()
        .len();
    count_chars(&cleaned) + unique_terms * 12
}

fn truncate_word_boundary(value: &str, max_chars: usize) -> String {
    if count_chars(value) <= max_chars {
        return value.to_string();
    }

    let taken = take_chars(value, max_chars);
    if let Some(pos) = taken.rfind(' ') {
        let candidate = taken[..pos].trim_end();
        if !candidate.is_empty() {
            return candidate.to_string();
        }
    }
    taken
}

fn choose_richer_text_internal(existing: &str, candidate: &str, max_chars: Option<usize>) -> String {
    let existing_clean = normalize_space(existing);
    let candidate_clean = normalize_space(candidate);
    let existing_score = text_information_score_internal(&existing_clean);
    let candidate_score = text_information_score_internal(&candidate_clean);

    let mut best = if existing_score >= candidate_score {
        existing_clean
    } else {
        candidate_clean
    };

    if let Some(max_chars) = max_chars {
        if count_chars(&best) > max_chars {
            best = truncate_word_boundary(&best, max_chars);
        }
    }

    best
}

fn merge_sources_internal(existing: &str, candidate: &str, max_chars: usize) -> String {
    let mut values: Vec<String> = Vec::new();

    for raw in [existing, candidate] {
        let cleaned = normalize_space(raw);
        if cleaned.is_empty() {
            continue;
        }
        for item in cleaned.split("; ") {
            let part = normalize_space(item);
            if !part.is_empty() && !values.iter().any(|value| value == &part) {
                values.push(part);
            }
        }
    }

    let merged = values.join("; ");
    if count_chars(&merged) <= max_chars {
        merged
    } else {
        truncate_with_ellipsis(&merged, max_chars)
    }
}

fn normalize_tags_internal(tags: &[String]) -> Vec<String> {
    let mut cleaned: Vec<String> = Vec::new();
    for tag in tags {
        let normalized = normalize_space(tag).to_lowercase();
        if !normalized.is_empty() && !cleaned.iter().any(|item| item == &normalized) {
            cleaned.push(normalized);
        }
    }
    cleaned
}

fn semantic_terms_internal(text: &str, limit: Option<usize>) -> Vec<String> {
    let mut seen: Vec<String> = Vec::new();
    for token in canonicalize_text(text).split_whitespace() {
        if token.chars().count() < 3 {
            continue;
        }
        if STOP_WORDS.contains(&token) {
            continue;
        }
        if seen.iter().any(|item| item == token) {
            continue;
        }
        seen.push(token.to_string());
        if let Some(limit) = limit {
            if seen.len() >= limit {
                break;
            }
        }
    }
    seen
}

fn extract_terms_internal(query: &str) -> Vec<String> {
    let mut seen: Vec<String> = Vec::new();
    for token in canonicalize_text(query).split_whitespace() {
        if token.chars().count() < 2 {
            continue;
        }
        if STOP_WORDS.contains(&token) {
            continue;
        }
        if seen.iter().any(|item| item == token) {
            continue;
        }
        seen.push(token.to_string());
        if seen.len() >= 8 {
            break;
        }
    }
    seen
}

fn strip_prefix_ci<'a>(value: &'a str, prefixes: &[&str]) -> &'a str {
    let lowered = value.to_lowercase();
    for prefix in prefixes {
        if lowered.starts_with(prefix) {
            return value[prefix.len()..].trim_start();
        }
    }
    value
}

fn infer_kind_internal(text: &str) -> &'static str {
    let lowered = canonicalize_text(text);
    let mut scores = [0_i32; 6];

    for hint in KIND_HINTS_DECISION {
        if lowered.contains(hint) {
            scores[0] += 2;
        }
    }
    for hint in KIND_HINTS_CONSTRAINT {
        if lowered.contains(hint) {
            scores[1] += 2;
        }
    }
    for hint in KIND_HINTS_PREFERENCE {
        if lowered.contains(hint) {
            scores[2] += 2;
        }
    }
    for hint in KIND_HINTS_TASK {
        if lowered.contains(hint) {
            scores[3] += 2;
        }
    }
    for hint in KIND_HINTS_FACT {
        if lowered.contains(hint) {
            scores[4] += 2;
        }
    }

    if lowered.starts_with("todo") || lowered.starts_with("next step") {
        scores[3] += 4;
    }
    if lowered.starts_with("note") {
        scores[5] += 2;
    }
    if contains_word(&lowered, &["must", "never", "cannot", "повинно", "не можна"]) {
        scores[1] += 1;
    }
    if contains_word(&lowered, &["decided", "switch to", "replace", "вирішили", "обрали"]) {
        scores[0] += 1;
    }

    let kinds = ["decision", "constraint", "preference", "task", "fact", "note"];
    let (index, best) = scores
        .iter()
        .enumerate()
        .max_by(|left, right| left.1.cmp(right.1))
        .unwrap_or((5, &0));

    if *best <= 0 {
        if KIND_HINTS_FACT.iter().any(|hint| lowered.contains(hint)) {
            "fact"
        } else {
            "note"
        }
    } else {
        kinds[index]
    }
}

fn base_importance(kind: &str) -> f64 {
    match kind {
        "decision" => 0.84,
        "constraint" => 0.82,
        "task" => 0.78,
        "preference" => 0.66,
        "fact" => 0.63,
        _ => 0.46,
    }
}

fn base_certainty(kind: &str) -> f64 {
    match kind {
        "decision" => 0.90,
        "constraint" => 0.88,
        "task" => 0.82,
        "preference" => 0.80,
        "fact" => 0.77,
        _ => 0.70,
    }
}

fn infer_importance_internal(text: &str, kind: &str) -> f64 {
    let lowered = canonicalize_text(text);
    let mut score = base_importance(kind);

    if STRONG_SIGNAL_WORDS.iter().any(|word| lowered.contains(word)) {
        score += 0.10;
    }
    if semantic_terms_internal(text, None).len() >= 6 {
        score += 0.05;
    }
    if kind == "note" && lowered.chars().count() < 40 {
        score -= 0.08;
    }

    (score.clamp(0.05, 1.0) * 100.0).round() / 100.0
}

fn infer_certainty_internal(text: &str, kind: &str) -> f64 {
    let lowered = canonicalize_text(text);
    let mut score = base_certainty(kind);

    if HEDGE_WORDS.iter().any(|word| lowered.contains(word)) {
        score -= 0.18;
    }
    if STRONG_SIGNAL_WORDS.iter().any(|word| lowered.contains(word)) {
        score += 0.06;
    }

    (score.clamp(0.2, 0.99) * 100.0).round() / 100.0
}

fn derive_title_internal(text: &str, kind: &str, max_words: usize, max_chars: usize) -> String {
    let normalized = normalize_space(text);
    let stripped = match kind {
        "decision" => strip_prefix_ci(&normalized, DECISION_PREFIXES),
        "constraint" => strip_prefix_ci(&normalized, CONSTRAINT_PREFIXES),
        "task" => strip_prefix_ci(&normalized, TASK_PREFIXES),
        "preference" => strip_prefix_ci(&normalized, PREFERENCE_PREFIXES),
        _ => normalized.as_str(),
    };

    let mut words = stripped.split_whitespace().take(max_words).collect::<Vec<_>>();
    if words.is_empty() {
        words = normalized.split_whitespace().take(max_words).collect();
    }
    let title = words.join(" ").trim_end_matches([' ', ',', ':', ';', '.', '-']).to_string();
    if title.is_empty() {
        return derive_summary_internal(text, max_chars);
    }
    truncate_with_ellipsis(&title, max_chars)
}

fn derive_summary_internal(text: &str, max_chars: usize) -> String {
    for line in text.lines() {
        let normalized = normalize_space(line);
        if !normalized.is_empty() {
            return truncate_with_ellipsis(&normalized, max_chars);
        }
    }
    String::new()
}

fn derive_candidate_tags_internal(text: &str, base_tags: &[String], limit: usize) -> Vec<String> {
    let mut tags: Vec<String> = Vec::new();
    for tag in base_tags {
        let cleaned = normalize_space(tag).to_lowercase();
        if !cleaned.is_empty() && !tags.iter().any(|item| item == &cleaned) {
            tags.push(cleaned);
        }
    }

    for term in semantic_terms_internal(text, Some(10)) {
        if !tags.iter().any(|item| item == &term) {
            tags.push(term);
        }
        if tags.len() >= limit {
            break;
        }
    }
    tags
}

fn split_sentences(text: &str) -> Vec<String> {
    let mut results: Vec<String> = Vec::new();
    let mut buffer = String::new();
    let chars: Vec<char> = text.chars().collect();
    let mut index = 0;

    while index < chars.len() {
        let ch = chars[index];
        buffer.push(ch);
        let is_break = matches!(ch, '.' | '!' | '?');
        let next = chars.get(index + 1).copied();
        if is_break && next.map(|item| item.is_whitespace()).unwrap_or(true) {
            let cleaned = normalize_space(&buffer);
            if !cleaned.is_empty() {
                results.push(cleaned);
            }
            buffer.clear();
        }
        index += 1;
    }

    let cleaned = normalize_space(&buffer);
    if !cleaned.is_empty() {
        results.push(cleaned);
    }
    results
}

fn split_ingest_chunk_internal(text: &str, max_chars: usize, force_sentences: bool) -> Vec<String> {
    let cleaned = normalize_space(text);
    if cleaned.is_empty() {
        return Vec::new();
    }

    let pieces = split_sentences(&cleaned);
    if force_sentences && pieces.len() > 1 {
        return pieces
            .into_iter()
            .map(|piece| truncate_with_ellipsis(&piece, max_chars))
            .collect();
    }

    if cleaned.chars().count() <= max_chars {
        return vec![cleaned];
    }
    if pieces.len() <= 1 {
        return vec![truncate_with_ellipsis(&cleaned, max_chars)];
    }

    let mut results: Vec<String> = Vec::new();
    let mut buffer = String::new();
    for piece in pieces {
        let candidate = if buffer.is_empty() {
            piece.clone()
        } else {
            format!("{buffer} {piece}")
        };

        if candidate.chars().count() <= max_chars {
            buffer = candidate;
            continue;
        }
        if !buffer.is_empty() {
            results.push(buffer.clone());
        }
        buffer = piece;
    }

    if !buffer.is_empty() {
        results.push(buffer);
    }
    results
}

fn strip_bullet_prefix(line: &str) -> String {
    let trimmed = line.trim_start();
    let chars: Vec<(usize, char)> = trimmed.char_indices().collect();
    if chars.is_empty() {
        return String::new();
    }

    let first = chars[0].1;
    if first == '-' || first == '*' || first == '\u{2022}' {
        let mut cut = chars[0].0 + first.len_utf8();
        for (index, ch) in chars.iter().skip(1) {
            if *ch == '-' || *ch == '*' || *ch == '\u{2022}' || ch.is_whitespace() {
                cut = *index + ch.len_utf8();
            } else {
                break;
            }
        }
        return trimmed[cut..].trim_start().to_string();
    }

    let mut index = 0;
    while index < chars.len() && chars[index].1.is_ascii_digit() {
        index += 1;
    }
    if index > 0 && index < chars.len() && (chars[index].1 == '.' || chars[index].1 == ')') {
        let cut = chars[index].0 + chars[index].1.len_utf8();
        return trimmed[cut..].trim_start().to_string();
    }

    trimmed.to_string()
}

fn split_memory_candidates_internal(text: &str, max_items: usize, max_chars: usize) -> Vec<String> {
    let mut segments: Vec<String> = Vec::new();
    for line in text.replace("\r\n", "\n").lines() {
        let cleaned = normalize_space(&strip_bullet_prefix(line));
        if cleaned.is_empty() {
            continue;
        }
        segments.extend(split_ingest_chunk_internal(&cleaned, max_chars, false));
    }

    if segments.len() <= 1 {
        segments = split_ingest_chunk_internal(&normalize_space(text), max_chars, true);
    }

    let mut seen: HashSet<String> = HashSet::new();
    let mut unique_segments: Vec<String> = Vec::new();
    for segment in segments {
        let cleaned = normalize_space(&segment);
        if cleaned.chars().count() < 12 {
            continue;
        }
        let canonical = canonicalize_text(&cleaned);
        if canonical.is_empty() || seen.contains(&canonical) {
            continue;
        }
        seen.insert(canonical);
        unique_segments.push(cleaned);
        if unique_segments.len() >= max_items {
            break;
        }
    }
    unique_segments
}

fn build_fts_query_internal(query: &str) -> String {
    extract_terms_internal(query)
        .into_iter()
        .map(|term| format!("{term}*"))
        .collect::<Vec<_>>()
        .join(" OR ")
}

fn char_index_from_byte(value: &str, byte_index: usize) -> usize {
    value[..byte_index].chars().count()
}

fn slice_chars(value: &str, start: usize, len: usize) -> String {
    value.chars().skip(start).take(len).collect()
}

fn make_excerpt_internal(summary: &str, content: &str, terms: &[String], max_chars: usize) -> String {
    let text = normalize_space(if summary.trim().is_empty() { content } else { summary });
    if text.chars().count() <= max_chars {
        return text;
    }
    if terms.is_empty() {
        return truncate_with_ellipsis(&text, max_chars);
    }

    let lower = text.to_lowercase();
    let first_match = terms
        .iter()
        .filter_map(|term| lower.find(term))
        .min_by(|left, right| {
            if left == right {
                Ordering::Equal
            } else {
                left.cmp(right)
            }
        });

    let Some(byte_pos) = first_match else {
        return truncate_with_ellipsis(&text, max_chars);
    };

    let term_char_pos = char_index_from_byte(&text, byte_pos);
    let start = term_char_pos.saturating_sub(40);
    let mut excerpt = slice_chars(&text, start, max_chars);

    if start > 0 {
        excerpt = format!("...{}", excerpt.chars().skip(3).collect::<String>());
    }
    if start + max_chars < text.chars().count() {
        let trimmed = excerpt.chars().take(max_chars.saturating_sub(3)).collect::<String>();
        excerpt = format!("{}...", trimmed.trim_end());
    }
    excerpt
}

fn light_stem_internal(term: &str) -> String {
    let term_chars = term.chars().count();
    if term_chars <= LIGHT_STEM_MIN_LEN {
        return term.to_string();
    }
    for suffix in UKRAINIAN_SUFFIXES {
        if term.ends_with(suffix) {
            let suffix_chars = suffix.chars().count();
            if term_chars - suffix_chars >= LIGHT_STEM_MIN_LEN {
                let stem_byte_end = term.len() - suffix.len();
                return term[..stem_byte_end].to_string();
            }
        }
    }
    term.to_string()
}

fn strip_ukrainian_prefix_internal(term: &str) -> String {
    let mut current = term.to_string();
    for _ in 0..DEEP_STEM_MAX_ITERATIONS {
        let current_chars = current.chars().count();
        if current_chars <= DEEP_STEM_MIN_LEN {
            break;
        }
        let mut stripped: Option<String> = None;
        for prefix in UKRAINIAN_PREFIXES {
            if current.starts_with(prefix) {
                let prefix_chars = prefix.chars().count();
                if current_chars - prefix_chars >= DEEP_STEM_MIN_LEN {
                    stripped = Some(current[prefix.len()..].to_string());
                    break;
                }
            }
        }
        match stripped {
            Some(next) if next != current => current = next,
            _ => break,
        }
    }
    current
}

fn deep_stem_internal(term: &str) -> String {
    strip_ukrainian_prefix_internal(&light_stem_internal(term))
}

fn compute_stems_text_internal(title: &str, content: &str, tags: &[String]) -> String {
    let mut parts: Vec<String> = vec![title.to_string(), content.to_string()];
    if !tags.is_empty() {
        parts.push(tags.join(" "));
    }
    let combined = parts.join(" ");
    let terms = semantic_terms_internal(&combined, None);
    let mut seen: HashSet<String> = HashSet::new();
    let mut stems: Vec<String> = Vec::new();
    for term in terms {
        let stem = deep_stem_internal(&term);
        if !stem.is_empty() && !seen.contains(&stem) {
            seen.insert(stem.clone());
            stems.push(stem);
        }
    }
    stems.join(" ")
}

fn token_overlap_score_internal(left: &str, right: &str) -> f64 {
    let left_terms: HashSet<String> = semantic_terms_internal(left, None).into_iter().collect();
    let right_terms: HashSet<String> = semantic_terms_internal(right, None).into_iter().collect();
    if left_terms.is_empty() || right_terms.is_empty() {
        return 0.0;
    }

    let intersection = left_terms.intersection(&right_terms).count() as f64;
    let union = left_terms.union(&right_terms).count() as f64;
    if union == 0.0 {
        0.0
    } else {
        intersection / union
    }
}

fn duplicate_match_score_internal(left: &str, right: &str) -> f64 {
    let left_terms: HashSet<String> = semantic_terms_internal(left, None).into_iter().collect();
    let right_terms: HashSet<String> = semantic_terms_internal(right, None).into_iter().collect();
    if left_terms.is_empty() || right_terms.is_empty() {
        return 0.0;
    }

    let intersection = left_terms.intersection(&right_terms).count() as f64;
    let baseline = left_terms.len().min(right_terms.len()) as f64;
    if baseline == 0.0 {
        0.0
    } else {
        intersection / baseline
    }
}

fn recency_score_internal(timestamp: Option<&str>, now: DateTime<Utc>) -> f64 {
    let Some(timestamp) = timestamp else {
        return 0.0;
    };
    let Ok(parsed) = DateTime::parse_from_rfc3339(timestamp) else {
        return 0.0;
    };
    let age_seconds = (now - parsed.with_timezone(&Utc)).num_seconds().max(0) as f64;
    let age_days = age_seconds / 86_400.0;
    1.0 / (1.0 + age_days / 14.0)
}

fn rank_rows_internal(
    rows: Vec<RankCandidate>,
    terms: &[String],
    now: DateTime<Utc>,
) -> Vec<RankedCandidate> {
    let terms_lower = terms
        .iter()
        .map(|term| term.to_lowercase())
        .collect::<Vec<_>>();

    let mut ranked = rows
        .into_iter()
        .enumerate()
        .map(|(index, row)| {
            let tags_text = row.tags.join(" ");
            let haystack = format!("{} {} {} {}", row.title, row.summary, row.content, tags_text).to_lowercase();
            let title = row.title.to_lowercase();

            let coverage = if terms_lower.is_empty() {
                0.0
            } else {
                let matches = terms_lower
                    .iter()
                    .filter(|term| haystack.contains(term.as_str()))
                    .count();
                matches as f64 / terms_lower.len() as f64
            };

            let title_bonus = if terms_lower
                .iter()
                .any(|term| title.contains(term.as_str()))
            {
                0.15
            } else {
                0.0
            };
            let recency_bonus = recency_score_internal(Some(row.updated_at.as_str()), now);
            let access_bonus = (row.access_count.min(8) as f64 / 8.0) * 0.14;
            let lexical_bonus = 1.15 / (index as f64 + 1.0);
            let score = lexical_bonus
                + coverage * 0.95
                + row.importance * 0.60
                + row.certainty * 0.25
                + recency_bonus * 0.22
                + access_bonus
                + title_bonus
                + actionability_bonus(&row.kind);

            RankedCandidate {
                id: row.id,
                scope: row.scope,
                kind: row.kind,
                title: row.title,
                summary: row.summary.clone(),
                content: row.content.clone(),
                tags: row.tags,
                source: row.source,
                importance: row.importance,
                certainty: row.certainty,
                access_count: row.access_count,
                created_at: row.created_at,
                updated_at: row.updated_at,
                last_accessed_at: row.last_accessed_at,
                score: (score * 10_000.0).round() / 10_000.0,
                excerpt: make_excerpt_internal(&row.summary, &row.content, &terms_lower, 220),
            }
        })
        .collect::<Vec<_>>();

    ranked.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(Ordering::Equal)
    });
    ranked
}

fn render_pack_internal(
    results: &[RankedCandidate],
    budget_chars: usize,
    limit: usize,
    header: &str,
) -> PackOutput {
    let mut lines = vec![header.to_string()];
    let mut items: Vec<PackItem> = Vec::new();

    for result in results {
        if items.len() >= limit {
            break;
        }

        let mut line = format!(
            "- [{}/{}] {}: {}",
            result.kind, result.scope, result.title, result.excerpt
        );
        if !result.source.is_empty() {
            line.push_str(&format!(" (source: {})", result.source));
        }

        let mut candidate_lines = lines.clone();
        candidate_lines.push(line.clone());
        let candidate = candidate_lines.join("\n");
        if count_chars(&candidate) > budget_chars && !items.is_empty() {
            break;
        }
        if count_chars(&candidate) > budget_chars {
            let current = lines.join("\n");
            let remaining = budget_chars.saturating_sub(count_chars(&current) + 1);
            let target = remaining.saturating_sub(3);
            line = if target == 0 {
                "...".to_string()
            } else {
                truncate_with_ellipsis(&line, target + 3)
            };
        }

        items.push(PackItem {
            id: result.id.clone(),
            kind: result.kind.clone(),
            scope: result.scope.clone(),
            title: result.title.clone(),
            excerpt: result.excerpt.clone(),
            score: result.score,
        });
        lines.push(line);
    }

    let mut rendered = lines.join("\n");
    if count_chars(&rendered) > budget_chars {
        rendered = truncate_with_ellipsis(&rendered, budget_chars);
    }

    PackOutput {
        budget_chars,
        used_chars: count_chars(&rendered),
        items,
        rendered,
    }
}

#[pyfunction]
fn derive_summary(text: &str, max_chars: usize) -> String {
    derive_summary_internal(text, max_chars)
}

#[pyfunction]
fn semantic_terms(text: &str, limit: isize) -> Vec<String> {
    let limit = if limit < 0 { None } else { Some(limit as usize) };
    semantic_terms_internal(text, limit)
}

#[pyfunction]
fn token_overlap_score(left: &str, right: &str) -> f64 {
    token_overlap_score_internal(left, right)
}

#[pyfunction]
fn duplicate_match_score(left: &str, right: &str) -> f64 {
    duplicate_match_score_internal(left, right)
}

#[pyfunction]
fn derive_title(text: &str, kind: &str, max_words: usize, max_chars: usize) -> String {
    derive_title_internal(text, kind, max_words, max_chars)
}

#[pyfunction]
fn infer_kind(text: &str) -> String {
    infer_kind_internal(text).to_string()
}

#[pyfunction]
fn infer_importance(text: &str, kind: &str) -> f64 {
    infer_importance_internal(text, kind)
}

#[pyfunction]
fn infer_certainty(text: &str, kind: &str) -> f64 {
    infer_certainty_internal(text, kind)
}

#[pyfunction]
fn derive_candidate_tags(text: &str, base_tags: Vec<String>, limit: usize) -> Vec<String> {
    derive_candidate_tags_internal(text, &base_tags, limit)
}

#[pyfunction]
fn split_memory_candidates(text: &str, max_items: usize, max_chars: usize) -> Vec<String> {
    split_memory_candidates_internal(text, max_items, max_chars)
}

#[pyfunction]
fn extract_terms(query: &str) -> Vec<String> {
    extract_terms_internal(query)
}

#[pyfunction]
fn build_fts_query(query: &str) -> String {
    build_fts_query_internal(query)
}

#[pyfunction]
fn make_excerpt(summary: &str, content: &str, terms: Vec<String>, max_chars: usize) -> String {
    make_excerpt_internal(summary, content, &terms, max_chars)
}

#[pyfunction]
fn choose_richer_text(existing: &str, candidate: &str, max_chars: isize) -> String {
    let max_chars = if max_chars < 0 {
        None
    } else {
        Some(max_chars as usize)
    };
    choose_richer_text_internal(existing, candidate, max_chars)
}

#[pyfunction]
fn merge_sources(existing: &str, candidate: &str, max_chars: usize) -> String {
    merge_sources_internal(existing, candidate, max_chars)
}

#[pyfunction]
fn find_duplicate_candidate(
    candidates: Vec<(usize, String)>,
    content: &str,
    threshold: f64,
) -> Option<usize> {
    for (index, candidate_content) in candidates {
        if duplicate_match_score_internal(&candidate_content, content) >= threshold {
            return Some(index);
        }
    }
    None
}

#[pyfunction]
fn merge_memory_fields(
    existing_title: &str,
    existing_content: &str,
    existing_source: &str,
    existing_tags: Vec<String>,
    existing_importance: f64,
    existing_certainty: f64,
    candidate_title: &str,
    candidate_content: &str,
    candidate_source: &str,
    candidate_tags: Vec<String>,
    candidate_importance: f64,
    candidate_certainty: f64,
    title_max_chars: usize,
    source_max_chars: usize,
) -> (
    String,
    String,
    String,
    Vec<String>,
    String,
    f64,
    f64,
) {
    let merged_title = choose_richer_text_internal(existing_title, candidate_title, Some(title_max_chars));
    let merged_content = choose_richer_text_internal(existing_content, candidate_content, None);
    let merged_summary = derive_summary_internal(&merged_content, 180);
    let merged_tags = normalize_tags_internal(
        &existing_tags
            .into_iter()
            .chain(candidate_tags.into_iter())
            .collect::<Vec<_>>(),
    );
    let merged_source = merge_sources_internal(existing_source, candidate_source, source_max_chars);
    let merged_importance = existing_importance.max(candidate_importance);
    let merged_certainty = (existing_certainty.max(candidate_certainty) + 0.02).min(1.0);

    (
        merged_title,
        merged_content,
        merged_summary,
        merged_tags,
        merged_source,
        merged_importance,
        merged_certainty,
    )
}

#[pyfunction]
fn light_stem(term: &str) -> String {
    light_stem_internal(term)
}

#[pyfunction]
fn deep_stem(term: &str) -> String {
    deep_stem_internal(term)
}

#[pyfunction]
fn compute_stems_text(title: &str, content: &str, tags: Vec<String>) -> String {
    compute_stems_text_internal(title, content, &tags)
}

#[pyfunction]
fn rank_rows_tuples(
    rows: Vec<(usize, String, String, String, String, String, f64, f64, i64, String)>,
    terms: Vec<String>,
    now_iso: &str,
    limit: usize,
) -> PyResult<Vec<(usize, f64, String)>> {
    let now = DateTime::parse_from_rfc3339(now_iso)
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyValueError, _>(err.to_string()))?
        .with_timezone(&Utc);
    let terms_lower = terms
        .iter()
        .map(|term| term.to_lowercase())
        .collect::<Vec<_>>();

    let mut ranked = rows
        .into_iter()
        .enumerate()
        .map(|(lexical_index, row)| {
            let (
                source_index,
                kind,
                title,
                summary,
                content,
                tags_text,
                importance,
                certainty,
                access_count,
                updated_at,
            ) = row;

            let haystack = format!("{title} {summary} {content} {tags_text}").to_lowercase();
            let lowered_title = title.to_lowercase();
            let coverage = if terms_lower.is_empty() {
                0.0
            } else {
                let matches = terms_lower
                    .iter()
                    .filter(|term| haystack.contains(term.as_str()))
                    .count();
                matches as f64 / terms_lower.len() as f64
            };

            let title_bonus = if terms_lower
                .iter()
                .any(|term| lowered_title.contains(term.as_str()))
            {
                0.15
            } else {
                0.0
            };
            let recency_bonus = recency_score_internal(Some(updated_at.as_str()), now);
            let access_bonus = (access_count.min(8) as f64 / 8.0) * 0.14;
            let lexical_bonus = 1.15 / (lexical_index as f64 + 1.0);
            let score = lexical_bonus
                + coverage * 0.95
                + importance * 0.60
                + certainty * 0.25
                + recency_bonus * 0.22
                + access_bonus
                + title_bonus
                + actionability_bonus(&kind);
            let excerpt = make_excerpt_internal(&summary, &content, &terms_lower, 220);

            (source_index, (score * 10_000.0).round() / 10_000.0, excerpt)
        })
        .collect::<Vec<_>>();

    ranked.sort_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(Ordering::Equal)
    });
    ranked.truncate(limit);
    Ok(ranked)
}

#[pyfunction]
fn rank_rows_json(rows_json: &str, terms: Vec<String>, now_iso: &str) -> PyResult<String> {
    let rows = serde_json::from_str::<Vec<RankCandidate>>(rows_json)
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyValueError, _>(err.to_string()))?;
    let now = DateTime::parse_from_rfc3339(now_iso)
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyValueError, _>(err.to_string()))?
        .with_timezone(&Utc);
    let ranked = rank_rows_internal(rows, &terms, now);
    serde_json::to_string(&ranked)
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyValueError, _>(err.to_string()))
}

#[pyfunction]
fn render_pack_json(results_json: &str, budget_chars: usize, limit: usize, header: &str) -> PyResult<String> {
    let results = serde_json::from_str::<Vec<RankedCandidate>>(results_json)
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyValueError, _>(err.to_string()))?;
    let pack = render_pack_internal(&results, budget_chars, limit, header);
    serde_json::to_string(&pack)
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyValueError, _>(err.to_string()))
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(derive_summary, m)?)?;
    m.add_function(wrap_pyfunction!(semantic_terms, m)?)?;
    m.add_function(wrap_pyfunction!(token_overlap_score, m)?)?;
    m.add_function(wrap_pyfunction!(derive_title, m)?)?;
    m.add_function(wrap_pyfunction!(infer_kind, m)?)?;
    m.add_function(wrap_pyfunction!(infer_importance, m)?)?;
    m.add_function(wrap_pyfunction!(infer_certainty, m)?)?;
    m.add_function(wrap_pyfunction!(derive_candidate_tags, m)?)?;
    m.add_function(wrap_pyfunction!(split_memory_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(extract_terms, m)?)?;
    m.add_function(wrap_pyfunction!(build_fts_query, m)?)?;
    m.add_function(wrap_pyfunction!(make_excerpt, m)?)?;
    m.add_function(wrap_pyfunction!(duplicate_match_score, m)?)?;
    m.add_function(wrap_pyfunction!(choose_richer_text, m)?)?;
    m.add_function(wrap_pyfunction!(merge_sources, m)?)?;
    m.add_function(wrap_pyfunction!(find_duplicate_candidate, m)?)?;
    m.add_function(wrap_pyfunction!(merge_memory_fields, m)?)?;
    m.add_function(wrap_pyfunction!(light_stem, m)?)?;
    m.add_function(wrap_pyfunction!(deep_stem, m)?)?;
    m.add_function(wrap_pyfunction!(compute_stems_text, m)?)?;
    m.add_function(wrap_pyfunction!(rank_rows_tuples, m)?)?;
    m.add_function(wrap_pyfunction!(rank_rows_json, m)?)?;
    m.add_function(wrap_pyfunction!(render_pack_json, m)?)?;
    Ok(())
}
