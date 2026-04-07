"""Claude API wrapper for DebuggAI."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import anthropic

logger = logging.getLogger("debuggai")

_client: Optional[anthropic.Anthropic] = None
_cached_key: Optional[str] = None

# Model can be overridden via env var
DEFAULT_MODEL = "claude-sonnet-4-20250514"


def get_model() -> str:
    """Get the model to use, allowing env var override."""
    return os.environ.get("DEBUGGAI_MODEL", DEFAULT_MODEL)


def get_client(api_key: Optional[str] = None) -> anthropic.Anthropic:
    """Get or create the Anthropic client. Recreates if key changes."""
    global _client, _cached_key
    if _client is None or (api_key and api_key != _cached_key):
        _client = anthropic.Anthropic(api_key=api_key)
        _cached_key = api_key
    return _client


def _parse_json_response(text: str) -> Any:
    """Extract JSON from an LLM response, handling markdown code blocks."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


def _safe_llm_call(func):
    """Decorator that catches API errors and returns graceful fallback."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except anthropic.APIConnectionError as e:
            logger.warning("DebuggAI: Cannot connect to Anthropic API: %s", e)
            return kwargs.get("fallback", func.__defaults__[-1] if func.__defaults__ else None)
        except anthropic.RateLimitError:
            logger.warning("DebuggAI: Anthropic API rate limit hit. Skipping LLM analysis.")
            return kwargs.get("fallback", None)
        except anthropic.APIStatusError as e:
            logger.warning("DebuggAI: Anthropic API error (status %s): %s", e.status_code, e.message)
            return kwargs.get("fallback", None)
    return wrapper


def analyze_code(
    code: str,
    context: str = "",
    analysis_type: str = "general",
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Send code to Claude for AI-specific analysis."""
    try:
        client = get_client(api_key)
    except anthropic.AuthenticationError:
        logger.warning("DebuggAI: Invalid Anthropic API key. Skipping LLM review.")
        return {"issues": []}

    system_prompt = """You are DebuggAI, an expert code analyzer specializing in detecting bugs
in AI-generated code. You focus on issues that AI coding tools commonly introduce:

1. HALLUCINATED APIs: Imports or function calls to modules/functions that don't exist
2. INCOMPLETE ERROR HANDLING: Happy-path-only code missing error cases
3. LOGIC ERRORS: Off-by-one, wrong comparisons, missing null checks, race conditions
4. SECURITY ISSUES: XSS, SQL injection, hardcoded secrets, command injection
5. PERFORMANCE: O(n²) loops, N+1 queries, excessive I/O, missing async
6. ARCHITECTURAL DRIFT: Code that doesn't match project patterns/conventions
7. DEAD CODE: Unused variables, unreachable branches from AI iteration

Return your analysis as a JSON array of issues. Each issue must have:
- severity: "critical" | "major" | "minor" | "info"
- category: "security" | "performance" | "logic" | "import" | "ai_pattern" | "style"
- title: short description
- description: detailed explanation
- line: line number (if applicable)
- suggestion: how to fix it
- confidence: 0.0 to 1.0

Only report real issues. Do NOT report style preferences or subjective opinions.
Be precise about line numbers. If unsure, set confidence below 0.7."""

    user_msg = f"""Analyze this code for AI-generated code bugs.

Analysis focus: {analysis_type}

{f"Project context: {context}" if context else ""}

Code to analyze:
```
{code}
```

Return ONLY a JSON array of issues found. Return [] if no issues."""

    try:
        response = client.messages.create(
            model=get_model(),
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text
        return {"issues": _parse_json_response(text)}
    except (anthropic.APIError, anthropic.APIConnectionError) as e:
        logger.warning("DebuggAI: LLM analysis failed: %s", e)
        return {"issues": []}
    except (json.JSONDecodeError, IndexError):
        return {"issues": []}


def extract_intent_assertions(
    intent: str,
    code_context: str = "",
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Extract testable assertions from a natural language intent."""
    try:
        client = get_client(api_key)
    except anthropic.AuthenticationError:
        logger.warning("DebuggAI: Invalid API key. Skipping intent extraction.")
        return []

    system_prompt = """You are DebuggAI's intent parser. Given a natural language description of
what code should do, extract specific, testable assertions.

Each assertion should have:
- type: "dependency" | "route" | "behavior" | "security" | "function" | "file" | "pattern" | "ui"
- description: what this assertion checks
- expect: what we expect to find in the code
- importance: 0.0 to 1.0 (how critical this assertion is)

Extract 3-10 assertions. Focus on concrete, verifiable things.

Return ONLY a JSON array of assertions."""

    user_msg = f"""Extract testable assertions from this intent:

Intent: "{intent}"

{f"Code context (what exists in the project): {code_context}" if code_context else ""}

Return ONLY a JSON array of assertions."""

    try:
        response = client.messages.create(
            model=get_model(),
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        return _parse_json_response(response.content[0].text)
    except (anthropic.APIError, anthropic.APIConnectionError) as e:
        logger.warning("DebuggAI: Intent extraction failed: %s", e)
        return []
    except (json.JSONDecodeError, IndexError):
        return []


def verify_assertion(
    assertion: dict[str, Any],
    code: str,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Verify a single assertion against code."""
    try:
        client = get_client(api_key)
    except anthropic.AuthenticationError:
        return {"status": "unknown", "evidence": "Invalid API key", "score": 0.0}

    system_prompt = """You are DebuggAI's assertion verifier. Given an assertion about what code
should contain/do, and the actual code, determine if the assertion is satisfied.

Return a JSON object with:
- status: "pass" | "fail" | "partial" | "unknown"
- evidence: what was found (or not found)
- location: where in the code (file:line if possible)
- score: 0.0 to 1.0 (how well satisfied)

Be precise. Only mark "pass" if clearly satisfied. "partial" if partially done."""

    user_msg = f"""Verify this assertion against the code:

Assertion:
- Type: {assertion.get('type')}
- Description: {assertion.get('description')}
- Expected: {assertion.get('expect')}

Code:
```
{code}
```

Return ONLY a JSON object with status, evidence, location, score."""

    try:
        response = client.messages.create(
            model=get_model(),
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        return _parse_json_response(response.content[0].text)
    except (anthropic.APIError, anthropic.APIConnectionError) as e:
        logger.warning("DebuggAI: Assertion verification failed: %s", e)
        return {"status": "unknown", "evidence": str(e), "score": 0.0}
    except (json.JSONDecodeError, IndexError):
        return {"status": "unknown", "evidence": "Could not parse response", "score": 0.0}
