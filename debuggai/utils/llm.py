"""Claude API wrapper for DebuggAI."""

from __future__ import annotations

import json
from typing import Any, Optional

import anthropic

_client: Optional[anthropic.Anthropic] = None


def get_client(api_key: Optional[str] = None) -> anthropic.Anthropic:
    """Get or create the Anthropic client."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def analyze_code(
    code: str,
    context: str = "",
    analysis_type: str = "general",
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Send code to Claude for AI-specific analysis.

    Returns structured analysis results.
    """
    client = get_client(api_key)

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

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    # Extract JSON from response
    text = response.content[0].text
    # Try to find JSON array in the response
    try:
        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return {"issues": json.loads(text.strip())}
    except (json.JSONDecodeError, IndexError):
        return {"issues": [], "raw_response": text}


def extract_intent_assertions(
    intent: str,
    code_context: str = "",
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Extract testable assertions from a natural language intent."""
    client = get_client(api_key)

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

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except (json.JSONDecodeError, IndexError):
        return []


def verify_assertion(
    assertion: dict[str, Any],
    code: str,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Verify a single assertion against code."""
    client = get_client(api_key)

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

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except (json.JSONDecodeError, IndexError):
        return {"status": "unknown", "evidence": "Could not parse response", "score": 0.0}
