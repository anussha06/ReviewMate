"""Tests for SQLite review store."""

import pytest
from app.db.models import ReviewRecord, Finding, AgentStatus
from app.db.review_store import (
    save_review,
    get_recent_reviews,
    get_review_by_id,
    update_comment_url,
)


def test_review_store_lifecycle(tmp_path):
    db_file = str(tmp_path / "test_reviewmate.db")

    finding = Finding(
        agent="security",
        category="Security",
        severity="HIGH",
        confidence="HIGH",
        file="app/main.py",
        line=12,
        title="Potential SQL Injection",
        description="Raw SQL query format used",
        recommendation="Use parameterized queries",
    )

    agent_status = AgentStatus(
        agent="security",
        status="completed",
        findings_count=1,
    )

    record = ReviewRecord(
        pr_url="https://github.com/test/repo/pull/1",
        repo="test/repo",
        pr_number=1,
        pr_title="Fix login vulnerability",
        pr_author="octocat",
        recommendation="REQUEST_CHANGES",
        context_summary={"files_included": ["app/main.py"], "estimated_tokens": 300},
        agent_statuses={"security": agent_status},
        findings=[finding],
        summary_markdown="# Review Summary",
    )

    # Save
    review_id = save_review(record, db_path=db_file)
    assert review_id > 0

    # Retrieve by ID
    loaded = get_review_by_id(review_id, db_path=db_file)
    assert loaded is not None
    assert loaded.pr_title == "Fix login vulnerability"
    assert loaded.recommendation == "REQUEST_CHANGES"
    assert len(loaded.findings) == 1
    assert loaded.findings[0].title == "Potential SQL Injection"
    assert loaded.agent_statuses["security"].findings_count == 1

    # Update comment URL
    updated = update_comment_url(review_id, "https://github.com/comment/123", db_path=db_file)
    assert updated is True

    loaded_after = get_review_by_id(review_id, db_path=db_file)
    assert loaded_after.github_comment_url == "https://github.com/comment/123"

    # Retrieve recent
    recent = get_recent_reviews(limit=10, db_path=db_file)
    assert len(recent) == 1
    assert recent[0].id == review_id
