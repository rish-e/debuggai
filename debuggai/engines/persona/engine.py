"""Persona engine — orchestrates discovery, static analysis, and live testing."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from debuggai.config import load_config
from debuggai.engines.persona.analyzer import analyze_for_personas
from debuggai.engines.persona.discover import Persona, PersonaProfile, discover_personas
from debuggai.engines.persona.experience import ExperienceReport
from debuggai.models.issues import Issue
from debuggai.models.reports import Report
from debuggai.reports.generator import generate_report


def run_persona_analysis(
    project_dir: Optional[str] = None,
    persona_name: Optional[str] = None,
    discover_only: bool = False,
    config_path: Optional[str] = None,
) -> tuple[PersonaProfile, Optional[Report]]:
    """Run persona discovery and static analysis."""
    start = time.time()
    config = load_config(config_path)
    project_dir = project_dir or str(Path.cwd())

    profile = discover_personas(project_dir, api_key=config.anthropic_api_key)

    if discover_only:
        return profile, None

    if persona_name:
        matching = [p for p in profile.personas if persona_name.lower() in p.name.lower()]
        if matching:
            profile.personas = matching

    issues: list[Issue] = analyze_for_personas(project_dir, profile)
    duration_ms = int((time.time() - start) * 1000)

    report = generate_report(
        issues=issues, target=project_dir,
        project_name=config.project_name or Path(project_dir).name,
        scan_duration_ms=duration_ms,
    )

    try:
        from debuggai.storage import get_db, save_scan
        db = get_db(project_dir)
        save_scan(db, project=report.project or "", target=report.target,
                  total=report.summary.total_issues, critical=report.summary.critical,
                  major=report.summary.major, minor=report.summary.minor,
                  info=report.summary.info, duration_ms=duration_ms, scan_mode="persona")
        db.close()
    except Exception:
        pass

    return profile, report


def run_live_persona_test(
    url: str,
    project_dir: Optional[str] = None,
    persona_name: Optional[str] = None,
    max_steps: int = 15,
    headless: bool = True,
    config_path: Optional[str] = None,
) -> tuple[PersonaProfile, list[ExperienceReport]]:
    """Run live browser testing as discovered personas.

    Returns (profile, list of experience reports — one per persona).
    """
    config = load_config(config_path)
    if not config.anthropic_api_key:
        raise RuntimeError("Live persona testing requires ANTHROPIC_API_KEY.")

    project_dir = project_dir or str(Path.cwd())
    profile = discover_personas(project_dir, api_key=config.anthropic_api_key)

    if persona_name:
        matching = [p for p in profile.personas if persona_name.lower() in p.name.lower()]
        if matching:
            profile.personas = matching

    from debuggai.engines.persona.agent import run_persona_agent_sync

    reports: list[ExperienceReport] = []
    for persona in profile.personas:
        report = run_persona_agent_sync(
            url=url, persona=persona, api_key=config.anthropic_api_key,
            max_steps=max_steps, headless=headless,
        )
        reports.append(report)

    return profile, reports
