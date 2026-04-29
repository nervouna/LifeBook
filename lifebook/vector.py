"""Vector index for semantic search over topic notes."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    doc_id: str
    distance: float
    metadata: dict[str, Any]
    text: str


class VectorIndex:
    """ChromaDB-backed vector index for topic notes.
    
    Each document is a topic note (from 20-topics/), keyed by its relative path.
    Metadata includes title, category, tags (comma-joined), related_keywords.
    Content indexed is: title + summary + key_points + narrative (concatenated).
    """
    
    def __init__(
        self,
        persist_dir: Path,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    ):
        """Initialize ChromaDB client and embedding model.
        
        Args:
            persist_dir: Directory to store ChromaDB data.
            model_name: SentenceTransformer model name.
        """
        self.persist_dir = persist_dir
        self.model_name = model_name
        self._model = None
        self._model_lock = threading.Lock()

        # Create directory if it doesn't exist
        persist_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="lifebook_topics",
            embedding_function=self._embedding_function(),
        )
        
        logger.info(
            "Vector index initialized at %s (%d documents)",
            persist_dir,
            self.collection.count(),
        )
    
    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    logger.info("Loading embedding model: %s", self.model_name)
                    self._model = SentenceTransformer(self.model_name)
        return self._model

    @model.setter
    def model(self, value):
        self._model = value

    def _embedding_function(self):
        """Create a ChromaDB-compatible embedding function."""
        def embed(texts: list[str]) -> list[list[float]]:
            """Embed a list of texts."""
            if not texts:
                return []
            embeddings = self.model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            # Convert to list of lists for ChromaDB
            return [emb.tolist() for emb in embeddings]
        
        return embed
    
    def upsert(self, doc_id: str, text: str, metadata: dict[str, str | int | float]) -> None:
        """Add or update a single document.
        
        Args:
            doc_id: Unique document identifier (e.g., relative path).
            text: Document content to embed.
            metadata: Document metadata (must be JSON-serializable).
        """
        self.collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata],
        )
        logger.debug("Upserted document: %s", doc_id)
    
    def upsert_batch(self, docs: list[dict]) -> None:
        """Batch upsert documents.
        
        Args:
            docs: List of dicts, each with keys: id, text, metadata.
        """
        if not docs:
            return
        
        ids = [d["id"] for d in docs]
        texts = [d["text"] for d in docs]
        metadatas = [d["metadata"] for d in docs]
        
        self.collection.upsert(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
        )
        logger.debug("Batch upserted %d documents", len(docs))
    
    def delete(self, doc_id: str) -> None:
        """Remove a document by ID.
        
        Args:
            doc_id: Document identifier to delete.
        """
        self.collection.delete(ids=[doc_id])
        logger.debug("Deleted document: %s", doc_id)
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Perform semantic search.
        
        Args:
            query: Search query text.
            n_results: Maximum number of results to return.
            where: Optional metadata filter (e.g., {"category": "AI技术"}).
        
        Returns:
            List of SearchResult objects, sorted by distance (ascending).
        """
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
                include=["metadatas", "documents", "distances"],
            )
        except Exception as e:
            logger.warning("Search failed: %s", e)
            return []
        
        # Handle empty results
        if not results["ids"] or not results["ids"][0]:
            return []
        
        # Build SearchResult objects
        search_results = []
        for i, doc_id in enumerate(results["ids"][0]):
            search_results.append(
                SearchResult(
                    doc_id=doc_id,
                    distance=results["distances"][0][i],
                    metadata=results["metadatas"][0][i] or {},
                    text=results["documents"][0][i],
                )
            )
        
        return search_results
    
    def count(self) -> int:
        """Return number of indexed documents."""
        return self.collection.count()
    
    def has(self, doc_id: str) -> bool:
        """Check if a document ID exists in the index.
        
        Args:
            doc_id: Document identifier to check.
        
        Returns:
            True if document exists, False otherwise.
        """
        result = self.collection.get(ids=[doc_id], include=[])
        return len(result["ids"]) > 0
