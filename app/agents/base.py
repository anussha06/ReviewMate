"""Base agent architecture for ReviewMate AI."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.context_manager import BoundedContext
from app.db.models import Finding
from app.llm_client import LLMClient

logger = logging.getLogger("reviewmate.agents")

VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
VALID_CONFIDENCES = {"HIGH", "MEDIUM", "LOW"}


class BaseAgent(ABC):
    """Abstract base class for all specialized code review agents."""

    def __init__(self, name: str, category: str) -> None:
        self.name = name
        self.category = category

    @property
    @abstractmethod
    def system_instructions(self) -> str:
        """Domain-specific instructions for the agent."""
        pass

    def get_full_system_prompt(self) -> str:
        """Compose standardized system prompt with strict schema requirements."""
        return f"""You are the {self.name.upper()} Code Review Agent for ReviewMate AI.
Your specialization is: {self.category}.

CRITICAL REVIEW RULES:
1. Findings are hypotheses, not proof. Hedge findings appropriately: use phrases like "Potential...", "Could lead to...", "Consider...", "Appears to...".
2. If a specific line number is not clearly identifiable in the diff, use null for the line. NEVER invent or guess line numbers.
3. Never fabricate files, evidence, or imaginary problems. Focus strictly on real code changes in the pull request.
4. If there are no legitimate concerns in your domain, return an empty list of findings. Do not invent minor nitpicks just to return something.
5. Severity MUST be one of: "CRITICAL", "HIGH", "MEDIUM", "LOW".
6. Confidence MUST be one of: "HIGH", "MEDIUM", "LOW".

SPECIALIZED FOCUS:
{self.system_instructions}

OUTPUT FORMAT:
Return ONLY a valid JSON object with a "findings" key containing an array of findings:
{{
  "findings": [
    {{
      "agent": "{self.name}",
      "category": "{self.category}",
      "severity": "HIGH",
      "confidence": "HIGH",
      "file": "path/to/file.py",
      "line": 42,
      "title": "Concise issue title",
      "description": "Clear explanation of the observed issue and rationale.",
      "recommendation": "Concrete, actionable fix or recommendation."
    }}
  ]
}}
"""

    def validate_and_parse_findings(self, raw_data: Any) -> List[Finding]:
        """Validate raw JSON from LLM into typed Finding objects."""
        findings_list: List[Dict[str, Any]] = []

        if isinstance(raw_data, dict):
            # Check for "findings" or "results" or "items"
            if "findings" in raw_data and isinstance(raw_data["findings"], list):
                findings_list = raw_data["findings"]
            elif "results" in raw_data and isinstance(raw_data["results"], list):
                findings_list = raw_data["results"]
            else:
                # If dict itself represents a single finding
                if "file" in raw_data and "title" in raw_data:
                    findings_list = [raw_data]
        elif isinstance(raw_data, list):
            findings_list = raw_data

        validated: List[Finding] = []
        for item in findings_list:
            if not isinstance(item, dict):
                continue

            try:
                # Sanitize severity
                raw_sev = str(item.get("severity", "MEDIUM")).strip().upper()
                sev = raw_sev if raw_sev in VALID_SEVERITIES else "MEDIUM"

                # Sanitize confidence
                raw_conf = str(item.get("confidence", "MEDIUM")).strip().upper()
                conf = raw_conf if raw_conf in VALID_CONFIDENCES else "MEDIUM"

                # Sanitize line number
                raw_line = item.get("line")
                line: Optional[int] = None
                if raw_line is not None:
                    try:
                        line_val = int(raw_line)
                        if line_val > 0:
                            line = line_val
                    except (ValueError, TypeError):
                        line = None

                file_path = str(item.get("file", "unknown")).strip()
                title = str(item.get("title", "")).strip()
                desc = str(item.get("description", "")).strip()
                rec = str(item.get("recommendation", "")).strip()

                if not title or not desc:
                    continue

                finding = Finding(
                    agent=self.name,
                    category=item.get("category", self.category) or self.category,
                    severity=sev,
                    confidence=conf,
                    file=file_path,
                    line=line,
                    title=title,
                    description=desc,
                    recommendation=rec or "Review code changes for alignment with best practices.",
                )
                validated.append(finding)
            except Exception as parse_err:
                logger.warning(f"Error parsing finding from agent {self.name}: {parse_err}")
                continue

        return validated

    async def run(
        self,
        context: BoundedContext,
        llm_client: LLMClient,
    ) -> List[Finding]:
        """Execute the agent against the bounded context."""
        system_prompt = self.get_full_system_prompt()
        user_prompt = f"""Please review the following pull request bounded context for {self.category.lower()} concerns:

{context.context_text}
"""
        raw_output = await llm_client.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return self.validate_and_parse_findings(raw_output)
