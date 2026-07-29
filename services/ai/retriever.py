"""Retrieval over the knowledge base.

Two backends behind one interface:

- **TF-IDF** (default) — sklearn, no API key, no network, deterministic. This
  is the backend that always works, including in the app's offline mode, so it
  is the default rather than a fallback.
- **Embeddings** — OpenAI-compatible vectors when a key is configured. Better
  at matching paraphrase ("why did my fund tank" → drawdown), at the cost of a
  network call. The index is cached on disk and rebuilt only when the corpus
  changes.

Retrieval returns scored passages with citations attached. A passage below the
score floor is dropped rather than padded in: handing the model weak matches is
how a grounded answer turns into a confident wrong one.

Known limitation: sparse retrieval matches words, not meaning, so an
out-of-domain question can still surface a passage on a shared term ("capital
of France" scoring against "capital withdrawal"). The score floor and relative
cutoff trim most of it, but the real guard is in the prompt — the model is told
retrieved passages may be irrelevant and must not claim support from one that
does not contain the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from config.settings import settings
from services.ai.knowledge_base import Document, corpus_fingerprint, load_corpus
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Cosine similarity below this is not a real match. TF-IDF scores on short
# queries are small in absolute terms, hence the low floor.
TFIDF_SCORE_FLOOR = 0.06
EMBEDDING_SCORE_FLOOR = 0.30

# Keep only passages within this fraction of the best hit. A tail match at a
# third of the top score is topic drift, not support.
RELATIVE_CUTOFF = 0.35

INDEX_DIR = Path(settings.data_cache_dir) / "kb_index"


@dataclass
class RetrievedPassage:
    document: Document
    score: float

    @property
    def citation(self) -> str:
        return self.document.citation

    def to_dict(self) -> dict[str, Any]:
        return {**self.document.to_dict(), "score": round(self.score, 4)}


class Retriever:
    """Sparse or dense retrieval over the knowledge base."""

    def __init__(
        self,
        documents: Optional[list[Document]] = None,
        *,
        backend: Optional[str] = None,
    ) -> None:
        self.documents = documents if documents is not None else load_corpus()
        self.backend = backend or ("embedding" if self._embeddings_available() else "tfidf")
        self._vectorizer = None
        self._matrix = None
        self._embeddings: Optional[np.ndarray] = None
        self._ready = False

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _embeddings_available() -> bool:
        return bool(getattr(settings, "openai_api_key", None)) and bool(
            getattr(settings, "rag_use_embeddings", False)
        )

    def build(self) -> "Retriever":
        """Build the index. Falls back to TF-IDF if embeddings fail."""
        if not self.documents:
            logger.warning("Retriever has no documents to index")
            self._ready = False
            return self

        if self.backend == "embedding":
            try:
                self._build_embeddings()
                self._ready = True
                return self
            except Exception as exc:
                logger.warning("Embedding index failed, using TF-IDF: {}", exc)
                self.backend = "tfidf"

        self._build_tfidf()
        self._ready = True
        return self

    def _build_tfidf(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vectorizer = TfidfVectorizer(
            stop_words="english",
            # Bigrams matter here: "expense ratio", "maximum drawdown",
            # "standard deviation" are the actual query terms.
            ngram_range=(1, 2),
            sublinear_tf=True,
            min_df=1,
        )
        self._matrix = self._vectorizer.fit_transform([d.text for d in self.documents])
        logger.info("TF-IDF index: {} docs, {} features",
                    len(self.documents), len(self._vectorizer.vocabulary_))

    def _index_path(self) -> Path:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        return INDEX_DIR / f"emb_{corpus_fingerprint(self.documents)}.npz"

    def _build_embeddings(self) -> None:
        path = self._index_path()
        if path.exists():
            data = np.load(path, allow_pickle=False)
            self._embeddings = data["vectors"]
            if self._embeddings.shape[0] == len(self.documents):
                logger.info("Loaded cached embedding index: {}", path.name)
                return
            logger.info("Cached embedding index is stale, rebuilding")

        vectors = self._embed([d.text for d in self.documents])
        self._embeddings = vectors
        np.savez_compressed(path, vectors=vectors)
        logger.info("Built embedding index: {} docs", len(self.documents))

    def _embed(self, texts: list[str]) -> np.ndarray:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=getattr(settings, "openai_base_url", None) or None,
        )
        model = getattr(settings, "rag_embedding_model", "text-embedding-3-small")
        out: list[list[float]] = []
        # Batch to stay clear of per-request token limits.
        for i in range(0, len(texts), 64):
            resp = client.embeddings.create(model=model, input=texts[i : i + 64])
            out.extend(item.embedding for item in resp.data)
        arr = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.clip(norms, 1e-9, None)

    # -------------------------------------------------------------- retrieval
    def search(self, query: str, k: int = 4) -> list[RetrievedPassage]:
        """Top-k passages above the score floor, best first."""
        if not self._ready:
            self.build()
        if not self.documents or not query or not query.strip():
            return []

        try:
            if self.backend == "embedding" and self._embeddings is not None:
                scores = self._score_embeddings(query)
                floor = EMBEDDING_SCORE_FLOOR
            else:
                scores = self._score_tfidf(query)
                floor = TFIDF_SCORE_FLOOR
        except Exception as exc:
            logger.warning("Retrieval failed: {}", exc)
            return []

        ranked = np.argsort(scores)[::-1][: max(k, 1)]
        top = float(scores[ranked[0]]) if len(ranked) else 0.0
        if top < floor:
            return []
        cutoff = max(floor, top * RELATIVE_CUTOFF)
        return [
            RetrievedPassage(document=self.documents[i], score=float(scores[i]))
            for i in ranked
            if scores[i] >= cutoff
        ]

    def _score_tfidf(self, query: str) -> np.ndarray:
        from sklearn.metrics.pairwise import cosine_similarity

        vec = self._vectorizer.transform([query])
        return cosine_similarity(vec, self._matrix).ravel()

    def _score_embeddings(self, query: str) -> np.ndarray:
        vec = self._embed([query])[0]
        return self._embeddings @ vec

    # ------------------------------------------------------------------ views
    def as_context(self, passages: list[RetrievedPassage]) -> str:
        """Render passages as a citable block for the model prompt."""
        if not passages:
            return ""
        parts = [
            "KNOWLEDGE BASE (cite these by their [source] tag; do not invent others):"
        ]
        for p in passages:
            parts.append(f"[{p.citation}]\n{p.document.text}")
        return "\n\n".join(parts)

    @property
    def size(self) -> int:
        return len(self.documents)


_retriever: Optional[Retriever] = None


def get_retriever() -> Retriever:
    """Process-wide retriever so the index is built once."""
    global _retriever
    if _retriever is None:
        _retriever = Retriever().build()
    return _retriever


def reset_retriever() -> None:
    """Drop the cached retriever (tests, or after editing the corpus)."""
    global _retriever
    _retriever = None
