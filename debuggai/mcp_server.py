"""DebuggAI MCP Server — Python-native, no npm required.

Run with: debuggai serve
Or point your MCP config to: python -m debuggai.mcp_server
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "DebuggAI",
    version="3.2.0",
    description="The universal verification layer for AI-generated software",
)


def _validate_path(target: str) -> str:
    """Validate and resolve target path. Prevents scanning outside project scope."""
    resolved = Path(target).resolve()
    cwd = Path.cwd().resolve()
    # Allow scanning cwd or subdirectories, or explicit absolute paths the user provides
    if not str(resolved).startswith(str(cwd)) and target not in (".", "./"):
        # Allow if it's a real directory the user likely intends
        if resolved.exists() and resolved.is_dir():
            return str(resolved)
        raise ValueError(f"Target path '{target}' is outside the current project directory.")
    return str(resolved)


# ─── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def scan_code(
    target: str = ".",
    diff: str | None = None,
    staged: bool = False,
    no_llm: bool = False,
    strict: bool = False,
) -> str:
    """Scan code for AI-generated bugs, security issues, and performance problems.

    Args:
        target: File or directory to scan (defaults to current directory)
        diff: Git ref to diff against (e.g., "HEAD~1")
        staged: Scan staged changes only
        no_llm: Skip LLM analysis for faster results
        strict: Report all severities including minor and info
    """
    from debuggai.orchestrator import run_scan
    from debuggai.reports.generator import format_markdown

    if strict:
        os.environ["DEBUGGAI_STRICTNESS"] = "high"

    report = run_scan(
        target=target if target != "." else None,
        diff_ref=diff,
        staged=staged,
        use_llm=not no_llm,
    )

    return format_markdown(report)


@mcp.tool()
def verify_intent(
    intent: str,
    target: str | None = None,
    diff: str | None = None,
) -> str:
    """Verify code matches a natural language intent. Returns Prompt Fidelity Score.

    Args:
        intent: What the code should do (e.g., "add user authentication with OAuth")
        target: File or directory to verify against
        diff: Git ref to verify against
    """
    from debuggai.orchestrator import run_scan
    from debuggai.reports.generator import format_markdown

    report = run_scan(
        target=target,
        diff_ref=diff,
        intent=intent,
        use_llm=True,
    )

    return format_markdown(report)


@mcp.tool()
def get_report(
    target: str | None = None,
    diff: str | None = None,
    no_llm: bool = True,
) -> str:
    """Get a full DebuggAI report in JSON format for programmatic analysis.

    Args:
        target: File or directory to scan
        diff: Git ref to diff against
        no_llm: Skip LLM analysis (default: True for speed)
    """
    from debuggai.orchestrator import run_scan
    from debuggai.reports.generator import format_json

    report = run_scan(
        target=target,
        diff_ref=diff,
        use_llm=not no_llm,
    )

    return format_json(report)


@mcp.tool()
def init_project(directory: str = ".") -> str:
    """Initialize DebuggAI for a project. Auto-detects languages and creates config.

    Args:
        directory: Project directory (defaults to current directory)
    """
    from debuggai.config import generate_default_config, auto_detect_languages

    project_dir = str(Path(directory).resolve())
    config_path = Path(project_dir) / ".debuggai.yaml"

    if config_path.exists():
        return f"Config already exists at {config_path}. Delete it first to reinitialize."

    config_content = generate_default_config(project_dir)
    config_path.write_text(config_content)

    langs = auto_detect_languages(project_dir)
    return (
        f"Initialized DebuggAI in {project_dir}\n"
        f"Config written to: {config_path}\n"
        f"Detected languages: {', '.join(langs) if langs else 'none'}\n"
        f"\nUse /scan to analyze your code."
    )


@mcp.tool()
def fix_issues(
    target: str = ".",
    min_confidence: float = 0.7,
    auto_apply: bool = False,
) -> str:
    """Generate fixes for detected issues. Optionally auto-apply high-confidence fixes.

    Args:
        target: File or directory to fix
        min_confidence: Minimum confidence threshold for fixes (0.0-1.0)
        auto_apply: If True, automatically apply fixes to files
    """
    from debuggai.config import load_config
    from debuggai.orchestrator import run_scan
    from debuggai.engines.fix import generate_fixes_for_issues, apply_fix

    cfg = load_config()
    if not cfg.anthropic_api_key:
        return "Auto-fix requires ANTHROPIC_API_KEY environment variable."

    report = run_scan(target=target if target != "." else None, use_llm=False)
    if not report.issues:
        return "No issues found — nothing to fix!"

    project_dir = str(Path(target).resolve()) if Path(target).is_dir() else str(Path.cwd())
    fixes = generate_fixes_for_issues(
        report.issues, project_dir, api_key=cfg.anthropic_api_key, min_confidence=min_confidence,
    )

    if not fixes:
        return f"Found {len(report.issues)} issues but could not generate fixes."

    result = f"Generated {len(fixes)} fixes:\n\n"
    for i, f in enumerate(fixes):
        result += f"**Fix {i+1}** (confidence: {f['confidence']:.0%})\n"
        result += f"[{f['severity'].upper()}] {f['issue_title']} — {f['file']}:{f['line']}\n"
        result += f"{f['explanation']}\n"
        if f.get("old_code") and f.get("new_code"):
            result += f"```diff\n- {f['old_code']}\n+ {f['new_code']}\n```\n"

        if auto_apply:
            if apply_fix(f, project_dir):
                result += "Applied successfully.\n"
            else:
                result += "Failed to apply.\n"
        result += "\n"

    return result


@mcp.tool()
def show_history(limit: int = 10) -> str:
    """Show scan history and quality trends for the current project.

    Args:
        limit: Number of recent scans to show
    """
    from debuggai.storage import get_db, get_scan_history, get_quality_delta

    db = get_db()
    scans = get_scan_history(db, limit=limit)
    delta = get_quality_delta(db, project=scans[0]["project"] if scans else "")
    db.close()

    if not scans:
        return "No scan history yet. Run a scan first."

    result = "DebuggAI Scan History\n\n"

    if delta:
        d = delta
        result += f"Since last scan: {d['delta_total']:+d} issues ({d['new_issues']} new, {d['fixed_issues']} fixed)\n\n"

    result += f"{'Timestamp':<22} {'Issues':>6} {'Crit':>5} {'Major':>6}\n"
    result += f"{'─'*22} {'─'*6} {'─'*5} {'─'*6}\n"
    for s in scans:
        ts = s["timestamp"][:19] if s["timestamp"] else "?"
        result += f"{ts:<22} {s['total_issues']:>6} {s['critical']:>5} {s['major']:>6}\n"

    return result


@mcp.tool()
def dismiss_rule(rule_id: str, file_pattern: str | None = None, reason: str = "") -> str:
    """Dismiss an issue rule. After 3 dismissals of the same rule, it auto-suppresses.

    Args:
        rule_id: The rule ID to dismiss (e.g., "xss-innerhtml", "nested-loop-on2")
        file_pattern: Only dismiss for files matching this pattern
        reason: Why this rule is being dismissed
    """
    from debuggai.storage import get_db, dismiss_issue, get_dismissals

    db = get_db()
    dismiss_issue(db, rule_id, file_pattern, reason)
    dismissals = get_dismissals(db)
    db.close()

    for d in dismissals:
        if d["rule_id"] == rule_id:
            if d["auto_suppress"]:
                return f"Rule '{rule_id}' is now auto-suppressed (dismissed {d['count']}x). It won't appear in future scans."
            else:
                remaining = 3 - d["count"]
                return f"Rule '{rule_id}' dismissed ({d['count']}x). {remaining} more dismissal(s) to auto-suppress."

    return f"Rule '{rule_id}' dismissed."


@mcp.tool()
def deep_analysis(
    target: str = ".",
    focus: str = "all",
    no_llm: bool = False,
) -> str:
    """Run deep architectural analysis — finds system-level bugs that pattern matching misses.

    This analyzes the entire project holistically: deployment model, runtime behavior,
    memory leaks, race conditions, architectural anti-patterns, and domain-specific issues.

    Args:
        target: Project directory to analyze (defaults to current directory)
        focus: Analysis focus — "all", "security", "performance", "deployment"
        no_llm: Skip LLM holistic review for faster/cheaper results
    """
    from debuggai.engines.deep.engine import run_deep_analysis
    from debuggai.reports.generator import format_markdown

    report = run_deep_analysis(
        project_dir=str(Path(target).resolve()) if target != "." else None,
        focus=focus,
        use_llm=not no_llm,
    )

    result = ""
    if report.architecture_summary:
        result += f"## Architecture\n{report.architecture_summary}\n\n"

    result += format_markdown(report)
    return result


@mcp.tool()
def discover_personas(target: str = ".") -> str:
    """Discover who uses this software. Identifies ICPs (Ideal Customer Personas) from the codebase.

    Reads README, UI patterns, features, and config to infer target personas.

    Args:
        target: Project directory to analyze
    """
    from debuggai.engines.persona.engine import run_persona_analysis

    project_dir = str(Path(target).resolve()) if target != "." else None
    profile, _ = run_persona_analysis(project_dir=project_dir, discover_only=True)

    result = f"## Personas for {profile.project_name} ({profile.app_type})\n\n"
    for i, p in enumerate(profile.personas, 1):
        result += f"### {i}. {p.name} ({p.role})\n"
        result += f"**Tech level:** {p.tech_level}\n"
        result += f"{p.description}\n"
        if p.goals:
            result += f"**Goals:** {', '.join(p.goals)}\n"
        if p.pain_points:
            result += f"**Pain points:** {', '.join(p.pain_points)}\n"
        if p.key_flows:
            result += f"**Key flows:** {', '.join(p.key_flows)}\n"
        result += "\n"

    return result


@mcp.tool()
def persona_test(
    target: str = ".",
    persona_name: str | None = None,
) -> str:
    """Test software from the customer's perspective. Finds UX issues specific to each persona.

    Discovers who uses this software, then checks for persona-specific problems:
    technical jargon in UI, missing loading states, mobile issues, accessibility gaps, etc.

    Args:
        target: Project directory to analyze
        persona_name: Specific persona to test for (or all if not specified)
    """
    from debuggai.engines.persona.engine import run_persona_analysis
    from debuggai.reports.generator import format_markdown

    project_dir = str(Path(target).resolve()) if target != "." else None
    profile, report = run_persona_analysis(
        project_dir=project_dir,
        persona_name=persona_name,
    )

    result = f"## Persona Test — {profile.project_name}\n\n"
    result += f"**App type:** {profile.app_type}\n"
    result += f"**Personas tested:** {', '.join(p.name for p in profile.personas)}\n\n"

    if report:
        result += format_markdown(report)

    return result


@mcp.tool()
def start_persona_session(
    url: str,
    target: str = ".",
    persona_name: str | None = None,
) -> str:
    """Start a live persona testing session. Opens a real browser and navigates to the URL.

    This is FREE — uses your existing Claude Code tokens, no API key needed.

    After calling this, you'll receive a screenshot and page info. Evaluate it as the persona,
    then call execute_persona_action() with what the persona would do next. Repeat until the
    persona completes their task or gives up. Finally call end_persona_session() for the report.

    The loop: start_persona_session → [evaluate screenshot → execute_persona_action] × N → end_persona_session

    Args:
        url: The URL to test (e.g., http://localhost:3000)
        target: Project directory for persona discovery
        persona_name: Persona to test as (discovers from codebase if not specified)
    """
    from debuggai.engines.persona.discover import discover_personas
    from debuggai.engines.persona.agent import start_session

    project_dir = str(Path(target).resolve()) if target != "." else str(Path.cwd())
    profile = discover_personas(project_dir)

    # Pick persona
    persona = profile.personas[0] if profile.personas else None
    if persona_name:
        matching = [p for p in profile.personas if persona_name.lower() in p.name.lower()]
        if matching:
            persona = matching[0]

    if not persona:
        return "No personas discovered. Specify one with persona_name."

    result = start_session(
        url=url,
        persona_name=persona.name,
        persona_description=persona.description,
        persona_tech_level=persona.tech_level,
        persona_goal=persona.goals[0] if persona.goals else "Explore the application",
    )

    if result.get("error"):
        return f"Error: {result['error']}"

    # Format for Claude Code to evaluate
    output = f"## Live Persona Session Started\n\n"
    output += f"**Persona:** {persona.name} ({persona.tech_level})\n"
    output += f"**Goal:** {persona.goals[0] if persona.goals else 'Explore'}\n"
    output += f"**URL:** {url}\n"
    output += f"**Page:** {result.get('title', '?')}\n\n"
    output += f"**Interactive elements:** {', '.join(result.get('interactive_elements', [])[:15])}\n\n"
    output += f"**Visible text excerpt:** {result.get('visible_text', '')[:500]}\n\n"
    output += "Now evaluate this page AS the persona. What would they see? Is it clear? Any friction?\n"
    output += "Then call execute_persona_action() with the persona's next action."

    return [
        {"type": "text", "text": output},
        {"type": "image", "data": result.get("screenshot_base64", ""), "mimeType": "image/png"},
    ]


@mcp.tool()
def execute_persona_action(
    action: str,
    target: str = "",
    feeling: str = "smooth",
    observation: str = "",
    friction: str = "",
    reasoning: str = "",
) -> str:
    """Execute the persona's next action and capture the new page state.

    Call this after evaluating a screenshot from the persona's perspective.
    Returns a new screenshot for you to evaluate again.

    Args:
        action: What the persona does — click, type, scroll, back, done (task complete), give_up (too frustrated)
        target: What to click or type (element text, button label, or "text in field_name")
        feeling: How the persona felt about the page — smooth, confused, frustrated, lost
        observation: What the persona noticed on the page
        friction: Any friction point (or empty if smooth)
        reasoning: Why the persona chose this action
    """
    from debuggai.engines.persona.agent import execute_persona_action as _execute

    result = _execute(
        action=action, target=target, feeling=feeling,
        observation=observation, friction=friction or None, reasoning=reasoning,
    )

    if result.get("error"):
        return f"Error: {result['error']}"

    # Terminal actions
    if result.get("status") in ("done", "give_up"):
        return f"Persona action: {result['status']}. Call end_persona_session() to get the experience report."

    output = f"**Step {result.get('step', '?')}** — Action: {action} '{target}'\n"
    output += f"**Page:** {result.get('title', '?')} ({result.get('url', '')})\n"
    output += f"**Action succeeded:** {result.get('action_success', '?')}\n\n"
    output += f"**Interactive elements:** {', '.join(result.get('interactive_elements', [])[:15])}\n\n"
    output += f"**Visible text:** {result.get('visible_text', '')[:500]}\n\n"
    output += "Evaluate this page AS the persona, then call execute_persona_action() again."

    return [
        {"type": "text", "text": output},
        {"type": "image", "data": result.get("screenshot_base64", ""), "mimeType": "image/png"},
    ]


@mcp.tool()
def end_persona_session() -> str:
    """End the live persona testing session and get the experience report.

    Call this after the persona completes their task (action: done) or gives up (action: give_up).
    Returns a full experience report with step-by-step journey, friction points, and score.
    """
    from debuggai.engines.persona.agent import end_session

    report = end_session()
    return report.format_markdown()


# ─── Prompts (slash commands) ─────────────────────────────────────────────────


@mcp.prompt()
def scan(target: str = ".", strict: bool = False) -> str:
    """Scan the current project for AI-generated code bugs, security issues, and performance problems."""
    parts = [f"Run the scan_code tool on target=\"{target}\""]
    if strict:
        parts.append(" with strict=True")
    parts.append(
        ". After getting results, present the findings clearly — "
        "group by severity, highlight critical issues first, and include fix suggestions."
    )
    return "".join(parts)


@mcp.prompt()
def verify(intent: str, target: str = ".") -> str:
    """Verify that code matches what you asked the AI to build. Returns a Prompt Fidelity Score."""
    return (
        f'Run the verify_intent tool with intent="{intent}" and target="{target}". '
        "Present the Prompt Fidelity Score prominently, then show each assertion with its "
        "pass/fail status. For failed assertions, explain what's missing and suggest fixes."
    )


@mcp.prompt()
def init(directory: str = ".") -> str:
    """Initialize DebuggAI for a project. Auto-detects languages and creates config."""
    return (
        f'Run the init_project tool with directory="{directory}". '
        "Show the user what was detected and configured."
    )


@mcp.prompt()
def fix(target: str = ".") -> str:
    """Generate and apply fixes for detected issues."""
    return (
        f'Run the fix_issues tool with target="{target}". '
        "Show each fix with its confidence score, the before/after code, and explanation. "
        "Ask the user if they want to apply the fixes."
    )


@mcp.prompt()
def history() -> str:
    """Show scan history and quality trends."""
    return (
        "Run the show_history tool. Present the results as a clean table "
        "and highlight any trends (improving or degrading quality)."
    )


@mcp.prompt()
def deep(target: str = ".", focus: str = "all") -> str:
    """Run deep architectural analysis — finds system-level bugs that pattern matching misses."""
    return (
        f'Run the deep_analysis tool with target="{target}" and focus="{focus}". '
        "Present the architecture summary first, then group findings by category "
        "(architectural, runtime, domain-specific). For each finding, explain the "
        "causal chain — why it's a bug, what happens at runtime, and how to fix it."
    )


@mcp.prompt()
def persona(target: str = ".") -> str:
    """Test your software from the customer's perspective. Discovers who uses it and finds UX issues they'd encounter."""
    return (
        f'First run the discover_personas tool with target="{target}" to identify who uses this software. '
        "Present each persona clearly with their goals, pain points, and key flows. "
        f'Then run the persona_test tool with target="{target}" to find UX issues. '
        "Group findings by persona. For each finding, explain why THIS persona would be affected "
        "and what the impact is from THEIR perspective — not a developer's."
    )


@mcp.prompt()
def persona_live(url: str, target: str = ".") -> str:
    """Test a live website from the customer's perspective — FREE, uses your existing Claude Code tokens.

    Opens a real browser, shows you screenshots, and you evaluate each page as the persona.
    """
    return (
        f'Call start_persona_session with url="{url}" and target="{target}". '
        "This opens a browser and returns a screenshot.\n\n"
        "For each screenshot:\n"
        "1. Look at the screenshot as the persona (their tech level, goals, pain points)\n"
        "2. Evaluate: is the page clear? Is there friction? What would they do next?\n"
        "3. Call execute_persona_action with:\n"
        "   - action: click/type/scroll/back/done/give_up\n"
        "   - target: what to interact with\n"
        "   - feeling: smooth/confused/frustrated/lost\n"
        "   - observation: what you saw\n"
        "   - friction: any issues (or empty)\n"
        "4. Repeat until the persona completes their task or gives up\n"
        "5. Call end_persona_session to get the experience report\n\n"
        "Stay in character as the persona throughout. Think about what THEY would notice, "
        "not what a developer would notice."
    )


# ─── Entry point ──────────────────────────────────────────────────────────────


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
