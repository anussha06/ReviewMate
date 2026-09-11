"""Bounded context manager for ReviewMate AI.

Extracts diffs, detects dependencies, tests, and configuration files,
estimates token counts using tiktoken, redacts secrets, and limits the context
budget to prevent dumping oversized repositories into LLM prompts.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.secret_scanner import redact_secrets

try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
    _ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:
    _TIKTOKEN_AVAILABLE = False
    _ENCODER = None


def estimate_tokens(text: str) -> int:
    """Estimate token count using tiktoken (cl100k_base) or char heuristic."""
    if not text:
        return 0
    if _TIKTOKEN_AVAILABLE and _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text, disallowed_special=()))
        except Exception:
            pass
    # Standard heuristic: ~4 characters per token
    return max(1, len(text) // 4)


class BoundedContext(BaseModel):
    """Encapsulates the bounded context provided to review agents."""
    files_included: List[str] = Field(default_factory=list)
    estimated_tokens: int = 0
    context_limit: int = 6000
    is_truncated: bool = False
    diff_summary: Dict[str, Any] = Field(default_factory=dict)
    imports_detected: List[str] = Field(default_factory=list)
    tests_detected: List[str] = Field(default_factory=list)
    configs_detected: List[str] = Field(default_factory=list)
    context_text: str = ""


# Regex patterns for detecting direct imports in Python, JS/TS, Go, Java
_IMPORT_PATTERNS = [
    # Python: import x, from x import y
    re.compile(r"^\s*(?:import\s+([a-zA-Z0-9_\.]+)|from\s+([a-zA-Z0-9_\.]+)\s+import)", re.MULTILINE),
    # JS/TS/ESM: import ... from 'pkg' or require('pkg')
    re.compile(r"""(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))"""),
    # Go: import "pkg"
    re.compile(r"""^\s*import\s+(?:\(\s*)?['"]([^'"]+)['"]""", re.MULTILINE),
]

_CONFIG_FILE_PATTERNS = {
    "package.json", "package-lock.json", "requirements.txt", "pyproject.toml",
    "setup.py", "Pipfile", "tsconfig.json", "Dockerfile", "docker-compose.yml",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", ".env.example",
}

_TEST_FILE_PATTERNS = re.compile(
    r"(?:test[s]?\/|__tests__\/|test_.*\.py$|.*_test\.py$|.*\.spec\.[a-z]+$|.*\.test\.[a-z]+$)",
    re.IGNORECASE,
)


def extract_imports_from_patch(patch_text: str) -> List[str]:
    """Extract imported module/package names from diff additions."""
    imports: set[str] = set()
    # Focus only on added or modified lines in git diffs
    added_lines = [
        line[1:] for line in patch_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    code_blob = "\n".join(added_lines)

    for pattern in _IMPORT_PATTERNS:
        for match in pattern.finditer(code_blob):
            for group in match.groups():
                if group:
                    # Clean symbol
                    pkg = group.strip().split(".")[0].split("/")[0]
                    if pkg and len(pkg) < 50:
                        imports.add(pkg)
    return sorted(imports)


def build_bounded_context(
    pr_metadata: Dict[str, Any],
    pr_files: List[Dict[str, Any]],
    supplemental_files: Optional[Dict[str, str]] = None,
    context_limit: int = 6000,
    known_secrets: Optional[List[str]] = None,
) -> BoundedContext:
    """Construct a bounded, secret-redacted context for pull request review.

    Args:
        pr_metadata: Pull request metadata (title, body, repo, author, etc.)
        pr_files: List of file dictionaries from GitHub API ({filename, patch, status, additions, deletions})
        supplemental_files: Optional dict of {filename: content} for configs, tests, or docs
        context_limit: Maximum tokens allowed for the context text.
        known_secrets: Secrets to explicitly redact.
    """
    files_included: List[str] = []
    imports_detected: set[str] = set()
    tests_detected: List[str] = []
    configs_detected: List[str] = []
    
    total_additions = sum(f.get("additions", 0) for f in pr_files)
    total_deletions = sum(f.get("deletions", 0) for f in pr_files)

    diff_summary = {
        "files_changed": len(pr_files),
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "repo": pr_metadata.get("repo", "unknown"),
        "pr_number": pr_metadata.get("pr_number", 0),
        "title": pr_metadata.get("title", ""),
        "author": pr_metadata.get("author", "unknown"),
    }

    # Inspect file types
    for f in pr_files:
        fn = f.get("filename", "")
        if fn:
            files_included.append(fn)
            base_name = fn.split("/")[-1]
            if base_name in _CONFIG_FILE_PATTERNS:
                configs_detected.append(fn)
            if _TEST_FILE_PATTERNS.search(fn):
                tests_detected.append(fn)

            patch = f.get("patch", "")
            if patch:
                imports_detected.update(extract_imports_from_patch(patch))

    # Assemble context sections
    # 1. PR Header & Overview
    header_section = [
        f"### Pull Request Metadata",
        f"- Repository: {diff_summary['repo']}",
        f"- PR Number: #{diff_summary['pr_number']}",
        f"- Title: {diff_summary['title']}",
        f"- Author: {diff_summary['author']}",
        f"- Files Changed: {diff_summary['files_changed']} (+{total_additions} / -{total_deletions})",
    ]

    pr_desc = pr_metadata.get("body", "").strip()
    if pr_desc:
        # Sanitize PR description
        redacted_desc = redact_secrets(pr_desc[:1000], known_secrets).sanitized_text
        header_section.append(f"- Description: {redacted_desc}")

    if imports_detected:
        header_section.append(f"- Direct Imports Detected: {', '.join(sorted(imports_detected)[:20])}")
    if configs_detected:
        header_section.append(f"- Config Files Touched: {', '.join(configs_detected[:10])}")
    if tests_detected:
        header_section.append(f"- Test Files Touched: {', '.join(tests_detected[:10])}")

    header_text = "\n".join(header_section) + "\n\n"

    # 2. File Patches (Priority 1)
    file_diff_sections: List[str] = []
    for f in pr_files:
        fn = f.get("filename", "unknown")
        status = f.get("status", "modified")
        adds = f.get("additions", 0)
        dels = f.get("deletions", 0)
        patch = f.get("patch", "")

        sec_header = f"#### File: `{fn}` ({status}, +{adds} / -{dels})\n"
        if not patch:
            patch_content = "(Binary file or empty diff)\n"
        else:
            # Redact secrets before inclusion
            redacted_patch = redact_secrets(patch, known_secrets).sanitized_text
            patch_content = f"```diff\n{redacted_patch}\n```\n"

        file_diff_sections.append(sec_header + patch_content)

    # 3. Supplemental Context (Config, Tests, README)
    supplemental_sections: List[str] = []
    if supplemental_files:
        for s_name, s_content in supplemental_files.items():
            redacted_s = redact_secrets(s_content[:2000], known_secrets).sanitized_text
            supplemental_sections.append(
                f"#### Supplemental: `{s_name}`\n```\n{redacted_s}\n```\n"
            )

    # Build context respecting context_limit budget
    # Reserve tokens for agent prompt overhead (~1500 tokens)
    budget = max(1000, context_limit - 1500)
    current_tokens = estimate_tokens(header_text)

    assembled_sections: List[str] = [header_text, "### Changed Files & Diffs\n\n"]
    is_truncated = False

    for sec in file_diff_sections:
        sec_tokens = estimate_tokens(sec)
        if current_tokens + sec_tokens <= budget:
            assembled_sections.append(sec + "\n")
            current_tokens += sec_tokens
        else:
            # If a single diff is too large, truncate lines while keeping context
            remaining_tokens = budget - current_tokens
            if remaining_tokens > 200:
                lines = sec.splitlines(keepends=True)
                truncated_chunk = ""
                for line in lines:
                    if estimate_tokens(truncated_chunk + line) < remaining_tokens - 50:
                        truncated_chunk += line
                    else:
                        break
                truncated_chunk += "\n... [Remaining diff lines omitted to respect context budget] ...\n```\n"
                assembled_sections.append(truncated_chunk)
                current_tokens += estimate_tokens(truncated_chunk)
            is_truncated = True
            break

    # Add supplemental files if budget allows
    if not is_truncated and supplemental_sections:
        assembled_sections.append("### Supplemental Repository Context\n\n")
        for sup_sec in supplemental_sections:
            sec_tokens = estimate_tokens(sup_sec)
            if current_tokens + sec_tokens <= budget:
                assembled_sections.append(sup_sec + "\n")
                current_tokens += sec_tokens
            else:
                is_truncated = True
                break

    final_context_text = "".join(assembled_sections)
    total_estimated_tokens = estimate_tokens(final_context_text)

    return BoundedContext(
        files_included=files_included,
        estimated_tokens=total_estimated_tokens,
        context_limit=context_limit,
        is_truncated=is_truncated,
        diff_summary=diff_summary,
        imports_detected=sorted(imports_detected),
        tests_detected=tests_detected,
        configs_detected=configs_detected,
        context_text=final_context_text,
    )
