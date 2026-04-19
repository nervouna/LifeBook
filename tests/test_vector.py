"""Unit tests for vector.py."""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lifebook.vector import VectorIndex, SearchResult


@pytest.fixture
def mock_chromadb():
    """Mock ChromaDB client and collection."""
    with patch("lifebook.vector.chromadb") as mock_chromadb:
        # Mock collection
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_collection.get.return_value = {"ids": [], "metadatas": [], "documents": []}
        mock_collection.query.return_value = {
            "ids": [],
            "distances": [],
            "metadatas": [],
            "documents": [],
        }
        
        # Mock client
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client
        
        # Mock embedding function
        mock_embedding_fn = MagicMock()
        mock_chromadb.EmbeddingFunction = MagicMock()
        mock_chromadb.EmbeddingFunction.return_value = mock_embedding_fn
        
        yield mock_chromadb, mock_client, mock_collection


@pytest.fixture
def mock_sentence_transformers():
    """Mock sentence-transformers."""
    with patch("lifebook.vector.SentenceTransformer") as mock_st:
        mock_model = MagicMock()
        mock_model.encode.return_value = [[0.1, 0.2, 0.3]]
        mock_st.return_value = mock_model
        yield mock_st, mock_model


@pytest.fixture
def vector_index(mock_chromadb, mock_sentence_transformers, tmp_path):
    """Create a VectorIndex with mocked dependencies."""
    with patch("lifebook.vector.chromadb"), patch("lifebook.vector.SentenceTransformer"):
        idx = VectorIndex(tmp_path / "vector_store")
        # Replace the mocked collection with our fixture's mock
        _, _, mock_collection = mock_chromadb
        idx.collection = mock_collection
        return idx


def test_vector_index_init(vector_index):
    """Test VectorIndex initialization."""
    assert vector_index.collection is not None


def test_upsert(vector_index):
    """Test upserting a single document."""
    mock_collection = vector_index.collection
    
    vector_index.upsert(
        doc_id="test_id",
        text="Test document text",
        metadata={"title": "Test", "category": "AI技术"},
    )
    
    # Verify upsert was called with correct arguments
    mock_collection.upsert.assert_called_once()
    call_args = mock_collection.upsert.call_args
    assert call_args.kwargs["ids"] == ["test_id"]
    assert call_args.kwargs["documents"] == ["Test document text"]
    assert call_args.kwargs["metadatas"] == [{"title": "Test", "category": "AI技术"}]


def test_upsert_batch(vector_index):
    """Test batch upsert."""
    mock_collection = vector_index.collection
    
    docs = [
        {
            "id": "id1",
            "text": "Text 1",
            "metadata": {"title": "Doc 1", "category": "开发者工具"},
        },
        {
            "id": "id2", 
            "text": "Text 2",
            "metadata": {"title": "Doc 2", "category": "游戏"},
        },
    ]
    
    vector_index.upsert_batch(docs)
    
    mock_collection.upsert.assert_called_once()
    call_args = mock_collection.upsert.call_args
    assert call_args.kwargs["ids"] == ["id1", "id2"]
    assert call_args.kwargs["documents"] == ["Text 1", "Text 2"]
    assert call_args.kwargs["metadatas"] == [
        {"title": "Doc 1", "category": "开发者工具"},
        {"title": "Doc 2", "category": "游戏"},
    ]


def test_upsert_batch_empty(vector_index):
    """Test batch upsert with empty list."""
    mock_collection = vector_index.collection
    
    vector_index.upsert_batch([])
    
    # Should not call upsert on empty list
    mock_collection.upsert.assert_not_called()


def test_delete(vector_index):
    """Test deleting a document."""
    mock_collection = vector_index.collection
    
    vector_index.delete("test_id")
    
    mock_collection.delete.assert_called_once_with(ids=["test_id"])


def test_delete_nonexistent(vector_index):
    """Test deleting a nonexistent document (should still call delete)."""
    mock_collection = vector_index.collection
    
    vector_index.delete("nonexistent")
    
    mock_collection.delete.assert_called_once_with(ids=["nonexistent"])


def test_search(vector_index):
    """Test semantic search."""
    mock_collection = vector_index.collection
    
    # Mock query response
    mock_collection.query.return_value = {
        "ids": [["id1", "id2"]],
        "distances": [[0.1, 0.5]],
        "metadatas": [[
            {"title": "Doc 1", "category": "AI技术"},
            {"title": "Doc 2", "category": "开发者工具"},
        ]],
        "documents": [["Text 1", "Text 2"]],
    }
    
    results = vector_index.search("test query", n_results=2)
    
    # Verify query was called
    mock_collection.query.assert_called_once()
    call_args = mock_collection.query.call_args
    assert call_args.kwargs["n_results"] == 2
    
    # Verify results
    assert len(results) == 2
    assert results[0].doc_id == "id1"
    assert results[0].distance == 0.1
    assert results[0].metadata == {"title": "Doc 1", "category": "AI技术"}
    assert results[0].text == "Text 1"
    
    assert results[1].doc_id == "id2"
    assert results[1].distance == 0.5
    assert results[1].metadata == {"title": "Doc 2", "category": "开发者工具"}
    assert results[1].text == "Text 2"


def test_search_with_where(vector_index):
    """Test search with metadata filtering."""
    mock_collection = vector_index.collection
    
    vector_index.search("query", where={"category": "AI技术"})
    
    mock_collection.query.assert_called_once()
    call_args = mock_collection.query.call_args
    assert call_args.kwargs["where"] == {"category": "AI技术"}


def test_search_empty_index(vector_index):
    """Test search when index is empty."""
    mock_collection = vector_index.collection
    
    # Mock empty response
    mock_collection.query.return_value = {
        "ids": [],
        "distances": [],
        "metadatas": [],
        "documents": [],
    }
    
    results = vector_index.search("query")
    
    assert results == []


def test_count(vector_index):
    """Test counting documents."""
    mock_collection = vector_index.collection
    mock_collection.count.return_value = 42
    
    assert vector_index.count() == 42
    mock_collection.count.assert_called_once()


def test_has(vector_index):
    """Test checking if document exists."""
    mock_collection = vector_index.collection
    
    # Test existing
    mock_collection.get.return_value = {"ids": ["existing_id"], "metadatas": [{}], "documents": [""]}
    assert vector_index.has("existing_id") is True
    
    # Test nonexistent
    mock_collection.get.return_value = {"ids": [], "metadatas": [], "documents": []}
    assert vector_index.has("nonexistent_id") is False


def test_search_result_dataclass():
    """Test SearchResult dataclass."""
    result = SearchResult(
        doc_id="test_id",
        distance=0.3,
        metadata={"title": "Test"},
        text="Test text",
    )
    
    # Test asdict serialization
    d = asdict(result)
    assert d == {
        "doc_id": "test_id",
        "distance": 0.3,
        "metadata": {"title": "Test"},
        "text": "Test text",
    }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
