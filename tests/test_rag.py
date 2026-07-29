"""Knowledge base chunking and retrieval."""

from __future__ import annotations

import pytest

from services.ai.knowledge_base import (
    Document,
    chunk_markdown,
    corpus_fingerprint,
    load_corpus,
)
from services.ai.retriever import Retriever

SAMPLE_MD = """# Guide Title

Intro paragraph that is long enough to survive the minimum chunk filter and
therefore should be indexed as its own passage under the title heading.

## Alpha

Alpha is excess return over the benchmark after adjusting for market risk.
This paragraph is deliberately long enough to clear the minimum chunk size so
that the chunker keeps it as a retrievable passage.

## Tiny

Too short.
"""


# ------------------------------------------------------------------ chunking
def test_chunker_splits_on_headings_and_keeps_section_titles():
    docs = chunk_markdown(SAMPLE_MD, "guide.md")
    sections = [d.section for d in docs]
    assert "Alpha" in sections
    assert all(d.source == "guide.md" for d in docs)


def test_tiny_sections_are_dropped():
    docs = chunk_markdown(SAMPLE_MD, "guide.md")
    assert "Tiny" not in [d.section for d in docs]


def test_citation_names_source_and_section():
    docs = chunk_markdown(SAMPLE_MD, "guide.md")
    alpha = next(d for d in docs if d.section == "Alpha")
    assert alpha.citation == "guide.md > Alpha"


def test_heading_is_prefixed_into_the_text_so_it_is_searchable():
    docs = chunk_markdown(SAMPLE_MD, "guide.md")
    alpha = next(d for d in docs if d.section == "Alpha")
    assert alpha.text.startswith("Alpha")


def test_long_sections_are_split_into_multiple_passages():
    body = "\n\n".join(["A fairly long paragraph about risk metrics." * 6] * 6)
    docs = chunk_markdown(f"# T\n\n## Big\n\n{body}\n", "big.md")
    assert len(docs) > 1
    assert all(d.section == "Big" for d in docs)


def test_doc_ids_are_unique_and_stable():
    first = chunk_markdown(SAMPLE_MD, "guide.md")
    second = chunk_markdown(SAMPLE_MD, "guide.md")
    ids = [d.doc_id for d in first]
    assert len(ids) == len(set(ids))
    assert ids == [d.doc_id for d in second]


def test_missing_directory_returns_empty_not_an_error(tmp_path):
    assert load_corpus(tmp_path / "nope") == []


def test_fingerprint_changes_with_the_corpus():
    a = chunk_markdown(SAMPLE_MD, "guide.md")
    b = chunk_markdown(SAMPLE_MD.replace("Alpha is", "Beta is"), "guide.md")
    assert corpus_fingerprint(a) != corpus_fingerprint(b)


# ----------------------------------------------------------------- retrieval
@pytest.fixture(scope="module")
def retriever() -> Retriever:
    return Retriever(backend="tfidf").build()


def test_shipped_corpus_is_not_empty(retriever):
    assert retriever.size > 10


@pytest.mark.parametrize(
    ("query", "expected_section"),
    [
        ("what is alpha", "Alpha"),
        ("explain maximum drawdown", "Maximum drawdown"),
        ("difference between direct and regular plans", "Direct vs Regular plans"),
        ("how much overlap between two funds is too much", "Fund overlap"),
        ("should I stop my SIP", "SIP and rupee cost averaging"),
        ("what is portfolio turnover", "Portfolio turnover"),
    ],
)
def test_domain_questions_retrieve_the_right_section(retriever, query, expected_section):
    hits = retriever.search(query, k=4)
    assert hits, f"no passage retrieved for {query!r}"
    assert expected_section in [h.document.section for h in hits]


def test_results_are_ordered_best_first(retriever):
    hits = retriever.search("expense ratio", k=4)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_weak_tail_matches_are_trimmed(retriever):
    # Everything returned must be within the relative cutoff of the best hit,
    # so a barely-related passage never rides along as apparent support.
    hits = retriever.search("what is alpha", k=6)
    assert hits
    assert all(h.score >= hits[0].score * 0.34 for h in hits)


def test_empty_query_retrieves_nothing(retriever):
    assert retriever.search("", k=3) == []
    assert retriever.search("   ", k=3) == []


def test_retriever_with_no_documents_is_safe():
    empty = Retriever(documents=[], backend="tfidf").build()
    assert empty.search("anything", k=3) == []


def test_as_context_labels_every_passage_with_its_citation(retriever):
    hits = retriever.search("what is beta", k=2)
    block = retriever.as_context(hits)
    assert "KNOWLEDGE BASE" in block
    for h in hits:
        assert f"[{h.citation}]" in block


def test_as_context_of_nothing_is_empty(retriever):
    assert retriever.as_context([]) == ""


def test_embedding_failure_falls_back_to_tfidf(monkeypatch):
    r = Retriever(
        documents=[Document("1", "a.md", "S", "alpha beta gamma risk metrics")],
        backend="embedding",
    )
    # Force the failure rather than relying on whether a key happens to be
    # configured — otherwise this test hits the network on a dev machine.
    monkeypatch.setattr(
        Retriever, "_build_embeddings", lambda self: (_ for _ in ()).throw(RuntimeError("no key"))
    )
    r.build()
    assert r.backend == "tfidf"
    assert r.search("alpha", k=1)


def test_embeddings_are_off_by_default_so_retrieval_needs_no_network():
    # rag_use_embeddings defaults False; the default retriever must be sparse.
    assert Retriever(documents=[]).backend == "tfidf"
