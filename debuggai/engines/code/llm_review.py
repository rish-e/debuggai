"""LLM-powered semantic code review for AI-specific bug patterns."""

from __future__ import annotations

from typing import Optional

from debuggai.models.issues import Category, Issue, Location, Severity
from debuggai.utils.llm import analyze_code


def review_with_llm(
    file_path: str,
    content: str,
    context: str = "",
    api_key: Optional[str] = None,
) -> list[Issue]:
    """Send code to Claude for deep semantic analysis of AI-specific bugs.

    This catches issues that regex/AST patterns miss:
    - Logic errors (wrong comparisons, off-by-one, missing null checks)
    - Incomplete error handling (happy-path-only code)
    - Architectural drift (code that doesn't fit project patterns)
    - Dead code from AI iteration
    - Race conditions and concurrency bugs
    """
    result = analyze_code(
        code=content,
        context=context,
        analysis_type="ai-generated-code",
        api_key=api_key,
    )

    issues: list[Issue] = []
    for raw_issue in result.get("issues", []):
        try:
            severity_map = {
                "critical": Severity.CRITICAL,
                "major": Severity.MAJOR,
                "minor": Severity.MINOR,
                "info": Severity.INFO,
            }
            category_map = {
                "security": Category.SECURITY,
                "performance": Category.PERFORMANCE,
                "logic": Category.LOGIC,
                "import": Category.IMPORT,
                "ai_pattern": Category.AI_PATTERN,
                "style": Category.STYLE,
            }

            severity = severity_map.get(raw_issue.get("severity", "").lower(), Severity.MINOR)
            category = category_map.get(raw_issue.get("category", "").lower(), Category.LOGIC)
            line = raw_issue.get("line")

            issues.append(Issue(
                id=f"llm-{file_path}:{line or 0}-{len(issues)}",
                severity=severity,
                category=category,
                title=raw_issue.get("title", "LLM-detected issue"),
                description=raw_issue.get("description", ""),
                location=Location(file=file_path, line=line) if line else None,
                suggestion=raw_issue.get("suggestion"),
                confidence=float(raw_issue.get("confidence", 0.7)),
                engine="llm",
                rule_id="llm-review",
            ))
        except (KeyError, ValueError, TypeError):
            continue

    return issues
