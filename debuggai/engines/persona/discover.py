"""Persona discovery — infer ICPs from codebase, README, UI patterns, and config."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("debuggai")


@dataclass
class Persona:
    """A discovered user persona."""
    name: str
    role: str  # primary, secondary, tertiary
    tech_level: str  # non-technical, moderate, technical, developer
    description: str
    goals: list[str] = field(default_factory=list)
    pain_points: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)  # desktop, mobile, tablet
    key_flows: list[str] = field(default_factory=list)  # what they'd try to do


@dataclass
class PersonaProfile:
    """Complete ICP profile for a project."""
    project_name: str
    app_type: str  # consumer, b2b, developer-tool, internal
    personas: list[Persona] = field(default_factory=list)
    raw_signals: dict = field(default_factory=dict)


def discover_personas(
    project_dir: str,
    api_key: Optional[str] = None,
) -> PersonaProfile:
    """Discover ICPs from the codebase.

    Uses two approaches:
    1. Signal-based heuristics (fast, no LLM) — infer from code patterns
    2. LLM-powered discovery (deeper) — read README + UI code + config
    """
    root = Path(project_dir)
    signals = _gather_signals(root)
    profile = PersonaProfile(
        project_name=root.name,
        app_type=_infer_app_type(signals),
        raw_signals=signals,
    )

    if api_key:
        profile.personas = _discover_with_llm(root, signals, api_key)
    else:
        profile.personas = _discover_from_signals(signals)

    return profile


def _gather_signals(root: Path) -> dict:
    """Gather persona-relevant signals from the codebase."""
    signals: dict = {
        "has_auth": False,
        "has_admin": False,
        "has_dashboard": False,
        "has_onboarding": False,
        "has_mobile_meta": False,
        "has_responsive_css": False,
        "has_file_upload": False,
        "has_video_audio": False,
        "has_payments": False,
        "has_api_docs": False,
        "has_i18n": False,
        "has_accessibility": False,
        "has_data_tables": False,
        "has_forms": False,
        "has_search": False,
        "has_notifications": False,
        "has_export": False,
        "has_roles": False,
        "readme_content": "",
        "ui_text_samples": [],
        "error_messages": [],
        "page_routes": [],
    }

    # Read README
    for readme_name in ["README.md", "readme.md", "README.txt", "README"]:
        readme = root / readme_name
        if readme.exists():
            try:
                signals["readme_content"] = readme.read_text()[:5000]
            except (UnicodeDecodeError, PermissionError):
                pass
            break

    # Scan source files for signals
    skip_dirs = {"node_modules", "__pycache__", ".git", "dist", "build", ".next", ".vercel", "venv"}
    supported = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss"}

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in supported:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        content_lower = content.lower()
        rel = str(path.relative_to(root)).lower()

        # Auth signals
        if any(k in content_lower for k in ["login", "signup", "sign-up", "register", "auth", "password", "oauth"]):
            signals["has_auth"] = True
        if any(k in rel for k in ["admin", "dashboard"]):
            signals["has_admin"] = True
        if "dashboard" in content_lower or "dashboard" in rel:
            signals["has_dashboard"] = True
        if any(k in content_lower for k in ["onboarding", "welcome", "getting-started", "tour"]):
            signals["has_onboarding"] = True

        # Mobile signals
        if "viewport" in content_lower and "width=device-width" in content_lower:
            signals["has_mobile_meta"] = True
        if any(k in content_lower for k in ["@media", "responsive", "mobile-first", "breakpoint"]):
            signals["has_responsive_css"] = True

        # Feature signals
        if any(k in content_lower for k in ['type="file"', "filereader", "upload", "dropzone"]):
            signals["has_file_upload"] = True
        if any(k in content_lower for k in ["video", "audio", "ffmpeg", "mediarecorder", "webrtc"]):
            signals["has_video_audio"] = True
        if any(k in content_lower for k in ["stripe", "razorpay", "payment", "checkout", "billing"]):
            signals["has_payments"] = True
        if any(k in content_lower for k in ["swagger", "openapi", "api-docs", "redoc"]):
            signals["has_api_docs"] = True
        if any(k in content_lower for k in ["i18n", "intl", "locale", "translation", "t("]):
            signals["has_i18n"] = True
        if any(k in content_lower for k in ["aria-", "role=", "sr-only", "screen-reader", "a11y"]):
            signals["has_accessibility"] = True
        if any(k in content_lower for k in ["<table", "datagrid", "data-table", "spreadsheet"]):
            signals["has_data_tables"] = True
        if any(k in content_lower for k in ["<form", "onsubmit", "handlesubmit", "useform"]):
            signals["has_forms"] = True
        if any(k in content_lower for k in ["search", "filter", "query"]):
            signals["has_search"] = True
        if any(k in content_lower for k in ["notification", "toast", "alert", "snackbar"]):
            signals["has_notifications"] = True
        if any(k in content_lower for k in ["export", "download", "csv", "pdf", "xlsx"]):
            signals["has_export"] = True
        if any(k in content_lower for k in ["role", "permission", "rbac", "isadmin", "is_admin"]):
            signals["has_roles"] = True

        # Collect route/page names
        route_patterns = re.findall(r'''(?:path|route)\s*[:=]\s*['"]([^'"]+)['"]''', content)
        signals["page_routes"].extend(route_patterns[:20])

        # Collect error messages
        error_patterns = re.findall(r'''(?:error|Error|message)\s*[:=]\s*['"]([^'"]{10,80})['"]''', content)
        signals["error_messages"].extend(error_patterns[:20])

        # Collect UI text
        if path.suffix.lower() in {".tsx", ".jsx", ".html"}:
            text_patterns = re.findall(r'>([A-Z][^<]{5,60})</', content)
            signals["ui_text_samples"].extend(text_patterns[:20])

    # Deduplicate
    signals["page_routes"] = list(set(signals["page_routes"]))[:30]
    signals["error_messages"] = list(set(signals["error_messages"]))[:20]
    signals["ui_text_samples"] = list(set(signals["ui_text_samples"]))[:20]

    return signals


def _infer_app_type(signals: dict) -> str:
    """Infer the app type from signals."""
    if signals["has_api_docs"] and not signals["has_forms"]:
        return "developer-tool"
    if signals["has_admin"] and signals["has_roles"] and signals["has_dashboard"]:
        return "b2b"
    if signals["has_payments"] or signals["has_file_upload"] or signals["has_video_audio"]:
        return "consumer"
    if signals["has_dashboard"] and signals["has_data_tables"]:
        return "b2b"
    return "consumer"


def _discover_from_signals(signals: dict) -> list[Persona]:
    """Generate basic personas from code signals (no LLM needed)."""
    personas = []

    # Primary persona based on app type
    if signals["has_video_audio"] or signals["has_file_upload"]:
        personas.append(Persona(
            name="Content Creator",
            role="primary",
            tech_level="non-technical",
            description="Creates and uploads content. Expects simple, visual workflows.",
            goals=["Upload and process content quickly", "Get results without technical knowledge"],
            pain_points=["Confusing error messages", "No progress feedback", "Too many options"],
            devices=["desktop", "mobile"],
            key_flows=["upload", "process", "preview", "export", "download"],
        ))
    elif signals["has_dashboard"] and signals["has_data_tables"]:
        personas.append(Persona(
            name="Business User",
            role="primary",
            tech_level="moderate",
            description="Uses dashboards and reports for decision-making.",
            goals=["View key metrics at a glance", "Export data for presentations"],
            pain_points=["Slow loading dashboards", "Can't find specific data", "No mobile access"],
            devices=["desktop"],
            key_flows=["login", "view dashboard", "filter data", "export report"],
        ))
    elif signals["has_api_docs"]:
        personas.append(Persona(
            name="Developer",
            role="primary",
            tech_level="developer",
            description="Integrates with the API. Needs clear docs and fast responses.",
            goals=["Integrate quickly", "Find the right endpoint", "Handle errors gracefully"],
            pain_points=["Outdated docs", "Unclear error codes", "No code examples"],
            devices=["desktop"],
            key_flows=["read docs", "get API key", "make first call", "handle errors"],
        ))
    else:
        personas.append(Persona(
            name="End User",
            role="primary",
            tech_level="non-technical",
            description="General user of the application.",
            goals=["Complete their task quickly", "Understand what to do next"],
            pain_points=["Confusing navigation", "No feedback on actions", "Unclear errors"],
            devices=["desktop", "mobile"],
            key_flows=["sign up", "complete main task", "view results"],
        ))

    # Admin persona if admin features detected
    if signals["has_admin"] or signals["has_roles"]:
        personas.append(Persona(
            name="Administrator",
            role="secondary",
            tech_level="moderate",
            description="Manages users, settings, and system configuration.",
            goals=["Manage user accounts", "Configure system settings", "Monitor activity"],
            pain_points=["No bulk operations", "Audit trail missing", "Role management unclear"],
            devices=["desktop"],
            key_flows=["manage users", "change settings", "view logs", "assign roles"],
        ))

    # First-time user (always relevant)
    personas.append(Persona(
        name="First-Time Visitor",
        role="tertiary",
        tech_level="non-technical",
        description="Has never seen this product before. Needs to understand what it does in seconds.",
        goals=["Understand what this product does", "Try it out quickly", "Decide if it's worth using"],
        pain_points=["No clear value proposition", "Complex signup", "No free trial or demo"],
        devices=["desktop", "mobile"],
        key_flows=["land on homepage", "understand value prop", "sign up or try demo"],
    ))

    # Mobile user if responsive detected
    if signals["has_mobile_meta"] or signals["has_responsive_css"]:
        personas.append(Persona(
            name="Mobile User",
            role="secondary",
            tech_level="non-technical",
            description="Accesses the app primarily on phone. Needs touch-friendly, fast-loading UI.",
            goals=["Complete tasks on the go", "Quick access to key features"],
            pain_points=["Tiny touch targets", "Slow loading on 4G", "Desktop-only features"],
            devices=["mobile"],
            key_flows=["open on phone", "navigate to main feature", "complete task with touch"],
        ))

    return personas


def _discover_with_llm(root: Path, signals: dict, api_key: str) -> list[Persona]:
    """Use LLM for deeper persona discovery."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Build context from signals
    readme_excerpt = signals.get("readme_content", "")[:3000]
    routes = ", ".join(signals.get("page_routes", [])[:15])
    ui_samples = "\n".join(signals.get("ui_text_samples", [])[:10])
    features = [k.replace("has_", "") for k, v in signals.items()
                if isinstance(v, bool) and v and k.startswith("has_")]

    try:
        response = client.messages.create(
            model=os.environ.get("DEBUGGAI_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=2048,
            system="""You are DebuggAI's persona discovery engine. Given signals from a codebase,
identify 2-4 user personas (ICP). For each persona, return a JSON object with:
- name: persona name (e.g., "Content Creator", "Enterprise Admin")
- role: "primary" | "secondary" | "tertiary"
- tech_level: "non-technical" | "moderate" | "technical" | "developer"
- description: one sentence describing this persona
- goals: list of 2-3 things they want to accomplish
- pain_points: list of 2-3 likely frustrations based on the app's features
- devices: list of devices they'd use ["desktop", "mobile", "tablet"]
- key_flows: list of 3-5 user flows they'd attempt (e.g., "upload video", "view dashboard")

Be specific to THIS app. Don't generate generic personas.
Return ONLY a JSON array of persona objects.""",
            messages=[{"role": "user", "content": f"""Discover user personas for this project:

Project: {root.name}
README excerpt: {readme_excerpt}
Detected features: {', '.join(features)}
Page routes: {routes}
UI text samples:
{ui_samples}

Return a JSON array of 2-4 personas."""}],
        )

        text = response.content[0].text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        raw_personas = json.loads(text.strip())
        return [Persona(**p) for p in raw_personas]

    except Exception as e:
        logger.warning("DebuggAI: LLM persona discovery failed: %s. Falling back to signal-based.", e)
        return _discover_from_signals(signals)
