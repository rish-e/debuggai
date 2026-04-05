"""Orchestrator — coordinates engines, context, storage, and reports."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("debuggai")
from pathlib import Path
from typing import Optional

from debuggai.config import DebuggAIConfig, load_config
from debuggai.context import ProjectContext, detect_context, should_adjust_severity
from debuggai.engines.code.rules import load_rules, scan_with_rules
from debuggai.engines.code.scanner import scan_directory, scan_file, scan_files
from debuggai.engines.intent.capture import capture_intent
from debuggai.engines.intent.parser import parse_intent
from debuggai.engines.intent.scorer import score_intent
from debuggai.models.assertions import IntentSpec
from debuggai.models.issues import Issue, Severity
from debuggai.models.reports import Report
from debuggai.reports.generator import generate_report
from debuggai.utils.git import FileDiff, get_changed_files, get_repo_root, is_git_repo


def run_scan(
    target: Optional[str] = None,
    diff_ref: Optional[str] = None,
    staged: bool = False,
    intent: Optional[str] = None,
    spec_file: Optional[str] = None,
    use_llm: bool = True,
    config_path: Optional[str] = None,
) -> Report:
    """Run a full DebuggAI scan."""
    start = time.time()
    config = load_config(config_path)

    # Determine project directory
    project_dir = None
    if target and Path(target).is_dir():
        project_dir = str(Path(target).resolve())
    elif is_git_repo():
        project_dir = get_repo_root()
    else:
        project_dir = str(Path.cwd())

    # Detect project context (frameworks, deployment, protections)
    ctx = detect_context(project_dir) if project_dir else ProjectContext()

    # Load custom YAML rules
    custom_rules = load_rules(project_dir=project_dir)

    issues: list[Issue] = []
    target_desc = target or "git changes"

    # Scan based on target type
    if target and Path(target).is_file():
        content = Path(target).read_text()
        issues = scan_file(target, content, config, project_dir=project_dir, use_llm=use_llm)
        # Run custom rules on this file
        issues.extend(scan_with_rules(target, content, custom_rules))
        target_desc = target

    elif target and Path(target).is_dir():
        issues = scan_directory(target, config, use_llm=use_llm)
        # Run custom rules on directory
        issues.extend(_run_rules_on_directory(target, custom_rules))
        target_desc = target

    elif diff_ref or staged:
        files = get_changed_files(ref=diff_ref, staged=staged, cwd=project_dir)
        issues = scan_files(files, config, project_dir=project_dir, use_llm=use_llm)
        target_desc = f"diff:{diff_ref}" if diff_ref else "staged changes"

    else:
        issues = scan_directory(project_dir or ".", config, use_llm=use_llm)
        issues.extend(_run_rules_on_directory(project_dir or ".", custom_rules))
        target_desc = project_dir or "."

    # Apply context-aware severity adjustments
    issues = _apply_context_adjustments(issues, ctx)

    # Filter suppressed issues (from dismissal memory)
    issues = _filter_suppressed(issues, project_dir)

    # Intent verification (if provided)
    intent_spec: Optional[IntentSpec] = None
    if intent or spec_file:
        intent_text, source = capture_intent(
            cli_intent=intent, spec_file=spec_file, project_dir=project_dir,
        )
        if intent_text:
            code_context = _gather_code_context(target, project_dir)
            intent_spec = parse_intent(
                intent_text, source, code_context=code_context, api_key=config.anthropic_api_key,
            )
            if intent_spec.assertions:
                intent_spec, intent_issues = score_intent(
                    intent_spec, code_context, project_dir=project_dir, api_key=config.anthropic_api_key,
                )
                issues.extend(intent_issues)

    duration_ms = int((time.time() - start) * 1000)

    report = generate_report(
        issues=issues, target=target_desc, intent=intent_spec,
        project_name=config.project_name, scan_duration_ms=duration_ms,
    )

    # Save to history
    _save_to_history(report, project_dir)

    return report


def _apply_context_adjustments(issues: list[Issue], ctx: ProjectContext) -> list[Issue]:
    """Adjust issue severity based on project context."""
    adjusted = []
    for issue in issues:
        adjustment = should_adjust_severity(ctx, issue.rule_id or "", issue.category.value)
        if adjustment == "suppress":
            continue
        if adjustment and adjustment != "suppress":
            severity_map = {
                "critical": Severity.CRITICAL, "major": Severity.MAJOR,
                "minor": Severity.MINOR, "info": Severity.INFO,
            }
            if adjustment in severity_map:
                issue.severity = severity_map[adjustment]
        adjusted.append(issue)
    return adjusted


def _filter_suppressed(issues: list[Issue], project_dir: Optional[str]) -> list[Issue]:
    """Remove issues that have been auto-suppressed via dismissal memory."""
    try:
        from debuggai.storage import get_db, is_suppressed
        db = get_db(project_dir)
        filtered = []
        for issue in issues:
            file_path = issue.location.file if issue.location else None
            if not is_suppressed(db, issue.rule_id or "", file_path):
                filtered.append(issue)
        db.close()
        return filtered
    except Exception as e:
        logger.warning("DebuggAI: Dismissal filter failed (issues shown unfiltered): %s", e)
        return issues


def _save_to_history(report: Report, project_dir: Optional[str]) -> None:
    """Save scan results to history database."""
    try:
        from debuggai.storage import get_db, save_scan, save_issues
        db = get_db(project_dir)
        scan_id = save_scan(
            db,
            project=report.project or "",
            target=report.target,
            total=report.summary.total_issues,
            critical=report.summary.critical,
            major=report.summary.major,
            minor=report.summary.minor,
            info=report.summary.info,
            fidelity_score=report.summary.fidelity_score,
            duration_ms=report.summary.scan_duration_ms,
        )
        save_issues(db, scan_id, [
            {
                "rule_id": i.rule_id,
                "file": i.location.file if i.location else None,
                "line": i.location.line if i.location else None,
                "severity": i.severity.value,
                "category": i.category.value,
                "title": i.title,
            }
            for i in report.issues
        ])
        db.close()
    except Exception as e:
        logger.warning("DebuggAI: Failed to save scan history: %s", e)


def _run_rules_on_directory(directory: str, rules: list[dict]) -> list[Issue]:
    """Run custom YAML rules on all files in a directory."""
    if not rules:
        return []

    issues = []
    supported = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java"}

    for path in sorted(Path(directory).rglob("*")):
        if not path.is_file() or path.suffix.lower() not in supported:
            continue
        if any(p.startswith(".") or p in ("node_modules", "__pycache__", "venv", ".venv", "dist", "build")
               for p in path.parts):
            continue
        try:
            content = path.read_text()
            rel = str(path.relative_to(directory))
            issues.extend(scan_with_rules(rel, content, rules))
        except (UnicodeDecodeError, PermissionError):
            continue

    return issues


def _gather_code_context(target: Optional[str], project_dir: Optional[str]) -> str:
    """Gather relevant code for intent verification."""
    if target and Path(target).is_file():
        return Path(target).read_text()
    if target and Path(target).is_dir():
        return _read_directory_summary(target)
    if project_dir:
        return _read_directory_summary(project_dir)
    return ""


def _read_directory_summary(directory: str, max_chars: int = 50000) -> str:
    """Read a summary of code files in a directory."""
    parts: list[str] = []
    total = 0
    supported = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java"}

    for path in sorted(Path(directory).rglob("*")):
        if not path.is_file() or path.suffix.lower() not in supported:
            continue
        if any(p.startswith(".") or p in ("node_modules", "__pycache__", "venv", ".venv")
               for p in path.parts):
            continue
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue
        rel = str(path.relative_to(directory))
        chunk = f"\n--- {rel} ---\n{content}\n"
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk)

    return "".join(parts)
