"""SQLite storage repository for ReviewMate AI review history."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.db.models import ReviewRecord, Finding, AgentStatus


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create and configure SQLite database connection."""
    target_path = db_path or settings.db_path
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables and indexes."""
    with get_db_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_url TEXT NOT NULL,
                repo TEXT NOT NULL,
                pr_number INTEGER NOT NULL,
                pr_title TEXT NOT NULL,
                pr_author TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                context_summary TEXT NOT NULL,
                agent_statuses TEXT NOT NULL,
                findings TEXT NOT NULL,
                summary_markdown TEXT NOT NULL,
                github_comment_url TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_created ON reviews(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_repo_pr ON reviews(repo, pr_number)")
        conn.commit()


def save_review(record: ReviewRecord, db_path: Optional[str] = None) -> int:
    """Persist a review record to the SQLite database and return its new ID."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO reviews (
                pr_url, repo, pr_number, pr_title, pr_author,
                recommendation, context_summary, agent_statuses,
                findings, summary_markdown, github_comment_url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.pr_url,
                record.repo,
                record.pr_number,
                record.pr_title,
                record.pr_author,
                record.recommendation,
                json.dumps(record.context_summary),
                json.dumps({k: v.model_dump() for k, v in record.agent_statuses.items()}),
                json.dumps([f.model_dump() for f in record.findings]),
                record.summary_markdown,
                record.github_comment_url,
                record.created_at,
            ),
        )
        conn.commit()
        record_id = cursor.lastrowid
        return int(record_id)


def _row_to_record(row: sqlite3.Row) -> ReviewRecord:
    """Convert an SQLite row into a typed ReviewRecord."""
    agent_statuses_raw = json.loads(row["agent_statuses"])
    agent_statuses = {k: AgentStatus(**v) for k, v in agent_statuses_raw.items()}
    findings_raw = json.loads(row["findings"])
    findings = [Finding(**f) for f in findings_raw]

    return ReviewRecord(
        id=row["id"],
        pr_url=row["pr_url"],
        repo=row["repo"],
        pr_number=row["pr_number"],
        pr_title=row["pr_title"],
        pr_author=row["pr_author"],
        recommendation=row["recommendation"],
        context_summary=json.loads(row["context_summary"]),
        agent_statuses=agent_statuses,
        findings=findings,
        summary_markdown=row["summary_markdown"],
        github_comment_url=row["github_comment_url"],
        created_at=row["created_at"],
    )


def get_recent_reviews(limit: int = 20, db_path: Optional[str] = None) -> List[ReviewRecord]:
    """Retrieve recent reviews ordered by created_at descending."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM reviews ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        return [_row_to_record(r) for r in rows]


def get_review_by_id(review_id: int, db_path: Optional[str] = None) -> Optional[ReviewRecord]:
    """Fetch a single review record by ID."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_record(row)


def update_comment_url(review_id: int, comment_url: str, db_path: Optional[str] = None) -> bool:
    """Update the posted GitHub comment URL for a review record."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reviews SET github_comment_url = ? WHERE id = ?",
            (comment_url, review_id),
        )
        conn.commit()
        return cursor.rowcount > 0
