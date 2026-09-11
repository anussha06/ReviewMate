"""Data models for ReviewMate AI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

SeverityLevel = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
ConfidenceLevel = Literal["HIGH", "MEDIUM", "LOW"]
RecommendationType = Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"]
AgentName = Literal["bug", "security", "quality", "performance"]


class Finding(BaseModel):
    """Structured code review finding produced by an agent."""
    agent: str = Field(..., description="Name of the reporting agent: bug, security, quality, performance")
    category: str = Field(..., description="Category of finding (e.g., Security, Logic Bug, Code Quality, Performance)")
    severity: SeverityLevel = Field(..., description="Severity level: CRITICAL, HIGH, MEDIUM, LOW")
    confidence: ConfidenceLevel = Field(..., description="Confidence level: HIGH, MEDIUM, LOW")
    file: str = Field(..., description="Path to the file where issue was found")
    line: Optional[int] = Field(None, description="Line number if known with certainty; null if general/unknown")
    title: str = Field(..., description="Concise, descriptive title (e.g. Potential SQL Injection)")
    description: str = Field(..., description="Detailed explanation of the issue with rationale")
    recommendation: str = Field(..., description="Concrete, actionable fix or remediation advice")


class AgentStatus(BaseModel):
    """Execution status and finding tally for an agent."""
    agent: str
    status: Literal["idle", "running", "completed", "error"]
    findings_count: int = 0
    error_message: Optional[str] = None


class ReviewRecord(BaseModel):
    """Persisted review record."""
    id: Optional[int] = None
    pr_url: str
    repo: str
    pr_number: int
    pr_title: str
    pr_author: str
    recommendation: RecommendationType
    context_summary: Dict[str, Any] = Field(default_factory=dict)
    agent_statuses: Dict[str, AgentStatus] = Field(default_factory=dict)
    findings: List[Finding] = Field(default_factory=list)
    summary_markdown: str = ""
    github_comment_url: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class AnalyzeRequest(BaseModel):
    """Payload for POST /api/analyze."""
    pr_url: str = Field(..., description="Full GitHub Pull Request URL")
    github_token: Optional[str] = Field(None, description="Optional personal access token override")


class PostReviewRequest(BaseModel):
    """Payload for POST /api/post-review."""
    review_id: Optional[int] = None
    owner: str
    repo: str
    pr_number: int
    summary_markdown: str
    github_token: Optional[str] = None
