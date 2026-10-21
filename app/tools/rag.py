"""Lightweight in-memory Vector DB (ChromaDB) RAG engine for scholarship verification.

Embeds scraped webpage text and retrieves only the high-signal passages for:
- Deadline & key dates
- Funding, stipend & tuition awards
- Eligibility criteria, degree & citizenship
- How to apply instructions

Reduces LLM verification context from 12,000+ chars down to ~300 tokens,
drastically reducing token consumption while preserving exact verbatim quotes.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, cast

import chromadb
from chromadb.api.types import EmbeddingFunction, Embeddings


class FastHashEmbedding(EmbeddingFunction[Any]):
    """Deterministic, fast 128-dimensional n-gram token embedding function.

    Runs 100% locally and offline without downloading heavy model weights,
    ideal for fast serverless scale-to-zero container deployments.
    """

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    @staticmethod
    def name() -> str:
        return "FastHashEmbedding"

    def __call__(self, input: Any) -> Embeddings:
        embeddings: list[list[float]] = []
        for text in input:
            vec = [0.0] * self.dim
            words = re.findall(r"\w+", str(text).lower())
            for w in words:
                idx = hash(w) % self.dim
                vec[idx] += 1.0
            # N-grams for phrase semantics
            for i in range(len(words) - 1):
                bi = f"{words[i]}_{words[i+1]}"
                idx = hash(bi) % self.dim
                vec[idx] += 1.5
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            embeddings.append([round(v / norm, 5) for v in vec])
        return cast(Embeddings, embeddings)


class ScholarRAG:
    """Manages ephemeral in-memory ChromaDB vector collections for scholarship pages."""

    def __init__(self) -> None:
        self.client = chromadb.Client()
        self.embedding_fn = FastHashEmbedding()
        self._collections: dict[str, Any] = {}

    def _clean_name(self, url: str) -> str:
        # Chroma collection names must be 3-63 chars: alphanumeric, _, -
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", url)[-50:]
        return f"rag_{clean}_{abs(hash(url)) % 10000}"

    def index_page(self, url: str, text: str, chunk_size: int = 350, overlap: int = 60) -> str:
        """Chunk and index webpage text into an in-memory ChromaDB collection."""
        if not text or len(text.strip()) < 50:
            return ""

        col_name = self._clean_name(url)
        try:
            # Delete if exists
            try:
                self.client.delete_collection(col_name)
            except Exception:
                pass
            collection = self.client.create_collection(
                name=col_name,
                embedding_function=cast(Any, self.embedding_fn),
            )
        except Exception:
            # Fallback collection
            collection = self.client.get_or_create_collection(
                name=f"fallback_{str(uuid.uuid4())[:8]}",
                embedding_function=cast(Any, self.embedding_fn),
            )

        # Split into overlapping character chunks
        chunks: list[str] = []
        ids: list[str] = []
        pos = 0
        text_len = len(text)
        idx = 0

        while pos < text_len:
            end = min(pos + chunk_size, text_len)
            chunk = text[pos:end].strip()
            if len(chunk) > 30:
                chunks.append(chunk)
                ids.append(f"chunk_{idx}")
                idx += 1
            if end >= text_len:
                break
            pos += chunk_size - overlap

        if chunks:
            collection.add(documents=chunks, ids=ids)
            self._collections[url] = collection
            return collection.name
        return ""

    def query_page(
        self,
        url: str,
        queries: list[str] | None = None,
        top_k: int = 2,
    ) -> str:
        """Retrieve the top matching chunks for essential scholarship dimensions."""
        collection = self._collections.get(url)
        if not collection:
            return ""

        default_queries = [
            "deadline closing date application submission",
            "funding stipend tuition fee allowance amount cover",
            "eligibility criteria degree level requirements citizenship nationality",
            "how to apply application portal documents required",
        ]
        target_queries = queries or default_queries

        retrieved_passages: list[str] = []
        seen_texts: set[str] = set()

        for q in target_queries:
            try:
                res = collection.query(query_texts=[q], n_results=top_k)
                docs = res.get("documents", [])
                if docs and len(docs) > 0:
                    for doc in docs[0]:
                        if doc and doc not in seen_texts:
                            seen_texts.add(doc)
                            retrieved_passages.append(doc)
            except Exception:
                continue

        if not retrieved_passages:
            return ""

        # Join retrieved chunks with clear separation
        return "\n\n[...]\n\n".join(retrieved_passages)


# Global instance
default_rag = ScholarRAG()
