"""Tests for secret scanner and redaction functionality."""

import pytest
from app.secret_scanner import redact_secrets


def test_redact_github_pat():
    sample = "const token = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890';"
    res = redact_secrets(sample)
    assert "ghp_" not in res.sanitized_text
    assert "[REDACTED_SECRET:GITHUB_TOKEN]" in res.sanitized_text
    assert res.redactions_count >= 1
    assert "GITHUB_TOKEN" in res.redacted_types


def test_redact_fine_grained_pat():
    sample = "github_pat_11AAAAAAA01234567890abcdefghijklmnopqrstuvwxyz_01234567890abcdefghijklmnopq"
    res = redact_secrets(sample)
    assert "github_pat_" not in res.sanitized_text
    assert "[REDACTED_SECRET:GITHUB_PAT]" in res.sanitized_text
    assert "GITHUB_PAT" in res.redacted_types


def test_redact_aws_keys():
    sample = "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'"
    res = redact_secrets(sample)
    assert "AKIAIOSFODNN7EXAMPLE" not in res.sanitized_text
    assert "[REDACTED_SECRET:AWS_ACCESS_KEY]" in res.sanitized_text


def test_redact_groq_key():
    sample = "GROQ_API_KEY=gsk_1234567890abcdef1234567890abcdef1234567890"
    res = redact_secrets(sample)
    assert "gsk_" not in res.sanitized_text
    assert "[REDACTED_SECRET:GROQ_KEY]" in res.sanitized_text


def test_redact_private_key():
    sample = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Y1o7P
-----END RSA PRIVATE KEY-----"""
    res = redact_secrets(sample)
    assert "BEGIN RSA PRIVATE KEY" not in res.sanitized_text
    assert "[REDACTED_SECRET:PRIVATE_KEY]" in res.sanitized_text


def test_redact_auth_header():
    sample = "headers = {'Authorization': 'Bearer ya29.a0AfH6SMB...'}"
    res = redact_secrets(sample)
    assert "ya29.a0AfH6SMB" not in res.sanitized_text
    assert "[REDACTED_SECRET:AUTH_TOKEN]" in res.sanitized_text


def test_redact_generic_credentials():
    sample = 'db_password = "SuperSecretPassword123!"'
    res = redact_secrets(sample)
    assert "SuperSecretPassword123!" not in res.sanitized_text
    assert "[REDACTED_SECRET:CREDENTIAL]" in res.sanitized_text


def test_redact_known_extra_secrets():
    known_key = "my-special-private-vault-token-xyz999"
    sample = f"connect_to_service('{known_key}')"
    res = redact_secrets(sample, extra_known_secrets=[known_key])
    assert known_key not in res.sanitized_text
    assert "[REDACTED_SECRET:KNOWN_ENV_VAR]" in res.sanitized_text


def test_clean_text_unchanged():
    clean = "def add(a: int, b: int) -> int:\n    return a + b\n"
    res = redact_secrets(clean)
    assert res.sanitized_text == clean
    assert res.redactions_count == 0
    assert len(res.redacted_types) == 0
