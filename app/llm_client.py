"""LLM client for ReviewMate AI using Groq API.

Provides structured response handling, robust JSON parsing,
secret protection, and graceful error handling.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings

try:
    from groq import AsyncGroq, APIError, AuthenticationError, RateLimitError
    _GROQ_SDK_AVAILABLE = True
except Exception:
    _GROQ_SDK_AVAILABLE = False
    AsyncGroq = None  # type: ignore


def clean_json_response(raw_text: str) -> Any:
    """Extract and parse JSON from an LLM response string."""
    if not raw_text or not raw_text.strip():
        return []

    text = raw_text.strip()

    # If wrapped in markdown code blocks: ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()

    # Try standard json parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # If the text has preamble, find the first '[' or '{' and last ']' or '}'
    start_bracket = text.find("[")
    end_bracket = text.rfind("]")
    if start_bracket != -1 and end_bracket != -1 and end_bracket > start_bracket:
        candidate = text[start_bracket : end_bracket + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    start_brace = text.find("{")
    end_brace = text.rfind("}")
    if start_brace != -1 and end_brace != -1 and end_brace > start_brace:
        candidate = text[start_brace : end_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # If parsing completely fails, return empty list rather than crashing
    return []


class LLMClient:
    """Async wrapper for Groq LLM API."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = (api_key or settings.groq_api_key).strip()
        self.model = (model or settings.groq_model).strip()
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        if not self.api_key:
            raise ValueError(
                "Groq API key is missing. Please configure GROQ_API_KEY in your .env file."
            )
        if not _GROQ_SDK_AVAILABLE:
            raise RuntimeError(
                "Groq SDK is not installed. Please install dependencies from requirements.txt."
            )
        if self._client is None:
            self._client = AsyncGroq(api_key=self.api_key)
        return self._client

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> Any:
        """Call Groq LLM and return parsed JSON.

        Raises:
            ValueError: On missing configuration or invalid key.
            PermissionError / RuntimeError: On upstream LLM errors.
        """
        import asyncio
        client = self._get_client()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=4096,
                )
                raw_content = response.choices[0].message.content or ""
                return clean_json_response(raw_content)

            except AuthenticationError:
                raise ValueError("Invalid or expired GROQ_API_KEY. Please verify your Groq API credentials.")
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2.5
                    await asyncio.sleep(wait_time)
                    continue
                raise PermissionError("Groq API rate limit exceeded. Please wait a moment before retrying.")
            except APIError as e:
                raise RuntimeError(f"Groq API error ({e.code or 'unknown'}): {e.message}")
            except Exception as e:
                if "response_format" in str(e).lower():
                    try:
                        retry_resp = await client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=4096,
                        )
                        raw_content = retry_resp.choices[0].message.content or ""
                        return clean_json_response(raw_content)
                    except Exception as retry_err:
                        raise RuntimeError(f"LLM completion failed: {str(retry_err)}")
                raise RuntimeError(f"LLM request error: {str(e)}")
