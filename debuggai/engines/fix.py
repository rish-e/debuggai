"""Auto-fix engine — generate and apply fix diffs for detected issues."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from debuggai.models.issues import Issue


def generate_fix(
    issue: Issue,
    file_content: str,
    project_dir: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """Generate a fix for an issue using Claude.

    Returns:
        {
            "file": str,
            "line": int,
            "old_code": str,
            "new_code": str,
            "explanation": str,
            "confidence": float,  # 0.0-1.0
        }
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    loc = issue.location
    if not loc:
        return None

    # Extract surrounding context (10 lines before/after the issue)
    lines = file_content.split("\n")
    start = max(0, (loc.line or 1) - 11)
    end = min(len(lines), (loc.line or 1) + 10)
    context = "\n".join(f"{i+1}: {lines[i]}" for i in range(start, end))

    response = client.messages.create(
        model=os.environ.get("DEBUGGAI_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=2048,
        system="""You are DebuggAI's auto-fix engine. Given a code issue and its surrounding context,
generate a minimal, correct fix. Return ONLY a JSON object with:
- old_code: the exact lines to replace (as they appear in the file, no line numbers)
- new_code: the replacement code
- explanation: one sentence explaining the fix
- confidence: 0.0-1.0 (how confident you are this fix is correct and won't break anything)

Rules:
- Make the SMALLEST change possible. Don't refactor surrounding code.
- old_code must be an exact substring of the file content.
- Preserve indentation exactly.
- If you're not confident, set confidence below 0.5.
- Return ONLY the JSON object, no markdown.""",
        messages=[{
            "role": "user",
            "content": f"""Fix this issue:

**Issue:** [{issue.severity.value.upper()}] {issue.title}
**Description:** {issue.description}
**Suggestion:** {issue.suggestion or "None"}
**File:** {loc.file}
**Line:** {loc.line}

**Code context:**
```
{context}
```

**Full file path:** {loc.file}

Return a JSON fix object.""",
        }],
    )

    text = response.content[0].text
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        fix = json.loads(text.strip())

        # Validate the old_code actually exists in the file
        if fix.get("old_code") and fix["old_code"] not in file_content:
            # Try stripping trailing whitespace from each line
            old_lines = [l.rstrip() for l in fix["old_code"].split("\n")]
            file_lines = [l.rstrip() for l in file_content.split("\n")]
            old_stripped = "\n".join(old_lines)
            file_stripped = "\n".join(file_lines)
            if old_stripped not in file_stripped:
                fix["confidence"] = max(0.0, fix.get("confidence", 0.5) - 0.3)

        return {
            "file": loc.file,
            "line": loc.line,
            "old_code": fix.get("old_code", ""),
            "new_code": fix.get("new_code", ""),
            "explanation": fix.get("explanation", ""),
            "confidence": float(fix.get("confidence", 0.5)),
        }
    except (json.JSONDecodeError, IndexError, KeyError):
        return None


def apply_fix(fix: dict, project_dir: Optional[str] = None) -> bool:
    """Apply a fix to the file on disk.

    Returns True if applied successfully.
    """
    file_path = Path(project_dir or ".") / fix["file"]
    if not file_path.exists():
        return False

    content = file_path.read_text()
    old_code = fix["old_code"]
    new_code = fix["new_code"]

    if not old_code or old_code not in content:
        return False

    new_content = content.replace(old_code, new_code, 1)
    file_path.write_text(new_content)
    return True


def generate_fixes_for_issues(
    issues: list[Issue],
    project_dir: str,
    api_key: Optional[str] = None,
    min_confidence: float = 0.5,
) -> list[dict]:
    """Generate fixes for all issues that have locations.

    Returns list of fix dicts, filtered by minimum confidence.
    """
    fixes = []
    for issue in issues:
        if not issue.location or not issue.location.file:
            continue

        file_path = Path(project_dir) / issue.location.file
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        fix = generate_fix(issue, content, project_dir=project_dir, api_key=api_key)
        if fix and fix.get("confidence", 0) >= min_confidence:
            fix["issue_id"] = issue.id
            fix["issue_title"] = issue.title
            fix["severity"] = issue.severity.value
            fixes.append(fix)

    return fixes
