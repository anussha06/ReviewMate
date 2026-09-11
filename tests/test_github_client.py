"""Tests for GitHub API client."""

import pytest
import httpx
from app.github_client import (
    parse_pr_url,
    fetch_pr_metadata,
    fetch_pr_files,
    post_summary_comment,
)


def test_parse_pr_url_valid():
    cases = [
        ("https://github.com/facebook/react/pull/28000", ("facebook", "react", 28000)),
        ("http://github.com/torvalds/linux/pull/1234/", ("torvalds", "linux", 1234)),
        ("https://github.com/pallets/flask/pull/500/files", ("pallets", "flask", 500)),
        ("github.com/django/django/pull/9999", ("django", "django", 9999)),
        ("https://www.github.com/rust-lang/rust/pull/42", ("rust-lang", "rust", 42)),
    ]
    for url, expected in cases:
        assert parse_pr_url(url) == expected


def test_parse_pr_url_invalid():
    invalid_cases = [
        "",
        "https://google.com",
        "https://github.com/facebook/react",
        "https://github.com/facebook/react/issues/123",
        "not-a-url",
        None,
    ]
    for inv in invalid_cases:
        with pytest.raises(ValueError):
            parse_pr_url(inv)


@pytest.mark.asyncio
async def test_fetch_pr_metadata_mocked():
    mock_data = {
        "title": "Add feature X",
        "user": {"login": "dev_user"},
        "state": "open",
        "body": "Resolves issue #1",
        "created_at": "2026-01-01T00:00:00Z",
        "html_url": "https://github.com/owner/repo/pull/10",
        "diff_url": "https://github.com/owner/repo/pull/10.diff",
        "base": {"ref": "main"},
        "head": {"ref": "feature-x", "sha": "abc1234"},
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/owner/repo/pulls/10"
        return httpx.Response(200, json=mock_data)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        meta = await fetch_pr_metadata("owner", "repo", 10, client=client)

    assert meta["title"] == "Add feature X"
    assert meta["author"] == "dev_user"
    assert meta["pr_number"] == 10
    assert meta["repo"] == "owner/repo"


@pytest.mark.asyncio
async def test_fetch_pr_files_mocked():
    mock_files = [
        {
            "filename": "src/main.py",
            "status": "modified",
            "additions": 5,
            "deletions": 1,
            "changes": 6,
            "patch": "+print('hello')",
            "raw_url": "https://github.com/raw/1",
        }
    ]

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/owner/repo/pulls/10/files"
        return httpx.Response(200, json=mock_files)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        files = await fetch_pr_files("owner", "repo", 10, client=client)

    assert len(files) == 1
    assert files[0]["filename"] == "src/main.py"
    assert files[0]["additions"] == 5


@pytest.mark.asyncio
async def test_post_summary_comment_success():
    expected_url = "https://github.com/owner/repo/issues/comments/12345678"

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/owner/repo/issues/10/comments"
        assert "Authorization" in request.headers
        assert request.headers["Authorization"] == "Bearer test_token"
        return httpx.Response(201, json={"html_url": expected_url})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        comment_url = await post_summary_comment(
            owner="owner",
            repo="repo",
            pr_number=10,
            summary_markdown="# Review",
            token="test_token",
            client=client,
        )

    assert comment_url == expected_url


@pytest.mark.asyncio
async def test_post_summary_comment_missing_token():
    with pytest.raises(ValueError, match="GitHub token is required"):
        await post_summary_comment(
            owner="owner",
            repo="repo",
            pr_number=10,
            summary_markdown="# Review",
            token="",
        )


@pytest.mark.asyncio
async def test_post_summary_comment_github_error():
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource not accessible by integration"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(PermissionError, match="GitHub permission denied"):
            await post_summary_comment(
                owner="owner",
                repo="repo",
                pr_number=10,
                summary_markdown="# Review",
                token="bad_token",
                client=client,
            )
