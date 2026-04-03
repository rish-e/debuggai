"""Orchestrator — coordinates engines and builds reports."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from debuggai.config import DebuggAIConfig, load_config
from debuggai.engines.code.scanner import scan_directory, scan_file, scan_files
from debuggai.engines.intent.capture import capture_intent
from debuggai.engines.intent.parser import parse_intent
from debuggai.engines.intent.scorer import score_intent
from debuggai.models.assertions import IntentSpec
from debuggai.models.issues import Issue
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
    """Run a full DebuggAI scan.

    Args:
        target: File or directory to scan. If None, scans git changes.
        diff_ref: Git ref to diff against (e.g., "HEAD~1").
        staged: If True, scan staged changes only.
        intent: Natural language intent for verification.
        spec_file: Path to intent spec file.
        use_llm: Whether to use LLM for analysis.
        config_path: Path to config file.
    """
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

    issues: list[Issue] = []
    target_desc = target or "git changes"

    # Scan based on target type
    if target and Path(target).is_file():
        # Single file scan
        content = Path(target).read_text()
        issues = scan_file(
            target, content, config,
            project_dir=project_dir,
            use_llm=use_llm,
        )
        target_desc = target

    elif target and Path(target).is_dir():
        # Directory scan
        issues = scan_directory(target, config, use_llm=use_llm)
        target_desc = target

    elif diff_ref or staged:
        # Git diff scan
        files = get_changed_files(ref=diff_ref, staged=staged, cwd=project_dir)
        issues = scan_files(
            files, config,
            project_dir=project_dir,
            use_llm=use_llm,
        )
        target_desc = f"diff:{diff_ref}" if diff_ref else "staged changes"

    else:
        # Default: scan current directory
        issues = scan_directory(project_dir or ".", config, use_llm=use_llm)
        target_desc = project_dir or "."

    # Intent verification (if provided)
    intent_spec: Optional[IntentSpec] = None
    if intent or spec_file:
        intent_text, source = capture_intent(
            cli_intent=intent,
            spec_file=spec_file,
            project_dir=project_dir,
        )
        if intent_text:
            # Get code context for assertion verification
            code_context = _gather_code_context(target, project_dir)

            intent_spec = parse_intent(
                intent_text, source,
                code_context=code_context,
                api_key=config.anthropic_api_key,
            )

            if intent_spec.assertions:
                intent_spec, intent_issues = score_intent(
                    intent_spec, code_context,
                    project_dir=project_dir,
                    api_key=config.anthropic_api_key,
                )
                issues.extend(intent_issues)

    duration_ms = int((time.time() - start) * 1000)

    return generate_report(
        issues=issues,
        target=target_desc,
        intent=intent_spec,
        project_name=config.project_name,
        scan_duration_ms=duration_ms,
    )


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
