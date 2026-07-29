"""Knowledge corpus for the assistant's retrieval.

Documents live in `docs/kb/` as markdown and are split on headings, so every
chunk keeps the section title it came from and can be cited as
``file.md > Section``. Citation is the point: the assistant is instructed never
to state a figure or claim it cannot attribute, and a chunk without a traceable
source cannot be attributed.

Portfolio facts are *not* stored here. They are per-session, change constantly,
and carry provenance that must travel with them, so they are injected as
context at query time instead.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from config.settings import PROJECT_ROOT
from utils.logging_config import get_logger

logger = get_logger(__name__)

KB_DIR = Path(PROJECT_ROOT) / "docs" / "kb"

# Chunks shorter than this carry no usable signal (a stray heading, a one-line
# stub) and only add noise to retrieval.
MIN_CHUNK_CHARS = 120
# Long sections are split so a match returns the relevant part, not a wall.
MAX_CHUNK_CHARS = 1400


@dataclass(frozen=True)
class Document:
    """One retrievable passage with everything needed to cite it."""

    doc_id: str
    source: str  # file name
    section: str  # heading path
    text: str

    @property
    def citation(self) -> str:
        return f"{self.source} > {self.section}" if self.section else self.source

    def to_dict(self) -> dict[str, str]:
        return {
            "doc_id": self.doc_id,
            "source": self.source,
            "section": self.section,
            "citation": self.citation,
            "text": self.text,
        }


def _split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Break an over-long section on paragraph boundaries."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buffer = ""
    for para in text.split("\n\n"):
        if buffer and len(buffer) + len(para) + 2 > limit:
            parts.append(buffer.strip())
            buffer = para
        else:
            buffer = f"{buffer}\n\n{para}" if buffer else para
    if buffer.strip():
        parts.append(buffer.strip())
    return parts


def chunk_markdown(text: str, source: str) -> list[Document]:
    """Split a markdown file into one document per heading section."""
    lines = text.splitlines()
    title = ""
    section = ""
    buffer: list[str] = []
    out: list[Document] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if not body or len(body) < MIN_CHUNK_CHARS:
            return
        heading = section or title
        for i, piece in enumerate(_split_long(body)):
            raw = f"{source}:{heading}:{i}:{piece[:64]}"
            out.append(
                Document(
                    doc_id=hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16],
                    source=source,
                    section=heading,
                    # Prefix the heading so the retrieval signal includes it.
                    text=f"{heading}\n\n{piece}" if heading else piece,
                )
            )

    for line in lines:
        h1 = re.match(r"^#\s+(.*)", line)
        h2 = re.match(r"^##\s+(.*)", line)
        if h1:
            flush()
            buffer = []
            title = h1.group(1).strip()
            section = ""
            continue
        if h2:
            flush()
            buffer = []
            section = h2.group(1).strip()
            continue
        buffer.append(line)
    flush()
    return out


def load_corpus(kb_dir: Optional[Path] = None) -> list[Document]:
    """Every chunk from every markdown file in the knowledge base."""
    directory = Path(kb_dir or KB_DIR)
    if not directory.exists():
        logger.warning("Knowledge base directory missing: {}", directory)
        return []

    docs: list[Document] = []
    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not read {}: {}", path, exc)
            continue
        docs.extend(chunk_markdown(text, path.name))

    logger.info("Knowledge base: {} chunks from {}", len(docs), directory)
    return docs


def corpus_fingerprint(docs: Iterable[Document]) -> str:
    """Stable id for a corpus, so a cached index can be invalidated."""
    joined = "|".join(sorted(d.doc_id for d in docs))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
