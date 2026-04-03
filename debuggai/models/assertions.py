"""Intent assertion models for DebuggAI verification."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AssertionType(str, Enum):
    DEPENDENCY = "dependency"
    ROUTE = "route"
    BEHAVIOR = "behavior"
    SECURITY = "security"
    FUNCTION = "function"
    FILE = "file"
    PATTERN = "pattern"
    UI = "ui"


class AssertionStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class Assertion(BaseModel):
    """A testable assertion extracted from user intent."""

    type: AssertionType
    description: str = Field(description="What this assertion checks")
    expect: str = Field(description="What we expect to find")
    importance: float = Field(
        default=1.0, ge=0.0, le=1.0, description="How important this assertion is to the intent"
    )


class AssertionResult(BaseModel):
    """Result of checking a single assertion against the code."""

    assertion: Assertion
    status: AssertionStatus
    evidence: Optional[str] = Field(None, description="What was found (or not found)")
    location: Optional[str] = Field(None, description="Where the evidence was found")
    score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="How well the assertion was satisfied"
    )


class IntentSpec(BaseModel):
    """A parsed intent specification with extracted assertions."""

    raw_intent: str = Field(description="Original intent text")
    source: str = Field(description="Where the intent came from (cli, commit, pr, spec_file)")
    assertions: list[Assertion] = Field(default_factory=list)
    results: list[AssertionResult] = Field(default_factory=list)

    @property
    def fidelity_score(self) -> float:
        """Compute Prompt Fidelity Score (0-100)."""
        if not self.results:
            return 0.0
        total_weight = sum(r.assertion.importance for r in self.results)
        if total_weight == 0:
            return 0.0
        weighted_score = sum(r.score * r.assertion.importance for r in self.results)
        return round((weighted_score / total_weight) * 100, 1)
