"""Tests for bounded context manager."""

import pytest
from app.context_manager import (
    estimate_tokens,
    extract_imports_from_patch,
    build_bounded_context,
)


def test_estimate_tokens():
    text = "Hello world! This is a test string to verify token estimation."
    tokens = estimate_tokens(text)
    assert tokens > 5
    assert estimate_tokens("") == 0


def test_extract_imports_from_patch():
    patch = """@@ -1,3 +1,6 @@
+import os
+import requests
+from fastapi import FastAPI, HTTPException
+import my_internal_module.subpkg
 def main():
-    pass
+    print("ok")
"""
    imports = extract_imports_from_patch(patch)
    assert "os" in imports
    assert "requests" in imports
    assert "fastapi" in imports
    assert "my_internal_module" in imports


def test_build_bounded_context_basic():
    pr_metadata = {
        "repo": "owner/repo",
        "pr_number": 42,
        "title": "Add user authentication",
        "author": "octocat",
        "body": "Implements login route and password hashing",
    }
    pr_files = [
        {
            "filename": "app/auth.py",
            "status": "added",
            "additions": 25,
            "deletions": 0,
            "patch": "+import bcrypt\n+def hash_pw(pw):\n+    return bcrypt.hashpw(pw, bcrypt.gensalt())\n",
        },
        {
            "filename": "tests/test_auth.py",
            "status": "added",
            "additions": 10,
            "deletions": 0,
            "patch": "+import pytest\n+def test_hash():\n+    assert True\n",
        },
        {
            "filename": "requirements.txt",
            "status": "modified",
            "additions": 1,
            "deletions": 0,
            "patch": "+bcrypt==4.1.2\n",
        },
    ]

    ctx = build_bounded_context(pr_metadata, pr_files, context_limit=4000)

    assert "app/auth.py" in ctx.files_included
    assert "tests/test_auth.py" in ctx.files_included
    assert "requirements.txt" in ctx.files_included
    assert "tests/test_auth.py" in ctx.tests_detected
    assert "requirements.txt" in ctx.configs_detected
    assert "bcrypt" in ctx.imports_detected
    assert ctx.estimated_tokens > 0
    assert ctx.estimated_tokens <= 4000
    assert not ctx.is_truncated
    assert "### Pull Request Metadata" in ctx.context_text
    assert "bcrypt.hashpw" in ctx.context_text


def test_build_bounded_context_truncation():
    pr_metadata = {
        "repo": "owner/repo",
        "pr_number": 99,
        "title": "Massive file change",
        "author": "octocat",
        "body": "Big change",
    }
    # Create very large patch
    large_patch = "+large_data_line = 'abcdefghijklmnopqrstuvwxyz0123456789'\n" * 500
    pr_files = [
        {
            "filename": "app/data.py",
            "status": "modified",
            "additions": 500,
            "deletions": 0,
            "patch": large_patch,
        }
    ]

    # Set very small token budget
    ctx = build_bounded_context(pr_metadata, pr_files, context_limit=1500)
    assert ctx.is_truncated is True
    assert ctx.estimated_tokens <= 1500
