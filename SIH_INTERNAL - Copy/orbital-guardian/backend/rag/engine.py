"""
RAG Engine module for Orbital Guardian.

Provides document ingestion, chunking, embeddings, and query retrieval interface.
"""

import hashlib
import re
from typing import List, Dict, Any, Optional

from backend.rag.retriever import retrieve, _load, _corpus


class RAGEngine:
    """
    RAG Engine wrapping retrieval, document chunking, embedding generation,
    and factual query processing.
    """

    def __init__(self):
        _load()

    def ingest_documents(self) -> bool:
        """
        Ingest and load knowledge base documents into memory.
        Returns True on success.
        """
        try:
            _load()
            return True
        except Exception as e:
            print(f"[RAG Engine] Ingestion error: {e}")
            return False

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """
        Split text into fixed-length chunks with optional overlap.
        Returns a list of strings (enables len() operations).
        """
        if not text:
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= text_len:
                break
            start += max(1, chunk_size - overlap)

        return chunks

    def get_embedding(self, text: str, dimensions: int = 64) -> List[float]:
        """
        Generate a deterministic vector embedding for text.
        Returns a list of floats of length `dimensions`.
        """
        if not text:
            return [0.0] * dimensions

        # Deterministic pseudo-random vector based on sha256 hash seeds
        vector = []
        for i in range(dimensions):
            h = hashlib.sha256(f"{text}:{i}".encode("utf-8")).hexdigest()
            val = (int(h[:8], 16) / 0xFFFFFFFF) * 2.0 - 1.0
            vector.append(round(val, 6))

        return vector

    def query(self, query_text: str, top_k: int = 3) -> str:
        """
        Query the RAG engine for knowledge base excerpts.
        Returns a formatted string summary of top matching results.
        """
        if not query_text or not query_text.strip():
            return "No query provided."

        hits = retrieve(query_text, top_k=top_k)

        if not hits:
            return f"No relevant information found for query: '{query_text}'."

        formatted_hits = []
        for i, hit in enumerate(hits, 1):
            formatted_hits.append(
                f"[{i}] {hit['title']} ({hit['category']})\n{hit['excerpt']}"
            )

        return "\n\n".join(formatted_hits)


__all__ = ["RAGEngine"]
