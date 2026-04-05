"""Holistic LLM analysis — sends full project context for architectural review.

This is the "senior engineer" mode. The LLM sees the entire project at once
and reasons about system-level issues that file-by-file scanning misses.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from debuggai.engines.deep.indexer import ProjectIndex
from debuggai.models.issues import Category, Issue, Location, Severity


def run_holistic_review(
    index: ProjectIndex,
    focus: str = "all",
    api_key: Optional[str] = None,
) -> list[Issue]:
    """Send full project context to Claude for architectural analysis.

    Args:
        index: The indexed project
        focus: Analysis focus — "all", "security", "performance", "deployment"
        api_key: Anthropic API key
    """
    if not api_key:
        return []

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    context = index.to_context_string(max_chars=150000)

    focus_instructions = {
        "all": "Analyze for ALL categories: security, performance, runtime behavior, architectural anti-patterns, missing safeguards, and dead code.",
        "security": "Focus on SECURITY: auth flows, data exposure, injection vectors, CORS, secrets, session management, API abuse vectors.",
        "performance": "Focus on PERFORMANCE: memory leaks, unnecessary re-renders, unoptimized queries, missing caching, resource lifecycle issues, encoding efficiency.",
        "deployment": f"Focus on DEPLOYMENT: this runs on {index.context.deployment or 'unknown'}. Find issues specific to this deployment model — stateful code in stateless env, timeout mismatches, cold start problems, resource limits.",
    }

    system_prompt = f"""You are DebuggAI's Deep Analysis Engine — a senior software engineer reviewing an entire project for system-level bugs.

You are NOT a linter. You understand architecture, deployment models, runtime behavior, and how code interacts across files. You find bugs that no pattern-matching tool can catch.

{focus_instructions.get(focus, focus_instructions["all"])}

For each issue found, return a JSON object with:
- severity: "critical" | "major" | "minor" | "info"
- category: "security" | "performance" | "logic" | "ai_pattern"
- title: concise issue title
- description: detailed explanation including WHY this is a problem and what happens at runtime
- file: primary file where the issue manifests
- line: approximate line number (if applicable)
- suggestion: specific fix with code example if possible
- confidence: 0.0 to 1.0

IMPORTANT:
- Only report issues you're genuinely confident about
- Explain the causal chain (e.g., "X happens because Y, which causes Z")
- Cross-reference findings across files
- Consider what happens when operations run multiple times
- Think about failure modes (what if external service is down?)
- Consider the deployment model's constraints

Return a JSON array of issues. Return [] if no significant issues found."""

    user_msg = f"""Perform a deep architectural analysis of this project.

{f"Architecture summary: {index.architecture_summary}" if index.architecture_summary else ""}

Full project context:

{context}

Return ONLY a JSON array of issues."""

    response = client.messages.create(
        model=os.environ.get("DEBUGGAI_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text

    # Parse response
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        raw_issues = json.loads(text.strip())
    except (json.JSONDecodeError, IndexError):
        return []

    issues: list[Issue] = []
    severity_map = {
        "critical": Severity.CRITICAL, "major": Severity.MAJOR,
        "minor": Severity.MINOR, "info": Severity.INFO,
    }
    category_map = {
        "security": Category.SECURITY, "performance": Category.PERFORMANCE,
        "logic": Category.LOGIC, "ai_pattern": Category.AI_PATTERN,
    }

    for i, raw in enumerate(raw_issues):
        try:
            sev = severity_map.get(raw.get("severity", "major").lower(), Severity.MAJOR)
            cat = category_map.get(raw.get("category", "logic").lower(), Category.LOGIC)
            file_path = raw.get("file", "")
            line = raw.get("line")

            issues.append(Issue(
                id=f"deep-holistic-{i}-{file_path}:{line or 0}",
                severity=sev,
                category=cat,
                title=raw.get("title", "Deep analysis finding"),
                description=raw.get("description", ""),
                location=Location(file=file_path, line=line) if file_path else None,
                suggestion=raw.get("suggestion"),
                confidence=float(raw.get("confidence", 0.7)),
                engine="deep-holistic",
                rule_id="holistic-review",
            ))
        except (KeyError, ValueError, TypeError):
            continue

    return issues
