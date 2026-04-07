"""Persona engine — orchestrates discovery + analysis."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from debuggai.config import load_config
from debuggai.engines.persona.analyzer import analyze_for_personas
from debuggai.engines.persona.discover import PersonaProfile, discover_personas
from debuggai.models.issues import Issue
from debuggai.models.reports import Report
from debuggai.reports.generator import generate_report


def run_persona_analysis(
    project_dir: Optional[str] = None,
    persona_name: Optional[str] = None,
    discover_only: bool = False,
    config_path: Optional[str] = None,
) -> tuple[PersonaProfile, Optional[Report]]:
    """Run persona discovery and analysis.

    Args:
        project_dir: Project root directory
        persona_name: Specific persona to test for (or None for all)
        discover_only: If True, only discover personas without analyzing
        config_path: Path to config file

    Returns:
        (PersonaProfile, Report or None if discover_only)
    """
    start = time.time()
    config = load_config(config_path)
    project_dir = project_dir or str(Path.cwd())

    # Step 1: Discover personas
    profile = discover_personas(project_dir, api_key=config.anthropic_api_key)

    if discover_only:
        return profile, None

    # Filter to specific persona if requested
    if persona_name:
        matching = [p for p in profile.personas
                    if persona_name.lower() in p.name.lower()]
        if matching:
            profile.personas = matching

    # Step 2: Static analysis for each persona
    issues: list[Issue] = analyze_for_personas(project_dir, profile)

    duration_ms = int((time.time() - start) * 1000)

    report = generate_report(
        issues=issues,
        target=project_dir,
        project_name=config.project_name or Path(project_dir).name,
        scan_duration_ms=duration_ms,
    )

    # Save to history
    try:
        from debuggai.storage import get_db, save_scan
        db = get_db(project_dir)
        save_scan(
            db, project=report.project or "", target=report.target,
            total=report.summary.total_issues, critical=report.summary.critical,
            major=report.summary.major, minor=report.summary.minor,
            info=report.summary.info, duration_ms=duration_ms, scan_mode="persona",
        )
        db.close()
    except Exception:
        pass

    return profile, report
