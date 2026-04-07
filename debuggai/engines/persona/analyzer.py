"""Persona-based static analyzer — checks code for persona-specific issues.

Tests the codebase from the customer's perspective without running it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from debuggai.engines.persona.discover import Persona, PersonaProfile
from debuggai.models.issues import Category, Issue, Location, Severity

# Issue category for persona findings
PERSONA_CATEGORY = Category.AI_PATTERN  # Reuse closest category


def analyze_for_personas(
    project_dir: str,
    profile: PersonaProfile,
) -> list[Issue]:
    """Run persona-specific static checks on the codebase."""
    issues: list[Issue] = []
    root = Path(project_dir)

    for persona in profile.personas:
        issues.extend(_check_persona(root, persona, profile.raw_signals))

    # Universal checks (apply to all personas)
    issues.extend(_check_error_messages(root, profile))
    issues.extend(_check_loading_feedback(root, profile))
    issues.extend(_check_empty_states(root))

    return issues


def _check_persona(root: Path, persona: Persona, signals: dict) -> list[Issue]:
    """Run checks specific to a persona type."""
    issues: list[Issue] = []

    if persona.tech_level == "non-technical":
        issues.extend(_check_non_technical_user(root, persona))

    if "mobile" in persona.devices:
        issues.extend(_check_mobile_user(root, persona))

    if persona.tech_level == "developer":
        issues.extend(_check_developer_user(root, persona))

    if persona.name.lower() in ("administrator", "admin"):
        issues.extend(_check_admin_user(root, persona, signals))

    return issues


# ── Non-Technical User Checks ─────────────────────────────────


def _check_non_technical_user(root: Path, persona: Persona) -> list[Issue]:
    """Check for issues that would confuse a non-technical user."""
    issues: list[Issue] = []
    skip = {"node_modules", "__pycache__", ".git", "dist", "build", ".next", ".vercel", "venv"}
    ui_exts = {".tsx", ".jsx", ".html", ".vue", ".svelte"}

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ui_exts:
            continue
        if any(p in skip for p in path.parts):
            continue
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        rel = str(path.relative_to(root))
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            # Technical jargon in user-facing text
            jargon = re.search(
                r'''>[^<]*\b(API|JSON|HTTP|CORS|DNS|SSL|TLS|JWT|OAuth|webhook|endpoint|payload|schema|runtime|stack trace|exception|null|undefined|NaN)\b[^<]*<''',
                line,
            )
            if jargon:
                term = jargon.group(1)
                issues.append(Issue(
                    id=f"persona-jargon-{rel}:{i}",
                    severity=Severity.MAJOR,
                    category=PERSONA_CATEGORY,
                    title=f"Technical jargon in UI: '{term}'",
                    description=(
                        f"[Persona: {persona.name}] The term '{term}' at {rel}:{i} is developer jargon. "
                        f"A {persona.tech_level} user won't understand it."
                    ),
                    location=Location(file=rel, line=i),
                    suggestion=f"Replace '{term}' with plain language that describes what it means for the user.",
                    confidence=0.7,
                    engine="persona",
                    rule_id="ui-jargon",
                ))

            # Raw error codes shown to users
            if re.search(r'''>[^<]*\b(?:error\s*code|status\s*\d{3}|errno|exit\s*code)\b[^<]*<''', line, re.IGNORECASE):
                issues.append(Issue(
                    id=f"persona-error-code-{rel}:{i}",
                    severity=Severity.MAJOR,
                    category=PERSONA_CATEGORY,
                    title="Raw error code shown to user",
                    description=(
                        f"[Persona: {persona.name}] Error code displayed at {rel}:{i}. "
                        f"Non-technical users need a human-readable message, not a code."
                    ),
                    location=Location(file=rel, line=i),
                    suggestion="Show a friendly message like 'Something went wrong. Please try again.' with a retry button.",
                    confidence=0.7,
                    engine="persona",
                    rule_id="raw-error-code",
                ))

    return issues


# ── Mobile User Checks ────────────────────────────────────────


def _check_mobile_user(root: Path, persona: Persona) -> list[Issue]:
    """Check for issues affecting mobile users."""
    issues: list[Issue] = []

    # Check for viewport meta tag
    html_files = list(root.rglob("*.html")) + list(root.rglob("index.tsx")) + list(root.rglob("layout.tsx"))
    has_viewport = False
    for f in html_files:
        if any(p in {"node_modules", ".next", "dist", "build"} for p in f.parts):
            continue
        try:
            content = f.read_text()
            if "viewport" in content and "width=device-width" in content:
                has_viewport = True
                break
        except (UnicodeDecodeError, PermissionError):
            continue

    if not has_viewport and html_files:
        issues.append(Issue(
            id="persona-no-viewport",
            severity=Severity.MAJOR,
            category=PERSONA_CATEGORY,
            title="No viewport meta tag for mobile",
            description=(
                f"[Persona: {persona.name}] No <meta name='viewport'> found. "
                f"The app won't scale properly on mobile devices."
            ),
            location=None,
            suggestion="Add <meta name='viewport' content='width=device-width, initial-scale=1'> to your HTML head.",
            confidence=0.9,
            engine="persona",
            rule_id="missing-viewport",
        ))

    # Check for hover-only interactions in CSS
    skip = {"node_modules", ".next", "dist", "build"}
    for path in root.rglob("*.css"):
        if any(p in skip for p in path.parts):
            continue
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        rel = str(path.relative_to(root))
        for i, line in enumerate(content.split("\n"), 1):
            if ":hover" in line and "@media" not in line:
                # Check if there's a corresponding touch/focus style
                context = content[max(0, content.find(line) - 200):content.find(line) + 200]
                if ":focus" not in context and ":active" not in context and "@media (hover:" not in context:
                    issues.append(Issue(
                        id=f"persona-hover-only-{rel}:{i}",
                        severity=Severity.MINOR,
                        category=PERSONA_CATEGORY,
                        title="Hover-only interaction (no touch equivalent)",
                        description=(
                            f"[Persona: {persona.name}] CSS :hover at {rel}:{i} with no :focus or :active fallback. "
                            f"Mobile users can't hover — this interaction is invisible to them."
                        ),
                        location=Location(file=rel, line=i),
                        suggestion="Add :focus and :active styles alongside :hover, or use @media (hover: hover).",
                        confidence=0.5,
                        engine="persona",
                        rule_id="hover-only-interaction",
                    ))
                    break  # One per file is enough

    # Check for large assets that would slow mobile loading
    static_dirs = ["public", "static", "assets"]
    for d in static_dirs:
        dir_path = root / d
        if not dir_path.exists():
            continue
        for path in dir_path.rglob("*"):
            if not path.is_file():
                continue
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > 5:
                rel = str(path.relative_to(root))
                issues.append(Issue(
                    id=f"persona-large-asset-{rel}",
                    severity=Severity.MAJOR,
                    category=PERSONA_CATEGORY,
                    title=f"Large asset ({size_mb:.0f}MB) hurts mobile loading",
                    description=(
                        f"[Persona: {persona.name}] {rel} is {size_mb:.0f}MB. "
                        f"On a mobile 4G connection, this takes ~{size_mb * 2:.0f} seconds to download."
                    ),
                    location=Location(file=rel),
                    suggestion="Lazy-load this asset, compress it, or load a smaller version on mobile.",
                    confidence=0.85,
                    engine="persona",
                    rule_id="large-asset-mobile",
                ))

    return issues


# ── Developer User Checks ─────────────────────────────────────


def _check_developer_user(root: Path, persona: Persona) -> list[Issue]:
    """Check for issues affecting developer users."""
    issues: list[Issue] = []

    # Check for missing API documentation
    has_api_routes = False
    has_api_docs = False
    skip = {"node_modules", "__pycache__", ".git", "dist", "build"}

    for path in root.rglob("*"):
        if any(p in skip for p in path.parts):
            continue
        rel = str(path.relative_to(root)).lower()
        if "api/" in rel and path.suffix.lower() in {".py", ".ts", ".js"}:
            has_api_routes = True
        if any(k in rel for k in ["swagger", "openapi", "api-doc", "redoc"]):
            has_api_docs = True

    if has_api_routes and not has_api_docs:
        issues.append(Issue(
            id="persona-no-api-docs",
            severity=Severity.MAJOR,
            category=PERSONA_CATEGORY,
            title="API routes exist but no API documentation",
            description=(
                f"[Persona: {persona.name}] API routes found but no Swagger/OpenAPI docs. "
                f"Developers can't integrate without documentation."
            ),
            location=None,
            suggestion="Add Swagger UI, Redoc, or an OpenAPI spec file.",
            confidence=0.8,
            engine="persona",
            rule_id="missing-api-docs",
        ))

    return issues


# ── Admin User Checks ─────────────────────────────────────────


def _check_admin_user(root: Path, persona: Persona, signals: dict) -> list[Issue]:
    """Check for issues affecting admin users."""
    issues: list[Issue] = []

    if not signals.get("has_export"):
        issues.append(Issue(
            id="persona-no-export",
            severity=Severity.MINOR,
            category=PERSONA_CATEGORY,
            title="No data export functionality",
            description=(
                f"[Persona: {persona.name}] No export/download feature detected. "
                f"Admins typically need to export data for reports or compliance."
            ),
            location=None,
            suggestion="Add CSV/PDF export for key data tables.",
            confidence=0.6,
            engine="persona",
            rule_id="missing-export",
        ))

    return issues


# ── Universal Checks ──────────────────────────────────────────


def _check_error_messages(root: Path, profile: PersonaProfile) -> list[Issue]:
    """Check if error messages are user-friendly."""
    issues: list[Issue] = []
    skip = {"node_modules", "__pycache__", ".git", "dist", "build", ".next", ".vercel"}
    code_exts = {".py", ".js", ".jsx", ".ts", ".tsx"}

    unfriendly_patterns = [
        (r'(?:err|error)\.(?:message|stack|toString)', "Raw error object exposed to user"),
        (r'(?:throw|raise)\s+(?:new\s+)?(?:Error|Exception)\s*\(\s*`', "Template literal in thrown error might reach UI"),
        (r'console\.error\s*\(.*\)\s*;?\s*$', "Error logged to console but not shown to user"),
    ]

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in code_exts:
            continue
        if any(p in skip for p in path.parts):
            continue
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        rel = str(path.relative_to(root))
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("#"):
                continue
            for pattern, desc in unfriendly_patterns:
                if re.search(pattern, line):
                    issues.append(Issue(
                        id=f"persona-error-msg-{rel}:{i}",
                        severity=Severity.MINOR,
                        category=PERSONA_CATEGORY,
                        title=desc,
                        description=f"[All Personas] {desc} at {rel}:{i}. Users need human-readable error messages.",
                        location=Location(file=rel, line=i),
                        suggestion="Catch the error and show a user-friendly message instead of technical details.",
                        confidence=0.6,
                        engine="persona",
                        rule_id="unfriendly-error",
                    ))
                    break

    return issues


def _check_loading_feedback(root: Path, profile: PersonaProfile) -> list[Issue]:
    """Check if async operations have loading indicators."""
    issues: list[Issue] = []
    skip = {"node_modules", "__pycache__", ".git", "dist", "build", ".next", ".vercel"}
    ui_exts = {".tsx", ".jsx", ".vue", ".svelte"}

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ui_exts:
            continue
        if any(p in skip for p in path.parts):
            continue
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        rel = str(path.relative_to(root))

        # Check for async data fetching without loading state
        has_fetch = bool(re.search(r'(?:useQuery|useSWR|fetch\(|axios\.|useEffect.*fetch)', content))
        has_loading = bool(re.search(r'(?:loading|isLoading|isPending|skeleton|spinner|Loader)', content, re.IGNORECASE))

        if has_fetch and not has_loading:
            issues.append(Issue(
                id=f"persona-no-loading-{rel}",
                severity=Severity.MAJOR,
                category=PERSONA_CATEGORY,
                title="Data fetching without loading indicator",
                description=(
                    f"[All Personas] {rel} fetches data but has no loading state. "
                    f"Users see a blank/broken page while data loads."
                ),
                location=Location(file=rel),
                suggestion="Add a loading state (spinner, skeleton, or 'Loading...' text) while data is being fetched.",
                confidence=0.7,
                engine="persona",
                rule_id="missing-loading-state",
            ))

    return issues


def _check_empty_states(root: Path) -> list[Issue]:
    """Check if lists/tables handle empty data gracefully."""
    issues: list[Issue] = []
    skip = {"node_modules", "__pycache__", ".git", "dist", "build", ".next", ".vercel"}
    ui_exts = {".tsx", ".jsx", ".vue", ".svelte"}

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ui_exts:
            continue
        if any(p in skip for p in path.parts):
            continue
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        rel = str(path.relative_to(root))

        # Check for .map() rendering without empty state handling
        has_map = bool(re.search(r'\.map\s*\(\s*\(', content))
        has_empty = bool(re.search(r'(?:\.length\s*===?\s*0|empty|no\s+(?:results|data|items))', content, re.IGNORECASE))

        if has_map and not has_empty:
            issues.append(Issue(
                id=f"persona-no-empty-state-{rel}",
                severity=Severity.MINOR,
                category=PERSONA_CATEGORY,
                title="List rendering without empty state",
                description=(
                    f"[All Personas] {rel} renders a list with .map() but doesn't handle empty data. "
                    f"When there's no data, users see a blank area with no explanation."
                ),
                location=Location(file=rel),
                suggestion="Add an empty state: 'No items yet' with a call-to-action or explanation.",
                confidence=0.6,
                engine="persona",
                rule_id="missing-empty-state",
            ))

    return issues
