"""
Unit tests for VectorStore client resolution and multi-container configuration:
  - Remote HTTP client initialization via QDRANT_URL
  - Embedded client fallback via QDRANT_PATH
  - Singleton caching behavior
  - Clean client teardown via reset_qdrant_client
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from backend.db.vector_store import get_qdrant_client, reset_qdrant_client


@pytest.fixture(autouse=True)
def cleanup_qdrant_client():
    """Ensure client singleton is reset before and after each test."""
    reset_qdrant_client()
    yield
    reset_qdrant_client()


def test_get_qdrant_client_remote_url():
    """When QDRANT_URL is set, QdrantClient should connect over HTTP."""
    with patch.dict(os.environ, {"QDRANT_URL": "http://qdrant:6333"}, clear=False), \
         patch("backend.db.vector_store.QdrantClient") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        client = get_qdrant_client()
        mock_client_cls.assert_called_once_with(url="http://qdrant:6333")
        assert client is mock_instance


def test_get_qdrant_client_local_path():
    """When QDRANT_URL is unset, QdrantClient should use embedded disk mode."""
    env = dict(os.environ)
    env.pop("QDRANT_URL", None)
    env["QDRANT_PATH"] = "./test_embedded_qdrant"

    with patch.dict(os.environ, env, clear=True), \
         patch("backend.db.vector_store.QdrantClient") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        client = get_qdrant_client()
        mock_client_cls.assert_called_once_with(path="./test_embedded_qdrant")
        assert client is mock_instance


def test_get_qdrant_client_singleton():
    """Subsequent calls should return the cached singleton instance."""
    with patch.dict(os.environ, {"QDRANT_URL": "http://qdrant:6333"}, clear=False), \
         patch("backend.db.vector_store.QdrantClient") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        c1 = get_qdrant_client()
        c2 = get_qdrant_client()
        assert c1 is c2
        assert mock_client_cls.call_count == 1


def test_reset_qdrant_client_closes_instance():
    """reset_qdrant_client should call close() and allow re-initialization."""
    with patch.dict(os.environ, {"QDRANT_URL": "http://qdrant:6333"}, clear=False), \
         patch("backend.db.vector_store.QdrantClient") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        get_qdrant_client()
        reset_qdrant_client()
        mock_instance.close.assert_called_once()

        # Re-initialize should create a fresh client
        get_qdrant_client()
        assert mock_client_cls.call_count == 2
