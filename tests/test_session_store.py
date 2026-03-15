"""Tests for session_store module."""

from pathlib import Path

from clawcoco.session_store import SessionStore


class TestSessionStore:
    """Tests for SessionStore class."""

    def test_set_and_get_session(self, session_store: SessionStore) -> None:
        """Should store and retrieve session ID."""
        assert session_store.get_session_id("repo", 1) is None
        session_store.set_session_id("repo", 1, "session-123")
        assert session_store.get_session_id("repo", 1) == "session-123"

    def test_persistence(self, temp_session_db: Path) -> None:
        """Should persist across instances."""
        SessionStore(temp_session_db).set_session_id("repo", 1, "session-123")
        assert SessionStore(temp_session_db).get_session_id("repo", 1) == "session-123"
