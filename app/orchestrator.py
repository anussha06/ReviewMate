"""ReviewMate AI review orchestrator.

Coordinates multi-agent execution, validates outputs, deduplicates findings,
derives final recommendations, and generates GitHub-formatted Markdown reviews.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from app.agents.base import BaseAgent
from app.agents.bug_agent import BugAgent
from app.agents.security_agent import SecurityAgent
from app.agents.quality_agent import QualityAgent
from app.agents.performance_agent import PerformanceAgent
from app.context_manager import BoundedContext
from app.db.models import Finding, AgentStatus, RecommendationType, ReviewRecord
from app.llm_client import LLMClient

logger = logging.getLogger("reviewmate.orchestrator")

SEVERITY_RANKS = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
CONFIDENCE_RANKS = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _tokenize(text: str) -> Set[str]:
    """Tokenize words for similarity comparison."""
    words = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", text.lower())
    return set(words)


def _is_duplicate_finding(f1: Finding, f2: Finding) -> bool:
    """Determine if two findings represent the same underlying issue."""
    # 1. Must be in the same file
    if f1.file.lower().strip() != f2.file.lower().strip():
        return False

    # 2. Line check: if both have lines, must be within 3 lines of each other
    if f1.line is not None and f2.line is not None:
        if abs(f1.line - f2.line) > 3:
            return False

    # 3. Text semantic similarity
    tokens1 = _tokenize(f"{f1.title} {f1.description}")
    tokens2 = _tokenize(f"{f2.title} {f2.description}")

    if not tokens1 or not tokens2:
        return False

    intersection = tokens1.intersection(tokens2)
    smaller_size = min(len(tokens1), len(tokens2))
    overlap = len(intersection) / smaller_size if smaller_size > 0 else 0

    return overlap >= 0.45


def deduplicate_findings(findings: List[Finding]) -> List[Finding]:
    """Deduplicate overlapping findings while preserving highest severity and confidence."""
    if not findings:
        return []

    unique: List[Finding] = []

    for f in findings:
        matched_idx = -1
        for idx, u in enumerate(unique):
            if _is_duplicate_finding(f, u):
                matched_idx = idx
                break

        if matched_idx == -1:
            unique.append(f)
        else:
            existing = unique[matched_idx]
            # Merge: take higher severity
            f_sev_rank = SEVERITY_RANKS.get(f.severity, 2)
            e_sev_rank = SEVERITY_RANKS.get(existing.severity, 2)
            chosen_sev = f.severity if f_sev_rank > e_sev_rank else existing.severity

            # Take higher confidence
            f_conf_rank = CONFIDENCE_RANKS.get(f.confidence, 2)
            e_conf_rank = CONFIDENCE_RANKS.get(existing.confidence, 2)
            chosen_conf = f.confidence if f_conf_rank > e_conf_rank else existing.confidence

            # Line number preference
            chosen_line = existing.line if existing.line is not None else f.line

            # Agent attribution
            combined_agents = existing.agent
            if f.agent not in existing.agent:
                combined_agents = f"{existing.agent}, {f.agent}"

            unique[matched_idx] = Finding(
                agent=combined_agents,
                category=existing.category if e_sev_rank >= f_sev_rank else f.category,
                severity=chosen_sev,
                confidence=chosen_conf,
                file=existing.file,
                line=chosen_line,
                title=existing.title if len(existing.title) >= len(f.title) else f.title,
                description=existing.description if len(existing.description) >= len(f.description) else f.description,
                recommendation=existing.recommendation if len(existing.recommendation) >= len(f.recommendation) else f.recommendation,
            )

    # Sort findings by severity descending, then confidence descending
    unique.sort(
        key=lambda x: (
            -SEVERITY_RANKS.get(x.severity, 0),
            -CONFIDENCE_RANKS.get(x.confidence, 0),
            x.file,
            x.line or 0,
        )
    )
    return unique


def determine_recommendation(findings: List[Finding]) -> RecommendationType:
    """Calculate final recommendation based on review findings."""
    if not findings:
        return "APPROVE"

    # Any HIGH or CRITICAL security or bug finding -> REQUEST_CHANGES
    has_critical_blocker = any(
        f.severity in ("CRITICAL", "HIGH") and any(a in f.agent for a in ("security", "bug"))
        for f in findings
    )
    if has_critical_blocker:
        return "REQUEST_CHANGES"

    # Any medium findings, or high quality/perf findings -> COMMENT
    return "COMMENT"


def generate_review_markdown(
    repo: str,
    pr_number: int,
    recommendation: RecommendationType,
    findings: List[Finding],
    context_summary: dict,
) -> str:
    """Generate clean, professional GitHub Markdown summary for PR comment."""
    rec_emojis = {
        "APPROVE": "✅ **APPROVE**",
        "REQUEST_CHANGES": "🛑 **REQUEST_CHANGES**",
        "COMMENT": "💬 **COMMENT**",
    }
    badge = rec_emojis.get(recommendation, recommendation)

    lines: List[str] = [
        "# 🤖 ReviewMate AI Review",
        "",
        "## Summary",
        f"ReviewMate analyzed pull request **#{pr_number}** in `{repo}` using four specialized AI review agents (Bug, Security, Quality, Performance).",
        "",
        f"- **Files Analyzed**: {len(context_summary.get('files_included', []))}",
        f"- **Estimated Context Tokens**: ~{context_summary.get('estimated_tokens', 0)}",
        f"- **Total Findings**: {len(findings)}",
        f"- **Recommendation**: {badge}",
        "",
    ]

    if not findings:
        lines.extend([
            "## Findings",
            "✨ *No significant issues or defects were detected across all four agents. Looks good to merge!*",
            "",
        ])
    else:
        lines.extend([
            "## Findings",
            "",
        ])

        # Group findings by severity
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            sev_findings = [f for f in findings if f.severity == sev]
            if not sev_findings:
                continue

            icon = "🔴" if sev in ("CRITICAL", "HIGH") else ("🟡" if sev == "MEDIUM" else "⚪")
            lines.append(f"### {icon} {sev} ({len(sev_findings)})")
            lines.append("")

            for f in sev_findings:
                line_str = f":L{f.line}" if f.line is not None else ""
                lines.append(f"#### **{f.title}**")
                lines.append(f"- **Agent**: `{f.agent}` | **Category**: {f.category} | **Confidence**: {f.confidence.capitalize()}")
                lines.append(f"- **File**: `{f.file}{line_str}`")
                lines.append("")
                lines.append(f"**Description:**  \n{f.description}")
                lines.append("")
                lines.append(f"**Recommendation:**  \n{f.recommendation}")
                lines.append("")

    lines.extend([
        "---",
        "## Final Recommendation",
        f"{badge}",
        "",
        "> *Note: Findings are generated by automated AI agents as advisory hypotheses. Please conduct human verification before merging.*",
    ])

    return "\n".join(lines)


class Orchestrator:
    """Manages multi-agent execution pipeline."""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.agents: List[BaseAgent] = [
            BugAgent(),
            SecurityAgent(),
            QualityAgent(),
            PerformanceAgent(),
        ]

    async def run_review(
        self,
        pr_url: str,
        repo: str,
        pr_number: int,
        pr_title: str,
        pr_author: str,
        context: BoundedContext,
    ) -> ReviewRecord:
        """Execute full review workflow."""
        agent_statuses: Dict[str, AgentStatus] = {}
        all_raw_findings: List[Finding] = []

        # Limit concurrent Groq LLM requests to 2 to prevent burst rate limits
        semaphore = asyncio.Semaphore(2)

        async def _run_single_agent(agent: BaseAgent) -> Tuple[str, List[Finding], Optional[str]]:
            async with semaphore:
                try:
                    findings = await agent.run(context, self.llm_client)
                    return agent.name, findings, None
                except Exception as e:
                    logger.error(f"Agent {agent.name} encountered error: {e}")
                    return agent.name, [], str(e)

        # Run all four agents with bounded concurrency
        tasks = [_run_single_agent(agent) for agent in self.agents]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for agent_name, agent_findings, error_msg in results:
            if error_msg:
                agent_statuses[agent_name] = AgentStatus(
                    agent=agent_name,
                    status="error",
                    findings_count=0,
                    error_message=error_msg,
                )
            else:
                agent_statuses[agent_name] = AgentStatus(
                    agent=agent_name,
                    status="completed",
                    findings_count=len(agent_findings),
                )
                all_raw_findings.extend(agent_findings)

        # Deduplicate and rank findings
        deduped = deduplicate_findings(all_raw_findings)

        # Determine recommendation
        recommendation = determine_recommendation(deduped)

        # Generate markdown review
        summary_md = generate_review_markdown(
            repo=repo,
            pr_number=pr_number,
            recommendation=recommendation,
            findings=deduped,
            context_summary={
                "files_included": context.files_included,
                "estimated_tokens": context.estimated_tokens,
                "context_limit": context.context_limit,
                "is_truncated": context.is_truncated,
            },
        )

        return ReviewRecord(
            pr_url=pr_url,
            repo=repo,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_author=pr_author,
            recommendation=recommendation,
            context_summary={
                "files_included": context.files_included,
                "estimated_tokens": context.estimated_tokens,
                "context_limit": context.context_limit,
                "is_truncated": context.is_truncated,
                "diff_summary": context.diff_summary,
                "imports_detected": context.imports_detected,
                "configs_detected": context.configs_detected,
                "tests_detected": context.tests_detected,
            },
            agent_statuses=agent_statuses,
            findings=deduped,
            summary_markdown=summary_md,
        )
