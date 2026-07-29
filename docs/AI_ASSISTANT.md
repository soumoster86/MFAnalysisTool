# AI Assistant (Module 12) — retrieval-grounded answers

The assistant answers from a real retrieval corpus with citations, not from the
model's own recollection. It works with or without an API key.

## Two grounding sources, deliberately separate

| Block | Content | Origin |
|-------|---------|--------|
| `KNOWLEDGE BASE` | Definitions, formulas, how this app computes | Retrieved from `docs/kb/` |
| `CONTEXT` | The user's own portfolio figures + provenance caveat | Injected by the page |

Keeping them apart matters: general guidance is stable and citable, portfolio
figures are per-session and carry data-provenance warnings that must travel
with them.

## Corpus

Markdown in `docs/kb/`, split on headings so every passage keeps its section
title and cites as `file.md > Section`:

- `risk_metrics.md` — alpha, beta, volatility, Sharpe, Sortino, Treynor,
  information ratio, drawdown, capture ratios, Calmar, VaR/CVaR
- `costs_and_structure.md` — TER, Direct vs Regular, exit load, turnover, AUM,
  riskometer, IDCW vs Growth, manager tenure
- `portfolio_construction.md` — overlap, concentration, allocation, market cap,
  correlation, MPT and the efficient frontier, SIP
- `how_this_app_computes.md` — health score, data sources and fallbacks,
  alerts, goal planning, the ML pipeline, and what the app will not tell you

Add a file to `docs/kb/` and it is indexed on next start. Sections shorter than
120 characters are dropped; longer ones are split on paragraph boundaries.

## Retrieval

**TF-IDF is the default** (sklearn, unigrams + bigrams). No API key, no network
call, deterministic — so retrieval works in the app's offline mode rather than
being the first thing to break. Bigrams matter because the real queries are
phrases: "expense ratio", "maximum drawdown", "standard deviation".

Optional dense retrieval with OpenAI embeddings when `RAG_USE_EMBEDDINGS=true`
and a key is set. Better at paraphrase, at the cost of a network call. The index
is cached in `data/cache/kb_index/` keyed by a corpus fingerprint and rebuilt
only when the corpus changes. If embedding fails, it falls back to TF-IDF.

Passages must clear an absolute score floor *and* sit within 35% of the top
hit's score. A tail match at a third of the best score is topic drift, not
support, and padding the prompt with weak matches is how a grounded answer
turns into a confident wrong one.

### Known limitation

Sparse retrieval matches words, not meaning, so an out-of-domain question can
still surface a passage sharing a term — "capital of France" scores against
"capital withdrawal". The floor and cutoff trim most of it; the real guard is
in the prompt. Rule 9 tells the model that retrieved passages may be irrelevant
and that it must not claim support from one that does not contain the answer.
In practice the model then replies that the knowledge base does not cover it.

## Without an API key

Retrieval still runs, and the top passage is returned **verbatim with its
citation** rather than paraphrased. There is no model to summarise with, and a
paraphrase written by no one is exactly the unattributable claim the rules
forbid. If nothing is retrieved, a short hand-written glossary answers the
common concept questions.

## Configuration

| Setting | Default | Meaning |
|---------|---------|---------|
| `RAG_ENABLED` | `true` | Turn retrieval off entirely |
| `RAG_USE_EMBEDDINGS` | `false` | Dense retrieval instead of TF-IDF |
| `RAG_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `RAG_TOP_K` | `4` | Passages retrieved per question |

## Citations

`chat()` returns a `citations` list, rendered under each answer in the UI. A
citation names the file and section a passage came from, so any claim can be
traced to its source text.
