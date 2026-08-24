"""
Lightweight retrieval over the bundled knowledge base.

Works fully offline using keyword scoring. When an embedding
provider is configured, the retriever interface stays identical
so a vector backend can be swapped in later.
"""

from pathlib import Path

KB_DIR = Path(__file__).resolve().parent / "knowledge_base"

# In-memory corpus: [{path, category, title, text}]
_corpus: list[dict] = []
_loaded = False


def _load():
    global _loaded
    global _corpus

    if _loaded:
        return

    _loaded = True

    if not KB_DIR.exists():
        return

    for md_file in KB_DIR.rglob("*.md"):
        category = md_file.parent.name

        text = md_file.read_text(encoding="utf-8", errors="ignore")

        title = text.splitlines()[0].lstrip("# ").strip() if text else md_file.stem

        _corpus.append(
            {"path": str(md_file.name), "category": category,
             "title": title, "text": text}
        )


STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "did", "do", "does", "doing", "don't", "down", "during", "each", "few", "for",
    "from", "further", "had", "has", "have", "having", "he", "how", "if", "in",
    "into", "is", "it", "its", "itself", "me", "more", "most", "my", "no", "nor",
    "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "out", "over", "own", "same", "she", "should", "so", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these",
    "they", "this", "those", "through", "to", "too", "under", "until", "up", "very",
    "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "with", "would", "you", "your", "yours"
}


def _keyword_score(query_tokens: list[str], doc: dict, raw_query: str) -> float:
    lower_text = doc["text"].lower()
    lower_title = doc["title"].lower()
    lower_category = doc["category"].lower()
    lower_query = raw_query.lower().strip()

    score = 0.0

    # Boost for exact full query phrase match
    if len(lower_query) > 3 and lower_query in lower_text:
        score += 8.0
    if len(lower_query) > 3 and lower_query in lower_title:
        score += 15.0

    for token in query_tokens:
        if token in STOP_WORDS or len(token) < 2:
            continue

        if token in lower_title:
            score += 5.0

        if token in lower_category:
            score += 2.0

        occurrences = lower_text.count(token)
        if occurrences:
            score += 1.0 + min(occurrences - 1, 4) * 0.25

    return score


def retrieve(query: str, top_k: int = 3) -> list[dict]:
    """
    Return top_k knowledge chunks relevant to the query.
    Deterministic keyword scoring with stop-word filtering & title boosting.
    """

    _load()

    if not _corpus or not query or not query.strip():
        return []

    clean_query = (
        query.lower()
        .replace(",", " ")
        .replace("?", " ")
        .replace(".", " ")
        .replace("!", " ")
        .replace(":", " ")
        .replace(";", " ")
    )

    all_tokens = clean_query.split()
    content_tokens = [t for t in all_tokens if t not in STOP_WORDS and len(t) >= 2]

    # Fallback to all tokens if query consisted entirely of stop words
    tokens_to_use = content_tokens if content_tokens else all_tokens

    scored = []

    for doc in _corpus:
        score = _keyword_score(tokens_to_use, doc, query)

        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda pair: -pair[0])

    return [
        {
            "title": doc["title"],
            "category": doc["category"],
            "source": doc["path"],
            "excerpt": doc["text"][:1200],
            "score": round(score, 2),
        }
        for score, doc in scored[:top_k]
    ]

