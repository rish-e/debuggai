"""Issue data models for DebuggAI findings."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class Category(str, Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    LOGIC = "logic"
    IMPORT = "import"
    AI_PATTERN = "ai_pattern"
    INTENT = "intent"
    STYLE = "style"


class Location(BaseModel):
    """Where in the codebase an issue was found."""

    file: str
    line: Optional[int] = None
    end_line: Optional[int] = None
    column: Optional[int] = None
    function: Optional[str] = None


class Issue(BaseModel):
    """A single issue found by DebuggAI."""

    id: str = Field(description="Unique issue identifier")
    severity: Severity
    category: Category
    title: str = Field(description="Short description of the issue")
    description: str = Field(description="Detailed explanation")
    location: Optional[Location] = None
    suggestion: Optional[str] = Field(None, description="Suggested fix")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="How confident we are this is a real issue"
    )
    engine: str = Field(description="Which engine found this (code, creative, intent, llm)")
    rule_id: Optional[str] = Field(None, description="Rule identifier if from rule engine")
    evidence: Optional[str] = Field(None, description="Code snippet or evidence supporting finding")
