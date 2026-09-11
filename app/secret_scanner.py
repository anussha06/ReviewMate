"""Secret scanner and redactor for ReviewMate AI.

Guarantees that credentials, tokens, private keys, passwords, and API keys
are redacted before any file content, diff, or prompt is transmitted to LLMs.
"""

from __future__ import annotations

import re
from typing import NamedTuple, List, Tuple


class SecretRedactionResult(NamedTuple):
    sanitized_text: str
    redactions_count: int
    redacted_types: List[str]


# High-confidence pattern definitions
# (name, regex_pattern, flags)
_PATTERNS: List[Tuple[str, str, int]] = [
    # 1. Private keys (RSA, DSA, EC, OPENSSH, PGP, etc.)
    (
        "PRIVATE_KEY",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        re.MULTILINE,
    ),
    # 2. GitHub Personal Access Tokens (Classic, fine-grained, OAuth, user-to-server)
    (
        "GITHUB_TOKEN",
        r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}",
        0,
    ),
    (
        "GITHUB_PAT",
        r"github_pat_[A-Za-z0-9_]{50,255}",
        0,
    ),
    # 3. AWS Access Key ID
    (
        "AWS_ACCESS_KEY",
        r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b",
        0,
    ),
    # 4. Groq API Key
    (
        "GROQ_KEY",
        r"\bgsk_[A-Za-z0-9]{40,64}\b",
        0,
    ),
    # 5. OpenAI API Key (legacy and project tokens)
    (
        "OPENAI_KEY",
        r"\bsk-(?:proj-|live-)?[A-Za-z0-9_-]{20,80}\b",
        0,
    ),
    # 6. Slack API Tokens
    (
        "SLACK_TOKEN",
        r"\bxox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,34}\b",
        0,
    ),
    # 7. JWT (JSON Web Token)
    (
        "JWT_TOKEN",
        r"\beyJ[A-Za-z0-9-_=]+\.eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_.+/=]+\b",
        0,
    ),
    # 8. Database connection URI with embedded password
    (
        "DATABASE_CREDENTIAL",
        r"(?:postgres|postgresql|mysql|mongodb|redis|amqp):\/\/[^:\s\/]+:([^@\s\/]+)@",
        0,
    ),
    # 9. Authorization headers: Authorization: Bearer <token> or Basic <base64>
    (
        "AUTH_HEADER",
        r"""(?i)(['"]?authorization['"]?\s*[:=]\s*['"]?(?:Bearer|Basic)\s+)([A-Za-z0-9_\-\.\+\/=]{10,})""",
        0,
    ),
    # 10. Key/Secret assignment in code/config:
    # api_key = "..." or password: "..."
    (
        "GENERIC_CREDENTIAL",
        r"""(?i)([\b_A-Za-z0-9]*(?:api[_-]?key|client[_-]?secret|password|passwd|auth[_-]?token|secret[_-]?key)\s*[:=]\s*['"])([A-Za-z0-9_\-.~!@#$%^&*+=]{8,})(['"])""",
        0,
    ),
]


def redact_secrets(
    text: str,
    extra_known_secrets: list[str] | None = None,
) -> SecretRedactionResult:
    """Scan and redact known secret formats from the given text.

    Args:
        text: Source text (diff, file content, code snippet).
        extra_known_secrets: Optional list of specific secret strings
                             (e.g., from environment variables) to redact.

    Returns:
        SecretRedactionResult containing the sanitized text and statistics.
    """
    if not text:
        return SecretRedactionResult(sanitized_text="", redactions_count=0, redacted_types=[])

    redacted_types: list[str] = []
    total_count = 0
    sanitized = text

    # Step A: Redact any explicitly known secrets first (e.g. current env tokens)
    if extra_known_secrets:
        for secret in set(extra_known_secrets):
            if secret and len(secret) >= 6 and secret in sanitized:
                sanitized = sanitized.replace(secret, "[REDACTED_SECRET:KNOWN_ENV_VAR]")
                redacted_types.append("KNOWN_ENV_VAR")
                total_count += 1

    # Step B: Scan against compiled regex patterns
    for name, pattern_str, flags in _PATTERNS:
        pattern = re.compile(pattern_str, flags)

        if name == "DATABASE_CREDENTIAL":
            # Redact only the password segment inside the URI
            def _replace_db_cred(match: re.Match[str]) -> str:
                nonlocal total_count
                total_count += 1
                full = match.group(0)
                password = match.group(1)
                return full.replace(password, "[REDACTED_SECRET:DB_PASSWORD]")

            sanitized, count = pattern.subn(_replace_db_cred, sanitized)
            if count > 0:
                redacted_types.append(name)

        elif name == "AUTH_HEADER":
            def _replace_auth(match: re.Match[str]) -> str:
                nonlocal total_count
                total_count += 1
                prefix = match.group(1)
                return f"{prefix}[REDACTED_SECRET:AUTH_TOKEN]"

            sanitized, count = pattern.subn(_replace_auth, sanitized)
            if count > 0:
                redacted_types.append(name)

        elif name == "GENERIC_CREDENTIAL":
            def _replace_generic(match: re.Match[str]) -> str:
                nonlocal total_count
                total_count += 1
                prefix = match.group(1)
                suffix = match.group(3)
                return f"{prefix}[REDACTED_SECRET:CREDENTIAL]{suffix}"

            sanitized, count = pattern.subn(_replace_generic, sanitized)
            if count > 0:
                redacted_types.append(name)

        else:
            # Direct match replacement
            def _replace_direct(match: re.Match[str]) -> str:
                nonlocal total_count
                total_count += 1
                return f"[REDACTED_SECRET:{name}]"

            sanitized, count = pattern.subn(_replace_direct, sanitized)
            if count > 0:
                redacted_types.append(name)

    return SecretRedactionResult(
        sanitized_text=sanitized,
        redactions_count=total_count,
        redacted_types=list(set(redacted_types)),
    )
