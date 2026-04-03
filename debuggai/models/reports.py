"""Report data models for DebuggAI output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from debuggai.models.assertions import IntentSpec
from debuggai.models.issues import Issue, Severity


class ReportSummary(BaseModel):
    """Summary statistics for a report."""

    total_issues: int = 0
    critical: int = 0
    major: int = 0
    minor: int = 0
    info: int = 0
    fidelity_score: Optional[float] = None
    engines_run: list[str] = Field(default_factory=list)
    scan_duration_ms: Optional[int] = None


class Report(BaseModel):
    """Complete DebuggAI analysis report."""

    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    project: Optional[str] = None
    target: str = Field(description="What was scanned (file path, diff ref, etc.)")
    issues: list[Issue] = Field(default_factory=list)
    intent: Optional[IntentSpec] = None
    summary: ReportSummary = Field(default_factory=ReportSummary)

    def build_summary(self) -> ReportSummary:
        """Compute summary from issues and intent."""
        self.summary = ReportSummary(
            total_issues=len(self.issues),
            critical=sum(1 for i in self.issues if i.severity == Severity.CRITICAL),
            major=sum(1 for i in self.issues if i.severity == Severity.MAJOR),
            minor=sum(1 for i in self.issues if i.severity == Severity.MINOR),
            info=sum(1 for i in self.issues if i.severity == Severity.INFO),
            fidelity_score=self.intent.fidelity_score if self.intent else None,
            engines_run=list({i.engine for i in self.issues}),
        )
        return self.summary
