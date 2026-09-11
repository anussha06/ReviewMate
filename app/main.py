"""FastAPI application for ReviewMate AI.

Serves the agentic review API endpoints and static frontend UI.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.context_manager import build_bounded_context
from app.db.models import AnalyzeRequest, PostReviewRequest, ReviewRecord, Finding, AgentStatus
from app.db.review_store import (
    init_db,
    save_review,
    get_recent_reviews,
    get_review_by_id,
    update_comment_url,
)
from app.github_client import (
    parse_pr_url,
    fetch_pr_metadata,
    fetch_pr_files,
    post_summary_comment,
)
from app.llm_client import LLMClient
from app.orchestrator import Orchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("reviewmate.api")

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on application startup."""
    init_db()
    logger.info("ReviewMate AI initialized with database at %s", settings.db_path)
    yield


app = FastAPI(
    title="ReviewMate AI",
    description="Agentic GitHub Pull Request Code Review & Repository Analysis System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount static assets directory
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
async def serve_index() -> FileResponse:
    """Serve the single-page frontend application."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Frontend index.html file is not found.",
        )
    return FileResponse(str(index_path))


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """Health check and sanitized environment readiness status."""
    return {
        "status": "healthy",
        "service": "ReviewMate AI",
        "version": "1.0.0",
        "configuration": settings.masked_summary(),
        "has_groq_key": settings.has_groq_key,
        "has_github_token": settings.has_github_token,
    }


@app.post("/api/analyze")
async def analyze_pr(req: AnalyzeRequest) -> Dict[str, Any]:
    """Analyze a GitHub pull request using the multi-agent bounded context pipeline."""
    # 1. Validate and parse URL
    try:
        owner, repo, pr_number = parse_pr_url(req.pr_url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 2. Fetch PR Metadata
    token = req.github_token or settings.github_token
    try:
        pr_metadata = await fetch_pr_metadata(owner, repo, pr_number, token=token)
    except (ValueError, PermissionError, RuntimeError) as e:
        logger.error(f"GitHub metadata error: {e}")
        status_code = status.HTTP_404_NOT_FOUND if "not found" in str(e).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error fetching PR metadata: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve pull request metadata from GitHub.")

    # 3. Fetch changed files and diffs
    try:
        pr_files = await fetch_pr_files(owner, repo, pr_number, token=token)
    except (ValueError, PermissionError, RuntimeError) as e:
        logger.error(f"GitHub diff fetch error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error fetching PR files: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve changed files from GitHub.")

    # Handle empty pull request diff
    if not pr_files:
        empty_record = ReviewRecord(
            pr_url=req.pr_url,
            repo=f"{owner}/{repo}",
            pr_number=pr_number,
            pr_title=pr_metadata.get("title", ""),
            pr_author=pr_metadata.get("author", "unknown"),
            recommendation="APPROVE",
            context_summary={"files_included": [], "estimated_tokens": 0, "notice": "No changed files or diffs found in this pull request."},
            agent_statuses={
                "bug": AgentStatus(agent="bug", status="completed", findings_count=0),
                "security": AgentStatus(agent="security", status="completed", findings_count=0),
                "quality": AgentStatus(agent="quality", status="completed", findings_count=0),
                "performance": AgentStatus(agent="performance", status="completed", findings_count=0),
            },
            findings=[],
            summary_markdown=(
                f"# 🤖 ReviewMate AI Review\n\n"
                f"## Pull Request #{pr_number} ({owner}/{repo})\n\n"
                f"**Notice:** No changed files or diffs were detected in this pull request. Nothing to review.\n\n"
                f"## Final Recommendation\n✅ **APPROVE**"
            ),
        )
        saved_id = save_review(empty_record)
        empty_record.id = saved_id
        return empty_record.model_dump()

    # 4. Build bounded context with secret redaction
    known_secrets = [tok for tok in [token, settings.groq_api_key] if tok]
    context = build_bounded_context(
        pr_metadata=pr_metadata,
        pr_files=pr_files,
        context_limit=settings.context_token_limit,
        known_secrets=known_secrets,
    )

    # 5. Check LLM readiness
    if not settings.has_groq_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "GROQ_API_KEY is not configured on the server. "
                "Please configure GROQ_API_KEY in your .env file or environment variables to enable agent reviews."
            ),
        )

    # 6. Execute multi-agent orchestrator
    try:
        orchestrator = Orchestrator()
        review = await orchestrator.run_review(
            pr_url=req.pr_url,
            repo=f"{owner}/{repo}",
            pr_number=pr_number,
            pr_title=pr_metadata.get("title", ""),
            pr_author=pr_metadata.get("author", "unknown"),
            context=context,
        )
    except Exception as e:
        logger.error(f"Orchestration failure: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent review failed: {str(e)}",
        )

    # 7. Persist to SQLite review history
    saved_id = save_review(review)
    review.id = saved_id

    return review.model_dump()


@app.post("/api/post-review")
async def post_review(req: PostReviewRequest) -> Dict[str, Any]:
    """Post a generated markdown review to the pull request on GitHub."""
    token = req.github_token or settings.github_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub token is required to post a review comment. Please configure GITHUB_TOKEN in your .env file or provide a token.",
        )

    try:
        comment_url = await post_summary_comment(
            owner=req.owner,
            repo=req.repo,
            pr_number=req.pr_number,
            summary_markdown=req.summary_markdown,
            token=token,
        )
    except (ValueError, PermissionError, RuntimeError) as e:
        logger.error(f"Error posting review to GitHub: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error posting review: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to post review comment to GitHub.",
        )

    # If review_id is provided, update SQLite history record
    if req.review_id:
        update_comment_url(req.review_id, comment_url)

    return {
        "success": True,
        "message": "Review posted successfully to GitHub.",
        "comment_url": comment_url,
    }


@app.get("/api/history")
async def list_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Get recent review history from SQLite."""
    try:
        records = get_recent_reviews(limit=limit)
        return [r.model_dump() for r in records]
    except Exception as e:
        logger.error(f"Error reading history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load review history.",
        )


@app.get("/api/history/{review_id}")
async def get_history_detail(review_id: int) -> Dict[str, Any]:
    """Get complete details for a specific historical review."""
    record = get_review_by_id(review_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review #{review_id} not found in history.",
        )
    return record.model_dump()
