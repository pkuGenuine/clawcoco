"""Session ID storage using SQLite with SQLModel."""

from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, create_engine


class SessionRecord(SQLModel, table=True):
    """Session ID record for a repo/issue pair."""

    repo: str = Field(primary_key=True)
    issue: int = Field(primary_key=True)
    session_id: str
    pr_number: int | None = Field(default=None)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionStore:
    """SQLite-backed session ID storage using SQLModel."""

    def __init__(self, db_path: Path) -> None:
        engine = create_engine(f"sqlite:///{db_path}")
        SQLModel.metadata.create_all(engine)
        self._engine = engine

    def get_session_id(self, repo: str, issue: int) -> str | None:
        """Get session ID for a repo/issue pair."""
        with Session(self._engine) as session:
            record = session.get(SessionRecord, (repo, issue))
            return record.session_id if record else None

    def set_session_id(self, repo: str, issue: int, session_id: str) -> None:
        """Set session ID for a repo/issue pair."""
        with Session(self._engine) as session:
            record = session.get(SessionRecord, (repo, issue))
            if record:
                record.session_id = session_id
                record.updated_at = datetime.now(timezone.utc)
            else:
                record = SessionRecord(repo=repo, issue=issue, session_id=session_id)
            session.add(record)
            session.commit()

    def set_pr_number(self, repo: str, issue: int, pr_number: int) -> None:
        """Update PR number for existing session."""
        with Session(self._engine) as session:
            record = session.get(SessionRecord, (repo, issue))
            if record:
                record.pr_number = pr_number
                record.updated_at = datetime.now(timezone.utc)
                session.add(record)
                session.commit()

    def get_pr_number(self, repo: str, issue: int) -> int | None:
        """Get PR number for a repo/issue pair."""
        with Session(self._engine) as session:
            record = session.get(SessionRecord, (repo, issue))
            return record.pr_number if record else None
