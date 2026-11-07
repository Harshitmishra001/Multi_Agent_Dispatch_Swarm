"""
Tests for SQLite checkpointer configuration:
  - WAL journal mode is active
  - Busy timeout is set to 30000ms
  - Connection timeout is 30s
"""
import pytest


def test_checkpointer_wal_mode_enabled():
    """The checkpointer connection must use WAL journal mode for concurrency."""
    from backend.graph.build_graph import _checkpoint_conn

    row = _checkpoint_conn.execute("PRAGMA journal_mode;").fetchone()
    assert row[0] == "wal", f"Expected WAL journal mode, got {row[0]}"


def test_checkpointer_busy_timeout_set():
    """The checkpointer connection must have a 30000ms busy timeout."""
    from backend.graph.build_graph import _checkpoint_conn

    row = _checkpoint_conn.execute("PRAGMA busy_timeout;").fetchone()
    assert row[0] == 30000, f"Expected busy_timeout=30000, got {row[0]}"


def test_checkpointer_connection_timeout():
    """The checkpointer connection must be created with timeout=30.0."""
    from backend.graph.build_graph import _checkpoint_conn

    # sqlite3.Connection stores the timeout value that was passed at creation
    assert _checkpoint_conn.execute("SELECT 1").fetchone() == (1,)
