"""End-to-end pipeline tests for ReviewMate AI FastAPI application."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app
from app.config import settings
from app.db.models import Finding


@pytest.fixture
def client(tmp_path):
    test_db = str(tmp_path / "e2e_test.db")
    with patch.object(settings, "db_path", test_db):
        yield TestClient(app)


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "ReviewMate AI"
    assert "configuration" in data


def test_analyze_invalid_url(client):
    response = client.post("/api/analyze", json={"pr_url": "https://not-github.com/foo/bar"})
    assert response.status_code == 400
    assert "Invalid GitHub Pull Request URL" in response.json()["detail"]


def test_analyze_missing_groq_key(client):
    # Mock github fetch to succeed so it reaches groq key check
    with patch("app.main.fetch_pr_metadata", new_callable=AsyncMock) as mock_meta, \
         patch("app.main.fetch_pr_files", new_callable=AsyncMock) as mock_files, \
         patch.object(settings, "groq_api_key", ""):
        mock_meta.return_value = {"title": "Test PR", "author": "dev", "repo": "owner/repo", "pr_number": 1}
        mock_files.return_value = [{"filename": "main.py", "status": "modified", "patch": "+print(1)"}]

        response = client.post("/api/analyze", json={"pr_url": "https://github.com/owner/repo/pull/1"})
        assert response.status_code == 400
        assert "GROQ_API_KEY is not configured" in response.json()["detail"]


def test_analyze_full_pipeline_mocked(client):
    mock_meta = {
        "repo": "facebook/react",
        "pr_number": 12345,
        "title": "Fix memory leak in useEffect",
        "author": "react_dev",
        "state": "open",
        "body": "Fixes unmounted event listener",
    }
    mock_files = [
        {
            "filename": "packages/react/src/ReactHooks.js",
            "status": "modified",
            "additions": 10,
            "deletions": 2,
            "patch": "+import { cleanup } from './utils';\n+// fixes memory leak\n",
        }
    ]

    mock_finding = Finding(
        agent="performance",
        category="Performance",
        severity="MEDIUM",
        confidence="HIGH",
        file="packages/react/src/ReactHooks.js",
        line=12,
        title="Potential lingering event listener",
        description="Cleanup function should be verified against edge-case unmounts.",
        recommendation="Ensure cleanup returns a void function.",
    )

    with patch("app.main.fetch_pr_metadata", new_callable=AsyncMock) as p_meta, \
         patch("app.main.fetch_pr_files", new_callable=AsyncMock) as p_files, \
         patch.object(settings, "groq_api_key", "gsk_dummy_test_key_1234567890"), \
         patch("app.orchestrator.Orchestrator.run_review", new_callable=AsyncMock) as p_run:

        p_meta.return_value = mock_meta
        p_files.return_value = mock_files

        # Mock review return
        from app.db.models import ReviewRecord, AgentStatus
        fake_record = ReviewRecord(
            pr_url="https://github.com/facebook/react/pull/12345",
            repo="facebook/react",
            pr_number=12345,
            pr_title="Fix memory leak in useEffect",
            pr_author="react_dev",
            recommendation="COMMENT",
            context_summary={"files_included": ["packages/react/src/ReactHooks.js"], "estimated_tokens": 150},
            agent_statuses={"performance": AgentStatus(agent="performance", status="completed", findings_count=1)},
            findings=[mock_finding],
            summary_markdown="# 🤖 ReviewMate AI Review\n\n## Recommendation\nCOMMENT",
        )
        p_run.return_value = fake_record

        res = client.post("/api/analyze", json={"pr_url": "https://github.com/facebook/react/pull/12345"})
        assert res.status_code == 200
        data = res.json()
        assert data["pr_number"] == 12345
        assert data["recommendation"] == "COMMENT"
        assert len(data["findings"]) == 1
        assert data["id"] is not None

        # Verify it can be retrieved from history
        review_id = data["id"]
        hist_res = client.get(f"/api/history/{review_id}")
        assert hist_res.status_code == 200
        assert hist_res.json()["pr_title"] == "Fix memory leak in useEffect"

        # Verify history list
        list_res = client.get("/api/history")
        assert list_res.status_code == 200
        assert len(list_res.json()) >= 1


def test_post_review_endpoint(client):
    # Case 1: Missing token
    with patch.object(settings, "github_token", ""):
        res_no_tok = client.post(
            "/api/post-review",
            json={
                "owner": "owner",
                "repo": "repo",
                "pr_number": 1,
                "summary_markdown": "Test review",
                "github_token": "",
            },
        )
        assert res_no_tok.status_code == 400
        assert "GitHub token is required" in res_no_tok.json()["detail"]

    # Case 2: Success with mock
    with patch("app.main.post_summary_comment", new_callable=AsyncMock) as p_post:
        p_post.return_value = "https://github.com/owner/repo/issues/comments/999"
        res_success = client.post(
            "/api/post-review",
            json={
                "owner": "owner",
                "repo": "repo",
                "pr_number": 1,
                "summary_markdown": "Test review",
                "github_token": "mock_token_123",
            },
        )
        assert res_success.status_code == 200
        data = res_success.json()
        assert data["success"] is True
        assert data["comment_url"] == "https://github.com/owner/repo/issues/comments/999"


def test_serve_frontend_static_assets(client):
    # Test root returns index.html
    root_res = client.get("/")
    assert root_res.status_code == 200
    assert "ReviewMate AI" in root_res.text
    assert "Agentic GitHub Code Review" in root_res.text

    # Test static style.css
    css_res = client.get("/static/style.css")
    assert css_res.status_code == 200
    assert "--accent" in css_res.text

    # Test static app.js
    js_res = client.get("/static/app.js")
    assert js_res.status_code == 200
    assert "handleAnalyzeSubmit" in js_res.text

