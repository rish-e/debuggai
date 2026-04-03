"""Report generator — produce formatted output from analysis results."""

from __future__ import annotations

import json
from typing import Optional

from debuggai.models.assertions import AssertionStatus, IntentSpec
from debuggai.models.issues import Issue, Severity
from debuggai.models.reports import Report


def generate_report(
    issues: list[Issue],
    target: str,
    intent: Optional[IntentSpec] = None,
    project_name: Optional[str] = None,
    scan_duration_ms: Optional[int] = None,
) -> Report:
    """Create a Report from analysis results."""
    report = Report(
        target=target,
        project=project_name,
        issues=issues,
        intent=intent,
    )
    summary = report.build_summary()
    if scan_duration_ms is not None:
        summary.scan_duration_ms = scan_duration_ms
    return report


def format_json(report: Report) -> str:
    """Format report as JSON."""
    return report.model_dump_json(indent=2)


def format_markdown(report: Report) -> str:
    """Format report as Markdown."""
    lines: list[str] = []
    summary = report.summary

    lines.append(f"# DebuggAI Report")
    if report.project:
        lines.append(f"**Project:** {report.project}")
    lines.append(f"**Target:** {report.target}")
    lines.append(f"**Timestamp:** {report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if summary.scan_duration_ms:
        lines.append(f"**Duration:** {summary.scan_duration_ms}ms")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Severity | Count |")
    lines.append(f"|----------|-------|")
    lines.append(f"| Critical | {summary.critical} |")
    lines.append(f"| Major | {summary.major} |")
    lines.append(f"| Minor | {summary.minor} |")
    lines.append(f"| Info | {summary.info} |")
    lines.append(f"| **Total** | **{summary.total_issues}** |")
    lines.append("")

    if summary.fidelity_score is not None:
        lines.append(f"**Prompt Fidelity Score:** {summary.fidelity_score}/100")
        lines.append("")

    # Issues by severity
    if report.issues:
        lines.append("## Issues")
        lines.append("")

        for severity in [Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.INFO]:
            severity_issues = [i for i in report.issues if i.severity == severity]
            if not severity_issues:
                continue

            icon = {"critical": "!!!", "major": "!!", "minor": "!", "info": "i"}[severity.value]
            lines.append(f"### [{icon}] {severity.value.upper()} ({len(severity_issues)})")
            lines.append("")

            for issue in severity_issues:
                loc = ""
                if issue.location:
                    loc = f" `{issue.location.file}"
                    if issue.location.line:
                        loc += f":{issue.location.line}"
                    loc += "`"

                lines.append(f"- **[{issue.category.value.upper()}]** {issue.title}{loc}")
                lines.append(f"  {issue.description}")
                if issue.suggestion:
                    lines.append(f"  > Fix: {issue.suggestion}")
                lines.append("")

    # Intent results
    if report.intent and report.intent.results:
        lines.append("## Intent Verification")
        lines.append("")
        lines.append(f"**Intent:** {report.intent.raw_intent}")
        lines.append(f"**Fidelity Score:** {report.intent.fidelity_score}/100")
        lines.append("")

        for result in report.intent.results:
            icon = {
                "pass": "+",
                "fail": "x",
                "partial": "~",
                "unknown": "?",
            }[result.status.value]
            lines.append(f"- [{icon}] {result.assertion.description}")
            lines.append(f"  Expected: {result.assertion.expect}")
            if result.evidence:
                lines.append(f"  Found: {result.evidence}")
            lines.append("")

    return "\n".join(lines)


def format_terminal(report: Report) -> str:
    """Format report for terminal output with colors via Rich markup."""
    lines: list[str] = []
    summary = report.summary

    lines.append("")
    lines.append("[bold]DebuggAI Report[/bold]")
    if report.project:
        lines.append(f"[dim]Project:[/dim] {report.project}")
    lines.append(f"[dim]Target:[/dim] {report.target}")
    if summary.scan_duration_ms:
        lines.append(f"[dim]Duration:[/dim] {summary.scan_duration_ms}ms")
    lines.append("")

    # Score line
    if summary.fidelity_score is not None:
        color = "green" if summary.fidelity_score >= 80 else "yellow" if summary.fidelity_score >= 50 else "red"
        lines.append(f"[bold]Prompt Fidelity Score:[/bold] [{color}]{summary.fidelity_score}/100[/{color}]")

    # Summary counts
    parts = []
    if summary.critical > 0:
        parts.append(f"[bold red]{summary.critical} critical[/bold red]")
    if summary.major > 0:
        parts.append(f"[yellow]{summary.major} major[/yellow]")
    if summary.minor > 0:
        parts.append(f"[blue]{summary.minor} minor[/blue]")
    if summary.info > 0:
        parts.append(f"[dim]{summary.info} info[/dim]")

    if parts:
        lines.append(f"[bold]Issues:[/bold] {', '.join(parts)}")
    else:
        lines.append("[bold green]No issues found![/bold green]")
    lines.append("")

    # Issues
    severity_styles = {
        Severity.CRITICAL: ("bold red", "!!!"),
        Severity.MAJOR: ("yellow", " !!"),
        Severity.MINOR: ("blue", "  !"),
        Severity.INFO: ("dim", "  i"),
    }

    for issue in report.issues:
        style, icon = severity_styles[issue.severity]
        loc = ""
        if issue.location:
            loc = f" [dim]{issue.location.file}"
            if issue.location.line:
                loc += f":{issue.location.line}"
            loc += "[/dim]"

        lines.append(f"[{style}]{icon}[/{style}] [{style}][{issue.category.value.upper()}][/{style}] {issue.title}{loc}")
        lines.append(f"   {issue.description}")
        if issue.suggestion:
            lines.append(f"   [green]Fix:[/green] {issue.suggestion}")
        lines.append("")

    # Intent results
    if report.intent and report.intent.results:
        lines.append("[bold]Intent Verification[/bold]")
        lines.append(f"[dim]Intent:[/dim] {report.intent.raw_intent}")
        lines.append("")

        for result in report.intent.results:
            status_style = {
                AssertionStatus.PASS: ("green", "+"),
                AssertionStatus.FAIL: ("red", "x"),
                AssertionStatus.PARTIAL: ("yellow", "~"),
                AssertionStatus.UNKNOWN: ("dim", "?"),
            }
            style, icon = status_style[result.status]
            lines.append(f"  [{style}][{icon}][/{style}] {result.assertion.description}")
            if result.evidence:
                lines.append(f"      [dim]{result.evidence}[/dim]")

        lines.append("")

    return "\n".join(lines)
