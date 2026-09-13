"""GitHub API client for ReviewMate AI.

Handles pull request URL parsing, metadata fetching, file diffs retrieval,
and posting review comments with robust error handling and strict security.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
import httpx

from app.config import settings


# Regex to parse GitHub Pull Request URLs
# Supports:
# https://github.com/owner/repo/pull/123
# http://github.com/owner/repo/pull/123/
# https://github.com/owner/repo/pull/123/files
# github.com/owner/repo/pull/123
_PR_URL_REGEX = re.compile(
    r"(?:https?:\/\/)?(?:www\.)?github\.com\/([a-zA-Z0-9_\-\.]+)\/([a-zA-Z0-9_\-\.]+)\/pull\/([0-9]+)(?:\/.*)?$",
    re.IGNORECASE,
)


def parse_pr_url(pr_url: str) -> Tuple[str, str, int]:
    """Parse a GitHub Pull Request URL into (owner, repo, pr_number).

    Raises:
        ValueError: If the URL is not a valid GitHub PR URL.
    """
    if not pr_url or not isinstance(pr_url, str):
        raise ValueError("Pull Request URL must be a non-empty string.")

    cleaned_url = pr_url.strip()
    match = _PR_URL_REGEX.match(cleaned_url)
    if not match:
        raise ValueError(
            "Invalid GitHub Pull Request URL. Expected format: "
            "https://github.com/<owner>/<repo>/pull/<number>"
        )

    owner, repo, pr_num_str = match.groups()
    return owner, repo, int(pr_num_str)


def _get_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Build request headers for GitHub API."""
    tok = token.strip() if token else settings.github_token
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ReviewMate-AI/1.0",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def _handle_github_error(response: httpx.Response, action_description: str) -> None:
    """Format and raise actionable, secret-safe errors for GitHub API responses."""
    status = response.status_code
    if status == 404:
        raise ValueError(
            f"GitHub resource not found while {action_description}. "
            "Please check that the repository and PR exist and are publicly accessible (or provide a GITHUB_TOKEN with repo access)."
        )
    elif status == 403:
        rate_limit_remaining = response.headers.get("x-ratelimit-remaining")
        if rate_limit_remaining == "0":
            raise PermissionError(
                "GitHub API rate limit exceeded. Please configure a GITHUB_TOKEN in your .env file to get 5,000 requests/hour."
            )
        raise PermissionError(
            f"GitHub permission denied while {action_description}. Please ensure your GITHUB_TOKEN has appropriate permissions."
        )
    elif status == 401:
        raise PermissionError(
            "GitHub authentication failed. The provided GITHUB_TOKEN is invalid or expired."
        )
    elif status >= 500:
        raise RuntimeError(
            f"GitHub API service error ({status}) while {action_description}. Please try again later."
        )
    else:
        raise RuntimeError(
            f"GitHub API request failed ({status}) while {action_description}: {response.text[:200]}"
        )


async def fetch_pr_metadata(
    owner: str,
    repo: str,
    pr_number: int,
    token: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Fetch pull request metadata from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = _get_headers(token)

    async def _do_fetch(c: httpx.AsyncClient) -> Dict[str, Any]:
        resp = await c.get(url, headers=headers, timeout=15.0)
        if resp.status_code != 200:
            _handle_github_error(resp, f"fetching PR metadata for {owner}/{repo}#{pr_number}")
        data = resp.json()
        return {
            "owner": owner,
            "repo": f"{owner}/{repo}",
            "pr_number": pr_number,
            "title": data.get("title", ""),
            "author": data.get("user", {}).get("login", "unknown"),
            "state": data.get("state", "open"),
            "body": data.get("body") or "",
            "created_at": data.get("created_at", ""),
            "html_url": data.get("html_url", ""),
            "diff_url": data.get("diff_url", ""),
            "base_ref": data.get("base", {}).get("ref", ""),
            "head_ref": data.get("head", {}).get("ref", ""),
            "head_sha": data.get("head", {}).get("sha", ""),
        }

    if client:
        return await _do_fetch(client)
    async with httpx.AsyncClient() as c:
        return await _do_fetch(c)


async def fetch_pr_files(
    owner: str,
    repo: str,
    pr_number: int,
    token: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """Fetch changed files and their diff patches for a pull request."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    headers = _get_headers(token)
    params = {"per_page": 100}

    async def _do_fetch(c: httpx.AsyncClient) -> List[Dict[str, Any]]:
        resp = await c.get(url, headers=headers, params=params, timeout=20.0)
        if resp.status_code != 200:
            _handle_github_error(resp, f"fetching changed files for {owner}/{repo}#{pr_number}")
        files_data = resp.json()
        results = []
        for item in files_data:
            results.append({
                "filename": item.get("filename", ""),
                "status": item.get("status", "modified"),
                "additions": item.get("additions", 0),
                "deletions": item.get("deletions", 0),
                "changes": item.get("changes", 0),
                "patch": item.get("patch", ""),
                "raw_url": item.get("raw_url", ""),
            })
        return results

    if client:
        return await _do_fetch(client)
    async with httpx.AsyncClient() as c:
        return await _do_fetch(c)


async def post_summary_comment(
    owner: str,
    repo: str,
    pr_number: int,
    summary_markdown: str,
    token: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Post a generated review markdown summary to the GitHub PR comment thread.

    Returns:
        The html_url of the created comment on GitHub.

    Raises:
        ValueError: If no GitHub token is provided or summary is empty.
        PermissionError / RuntimeError: If GitHub returns an error.
    """
    tok = token.strip() if token is not None else settings.github_token
    if not tok:
        raise ValueError(
            "GitHub token is required to post a review comment. "
            "Please configure GITHUB_TOKEN in your .env file or enter a Personal Access Token."
        )

    if not summary_markdown or not summary_markdown.strip():
        raise ValueError("Cannot post an empty review summary comment.")

    # In GitHub API, PR comments are posted to the issues endpoint
    # clean repo string if passed as 'owner/repo'
    clean_repo = repo.split("/")[-1]
    url = f"https://api.github.com/repos/{owner}/{clean_repo}/issues/{pr_number}/comments"
    headers = _get_headers(tok)
    payload = {"body": summary_markdown}

    async def _do_post(c: httpx.AsyncClient) -> str:
        resp = await c.post(url, headers=headers, json=payload, timeout=20.0)
        if resp.status_code not in (200, 201):
            _handle_github_error(resp, f"posting review comment to {owner}/{clean_repo}#{pr_number}")
        data = resp.json()
        comment_url = data.get("html_url", "")
        if not comment_url:
            raise RuntimeError("GitHub accepted the comment but did not return a valid comment URL.")
        return comment_url

    if client:
        return await _do_post(client)
    async with httpx.AsyncClient() as c:
        return await _do_post(c)
