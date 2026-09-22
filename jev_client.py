"""
Thin client for TypeSafe's Jev model through OpenRouter's Decisions endpoint.

Jev is not a chat model. It takes application state plus a set of typed
questions and returns one typed answer per question, with probabilities, in
a single call. The endpoint is separate from OpenRouter's chat completions
API, so `ChatOpenAI` cannot reach it; this module is the whole integration.

    POST https://openrouter.ai/api/alpha/decisions
    {"model": ..., "state": ..., "questions": {...}}
    -> {"model": ..., "answers": {...}, "usage": {...}}

The `/api/alpha/` path is OpenRouter's label, not mine: the endpoint is in
alpha and may move. Override it with JEV_ENDPOINT if it does.
"""

import os
import time
from typing import Any, Dict

import httpx

JEV_ENDPOINT = os.environ.get("JEV_ENDPOINT", "https://openrouter.ai/api/alpha/decisions")
JEV_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")


class JevError(RuntimeError):
    """Raised when the Decisions endpoint refuses or fails a request."""


def ask(state: Any, questions: Dict[str, Dict[str, Any]], timeout: float = 30.0) -> Dict[str, Any]:
    """Send one Decisions request and return the parsed response.

    Returns the full response body with two additions: `seconds` (wall-clock
    round trip) and `request` (what was sent), so the caller can log both
    next to the answers.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise JevError("OPENROUTER_API_KEY is not set")

    body = {"model": JEV_MODEL, "state": state, "questions": questions}
    started = time.perf_counter()
    try:
        response = httpx.post(
            JEV_ENDPOINT,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise JevError(f"request failed: {exc}") from exc
    elapsed = time.perf_counter() - started

    if response.status_code != 200:
        raise JevError(f"HTTP {response.status_code}: {response.text[:300]}")

    data = response.json()
    if "answers" not in data:
        raise JevError(f"no answers in response: {str(data)[:300]}")

    data["seconds"] = round(elapsed, 3)
    data["request"] = body
    return data
