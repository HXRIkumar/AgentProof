"""Inspectable lexical + embedding retrieval with an explicit lexical fallback."""

import math
import os
import re
import threading
from collections import Counter


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def cosine(left, right) -> float:
    if not left or len(left) != len(right):
        return 0.0
    if not all(isinstance(x, (float, int)) and math.isfinite(x) for x in [*left, *right]):
        return 0.0
    denom = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / denom if denom else 0.0


class SentenceEmbedder:
    """Load cached weights only. Installing an optional package never downloads a model."""

    def __init__(self, model=None):
        self.name = model or os.getenv(
            "ANSWER_LAB_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        self.revision = os.getenv("ANSWER_LAB_EMBEDDING_REVISION", "unrecorded")
        self._model = None
        self._failed = False
        self._lock = threading.Lock()
        self._cache = {}

    @property
    def status(self):
        return "unavailable" if self._failed else "loaded" if self._model is not None else "lazy"

    def encode(self, texts: list[str]) -> list[list[float]] | None:
        with self._lock:
            if self._failed:
                return None
            try:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(
                        self.name, local_files_only=True, device="cpu"
                    )
                missing = list(dict.fromkeys(text for text in texts if text not in self._cache))
                if missing:
                    vectors = self._model.encode(
                        missing, normalize_embeddings=True, show_progress_bar=False
                    ).tolist()
                    if len(self._cache) + len(missing) > 2000:
                        self._cache.clear()
                    self._cache.update(zip(missing, vectors))
                return [self._cache[text] for text in texts]
            except (ImportError, OSError, RuntimeError, ValueError):
                self._failed = True
                return None


def chunks(sources) -> list[dict]:
    result = []
    for source in sources:
        text = source.text
        start = 0
        while start < len(text):
            end = min(len(text), start + 2400)
            if end < len(text):
                boundary = max(
                    text.rfind(". ", start + 1200, end), text.rfind("\n", start + 1200, end)
                )
                if boundary > start:
                    end = boundary + 1
            result.append(
                {
                    "source_id": source.id,
                    "title": source.title,
                    "text": text[start:end],
                    "start": start,
                    "end": end,
                }
            )
            if end == len(text):
                break
            start = max(start + 1, end - 160)
    return result


def retrieve(question: str, sources, embedder=None, limit=4) -> dict:
    passages = chunks(sources)
    corpus = [tokens(passage["text"]) for passage in passages]
    query = list(dict.fromkeys(tokens(question)))
    avg_length = sum(map(len, corpus)) / max(1, len(corpus))
    frequencies = Counter(word for passage in corpus for word in set(passage))
    lexical = []
    for passage in corpus:
        counts = Counter(passage)
        score = 0.0
        for word in query:
            inverse = math.log(
                1 + (len(corpus) - frequencies[word] + 0.5) / (frequencies[word] + 0.5)
            )
            count = counts[word]
            denominator = count + 1.2 * (0.25 + 0.75 * len(passage) / max(1, avg_length))
            score += inverse * count * 2.2 / denominator if denominator else 0
        lexical.append(score)
    vectors = embedder.encode([question, *[p["text"] for p in passages]]) if embedder else None
    semantic = [cosine(vectors[0], vector) for vector in vectors[1:]] if vectors else None
    max_lex = max(lexical, default=0)
    for index, passage in enumerate(passages):
        lex = lexical[index] / max_lex if max_lex else 0.0
        sem = semantic[index] if semantic is not None else None
        passage.update(
            lexical_score=lex,
            semantic_score=sem,
            score=(0.45 * lex + 0.55 * max(0, sem)) if sem is not None else lex,
        )
    ranked = sorted(enumerate(passages), key=lambda pair: (-pair[1]["score"], pair[0]))
    selected = [passage for _, passage in ranked[:limit]]
    return {
        "method": "hybrid_bm25_embeddings" if vectors else "bm25",
        "embedding_model": getattr(embedder, "name", None) if vectors else None,
        "selected": selected,
        "total_chunks": len(passages),
        "selected_chunks": len(selected),
    }


def critical_signature(question: str) -> tuple:
    """Cheap conservative semantic-cache rejection, followed by a new model critique."""
    words = tokens(question)
    negatives = {
        "not",
        "never",
        "no",
        "except",
        "without",
        "before",
        "after",
        "least",
        "most",
        "minimum",
        "maximum",
        "first",
        "last",
    }
    return (
        tuple(sorted(re.findall(r"\d+(?:[.,]\d+)*", question))),
        tuple(sorted(word for word in words if word in negatives))
        + tuple(re.findall(r"\b\w+n['’]t\b|\bcannot\b", question.casefold())),
    )
