"""Deep Analysis Engine — orchestrates all deep analysis layers.

Usage:
    debuggai deep                           # Full analysis
    debuggai deep --focus security          # Security focus
    debuggai deep --focus performance       # Performance focus
    debuggai deep --focus deployment        # Deployment model focus
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from debuggai.config import load_config
from debuggai.utils.constants import SEVERITY_RANK
from debuggai.engines.deep.analyzer import analyze_architecture
from debuggai.engines.deep.holistic import run_holistic_review
from debuggai.engines.deep.indexer import (
    ProjectIndex,
    generate_architecture_summary,
    index_project,
)
from debuggai.engines.code.rules import load_rules, scan_with_rules
from debuggai.models.issues import Issue
from debuggai.models.reports import Report
from debuggai.reports.generator import generate_report


def run_deep_analysis(
    project_dir: Optional[str] = None,
    focus: str = "all",
    use_llm: bool = True,
    config_path: Optional[str] = None,
) -> Report:
    """Run full deep analysis on a project.

    Args:
        project_dir: Project root directory
        focus: Analysis focus — "all", "security", "performance", "deployment"
        use_llm: Whether to use LLM for holistic review
        config_path: Path to config file
    """
    start = time.time()
    config = load_config(config_path)
    project_dir = project_dir or str(Path.cwd())

    # Layer 1: Index the project
    index = index_project(project_dir)

    # Generate architecture summary
    if use_llm and config.anthropic_api_key:
        index.architecture_summary = generate_architecture_summary(
            index, api_key=config.anthropic_api_key
        )
    else:
        from debuggai.engines.deep.indexer import _generate_basic_summary
        index.architecture_summary = _generate_basic_summary(index)

    issues: list[Issue] = []

    # Layer 2 + 3: Architectural + runtime analysis (static, no LLM needed)
    issues.extend(analyze_architecture(index))

    # Layer 4: Domain-specific rule packs
    packs_dir = Path(__file__).parent.parent.parent / "rules" / "packs"
    if packs_dir.exists():
        pack_rules = []
        for yaml_file in sorted(packs_dir.rglob("*.yaml")):
            import yaml
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if data and "rules" in data:
                    pack_rules.extend(data["rules"])
            except Exception:
                continue

        # Run pack rules on all files
        if pack_rules:
            supported = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
            for f_info in index.files:
                if Path(f_info.path).suffix.lower() not in supported:
                    continue
                file_path = Path(project_dir) / f_info.path
                if not file_path.exists():
                    continue
                try:
                    content = file_path.read_text()
                    issues.extend(scan_with_rules(f_info.path, content, pack_rules))
                except (UnicodeDecodeError, PermissionError):
                    continue

    # Layer 5 (partial): Holistic LLM review
    if use_llm and config.anthropic_api_key:
        issues.extend(run_holistic_review(
            index, focus=focus, api_key=config.anthropic_api_key
        ))

    # Deduplicate
    seen: set[str] = set()
    unique_issues: list[Issue] = []
    for issue in issues:
        key = f"{issue.rule_id}:{issue.location.file if issue.location else ''}:{issue.location.line if issue.location else 0}"
        if key not in seen:
            seen.add(key)
            unique_issues.append(issue)

    # Sort by severity
    unique_issues.sort(key=lambda i: (
        SEVERITY_RANK.get(i.severity.value, 99),
        i.location.file if i.location else "",
    ))

    duration_ms = int((time.time() - start) * 1000)

    report = generate_report(
        issues=unique_issues,
        target=project_dir,
        project_name=config.project_name or Path(project_dir).name,
        scan_duration_ms=duration_ms,
    )

    # Add architecture info to report
    report.architecture_summary = index.architecture_summary
    report.project_context = {
        "deployment": index.context.deployment,
        "frameworks": index.context.frameworks,
        "is_serverless": index.context.is_serverless,
        "is_web_app": index.context.is_web_app,
        "total_files": index.total_files,
        "total_lines": index.total_lines,
    }

    # Save to history
    try:
        from debuggai.storage import get_db, save_scan
        db = get_db(project_dir)
        save_scan(
            db, project=report.project or "", target=report.target,
            total=report.summary.total_issues, critical=report.summary.critical,
            major=report.summary.major, minor=report.summary.minor,
            info=report.summary.info, duration_ms=duration_ms, scan_mode="deep",
        )
        db.close()
    except Exception:
        pass

    return report
