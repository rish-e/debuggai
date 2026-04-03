"""Configuration loading and management for DebuggAI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

CONFIG_FILENAME = ".debuggai.yaml"


class CodeConfig(BaseModel):
    languages: list[str] = Field(default_factory=list)
    strictness: str = "medium"
    ignore: list[str] = Field(default_factory=list)
    rules: dict[str, bool] = Field(
        default_factory=lambda: {"security": True, "performance": True, "ai_patterns": True}
    )


class CreativeVideoConfig(BaseModel):
    quality_threshold: int = 80
    check_sync: bool = True
    frame_sample_rate: float = 1.0


class CreativeAudioConfig(BaseModel):
    check_levels: bool = True
    check_clipping: bool = True


class CreativeConfig(BaseModel):
    video: CreativeVideoConfig = Field(default_factory=CreativeVideoConfig)
    audio: CreativeAudioConfig = Field(default_factory=CreativeAudioConfig)


class IntentConfig(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["git_commits", "pr_descriptions"])


class ReportingConfig(BaseModel):
    format: str = "markdown"
    severity_threshold: str = "minor"
    output: str = "stdout"


class DebuggAIConfig(BaseModel):
    project_name: Optional[str] = None
    project_type: str = "fullstack"
    code: CodeConfig = Field(default_factory=CodeConfig)
    creative: CreativeConfig = Field(default_factory=CreativeConfig)
    intent: IntentConfig = Field(default_factory=IntentConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    anthropic_api_key: Optional[str] = None


def find_config_file(start_dir: Optional[str] = None) -> Optional[Path]:
    """Walk up from start_dir looking for .debuggai.yaml."""
    current = Path(start_dir or os.getcwd()).resolve()
    while True:
        config_path = current / CONFIG_FILENAME
        if config_path.exists():
            return config_path
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def load_config(config_path: Optional[str] = None) -> DebuggAIConfig:
    """Load config from file, env vars, or defaults."""
    config_data = {}

    if config_path:
        path = Path(config_path)
    else:
        path = find_config_file()

    if path and path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        # Flatten nested "project" key
        if "project" in raw:
            proj = raw.pop("project")
            config_data["project_name"] = proj.get("name")
            config_data["project_type"] = proj.get("type", "fullstack")
        config_data.update(raw)

    config = DebuggAIConfig(**config_data)

    # Override API key from env
    env_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEBUGGAI_API_KEY")
    if env_key:
        config.anthropic_api_key = env_key

    return config


def auto_detect_languages(project_dir: str) -> list[str]:
    """Auto-detect programming languages used in a project."""
    extensions_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
    }
    found = set()
    root = Path(project_dir)
    for path in root.rglob("*"):
        if path.is_file() and not any(
            part.startswith(".") or part == "node_modules" or part == "__pycache__"
            for part in path.parts
        ):
            ext = path.suffix.lower()
            if ext in extensions_map:
                found.add(extensions_map[ext])
    return sorted(found)


def generate_default_config(project_dir: str) -> str:
    """Generate a default .debuggai.yaml for a project."""
    languages = auto_detect_languages(project_dir)

    config = {
        "project": {
            "name": Path(project_dir).name,
            "type": "fullstack",
        },
        "code": {
            "languages": languages,
            "strictness": "medium",
            "ignore": ["*.test.*", "*.spec.*", "node_modules/", "__pycache__/", ".git/"],
            "rules": {
                "security": True,
                "performance": True,
                "ai_patterns": True,
            },
        },
        "intent": {
            "sources": ["git_commits", "pr_descriptions", "spec_files"],
        },
        "reporting": {
            "format": "markdown",
            "severity_threshold": "minor",
            "output": "stdout",
        },
    }

    return yaml.dump(config, default_flow_style=False, sort_keys=False)
