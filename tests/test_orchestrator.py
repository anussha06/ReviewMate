"""Tests for ReviewMate AI orchestrator, deduplication, and markdown generation."""

import pytest
from app.db.models import Finding
from app.orchestrator import (
    deduplicate_findings,
    determine_recommendation,
    generate_review_markdown,
    _is_duplicate_finding,
)
from app.agents.base import BaseAgent
from app.context_manager import BoundedContext


class DummyAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="dummy", category="Test")

    @property
    def system_instructions(self):
        return "Test instructions"


def test_agent_validate_and_parse_findings():
    agent = DummyAgent()

    # Case 1: Valid dict with findings list
    raw_data = {
        "findings": [
            {
                "agent": "dummy",
                "category": "Test",
                "severity": "HIGH",
                "confidence": "HIGH",
                "file": "main.py",
                "line": 42,
                "title": "Potential off-by-one error",
                "description": "Loop bound exceeds array length",
                "recommendation": "Use range(len(arr))",
            }
        ]
    }
    findings = agent.validate_and_parse_findings(raw_data)
    assert len(findings) == 1
    assert findings[0].file == "main.py"
    assert findings[0].line == 42
    assert findings[0].severity == "HIGH"

    # Case 2: String line number conversion
    raw_string_line = {
        "findings": [
            {
                "severity": "medium",
                "confidence": "low",
                "file": "auth.py",
                "line": "15",
                "title": "Missing salt",
                "description": "Salt is missing",
                "recommendation": "Add salt",
            }
        ]
    }
    parsed = agent.validate_and_parse_findings(raw_string_line)
    assert len(parsed) == 1
    assert parsed[0].line == 15
    assert parsed[0].severity == "MEDIUM"
    assert parsed[0].confidence == "LOW"

    # Case 3: Invalid line number should default to None
    raw_invalid_line = {
        "findings": [
            {
                "severity": "INVALID_SEV",
                "confidence": "UNKNOWN",
                "file": "utils.py",
                "line": "not-a-number",
                "title": "General issue",
                "description": "General description",
                "recommendation": "Fix it",
            }
        ]
    }
    parsed_invalid = agent.validate_and_parse_findings(raw_invalid_line)
    assert len(parsed_invalid) == 1
    assert parsed_invalid[0].line is None
    assert parsed_invalid[0].severity == "MEDIUM"  # Default fallback
    assert parsed_invalid[0].confidence == "MEDIUM"

    # Case 4: Completely malformed or empty data
    assert agent.validate_and_parse_findings("invalid non-json") == []
    assert agent.validate_and_parse_findings({"findings": ["just a string"]}) == []


def test_deduplicate_findings():
    f1 = Finding(
        agent="security",
        category="Security",
        severity="HIGH",
        confidence="HIGH",
        file="app/login.py",
        line=10,
        title="Potential SQL Injection vulnerability in query string",
        description="Query concatenation allows unsanitized inputs to execute SQL commands.",
        recommendation="Use parameterized query.",
    )
    f2 = Finding(
        agent="bug",
        category="Logic & Bugs",
        severity="MEDIUM",
        confidence="MEDIUM",
        file="app/login.py",
        line=11,  # within 3 lines
        title="Potential SQL Injection flaw in login query",
        description="Unsanitized query string could cause SQL injection or syntax crash.",
        recommendation="Use parameterized DB calls.",
    )
    f3 = Finding(
        agent="quality",
        category="Code Quality",
        severity="LOW",
        confidence="LOW",
        file="app/config.py",
        line=5,
        title="Magic number in timeout",
        description="Consider defining constant for timeout",
        recommendation="Declare TIMEOUT = 30",
    )

    deduped = deduplicate_findings([f1, f2, f3])
    assert len(deduped) == 2  # f1 and f2 merged
    # Highest severity (HIGH) kept
    assert deduped[0].severity == "HIGH"
    assert "security" in deduped[0].agent
    assert "bug" in deduped[0].agent


def test_determine_recommendation():
    # 1. No findings -> APPROVE
    assert determine_recommendation([]) == "APPROVE"

    # 2. High/Critical Security or Bug -> REQUEST_CHANGES
    sec_high = Finding(
        agent="security",
        category="Security",
        severity="HIGH",
        confidence="HIGH",
        file="login.py",
        line=1,
        title="SQLi",
        description="SQL injection",
        recommendation="Fix",
    )
    assert determine_recommendation([sec_high]) == "REQUEST_CHANGES"

    # 3. Only quality/perf medium/low -> COMMENT
    qual_low = Finding(
        agent="quality",
        category="Code Quality",
        severity="LOW",
        confidence="LOW",
        file="style.py",
        line=1,
        title="Style nitpick",
        description="Add docstring",
        recommendation="Add docstring",
    )
    assert determine_recommendation([qual_low]) == "COMMENT"


def test_generate_review_markdown():
    findings = [
        Finding(
            agent="security",
            category="Security",
            severity="HIGH",
            confidence="HIGH",
            file="login.py",
            line=25,
            title="Potential SQL Injection",
            description="User input passed directly to database query.",
            recommendation="Use parameterized statements.",
        )
    ]
    summary = generate_review_markdown(
        repo="owner/repo",
        pr_number=12,
        recommendation="REQUEST_CHANGES",
        findings=findings,
        context_summary={"files_included": ["login.py"], "estimated_tokens": 500},
    )

    assert "# 🤖 ReviewMate AI Review" in summary
    assert "REQUEST_CHANGES" in summary
    assert "Potential SQL Injection" in summary
    assert "`login.py:L25`" in summary
    assert "Use parameterized statements." in summary
