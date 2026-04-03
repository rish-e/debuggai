"""Intent scorer — verify assertions against code and compute Prompt Fidelity Score."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from debuggai.models.assertions import (
    Assertion,
    AssertionResult,
    AssertionStatus,
    IntentSpec,
)
from debuggai.models.issues import Category, Issue, Location, Severity
from debuggai.utils.llm import verify_assertion


def score_intent(
    intent_spec: IntentSpec,
    code: str,
    project_dir: Optional[str] = None,
    api_key: Optional[str] = None,
) -> tuple[IntentSpec, list[Issue]]:
    """Verify all assertions against the code and compute fidelity score.

    Returns the updated IntentSpec with results, and a list of issues for failed assertions.
    """
    results: list[AssertionResult] = []
    issues: list[Issue] = []

    for i, assertion in enumerate(intent_spec.assertions):
        raw_result = verify_assertion(
            assertion=assertion.model_dump(),
            code=code,
            api_key=api_key,
        )

        status_map = {
            "pass": AssertionStatus.PASS,
            "fail": AssertionStatus.FAIL,
            "partial": AssertionStatus.PARTIAL,
            "unknown": AssertionStatus.UNKNOWN,
        }

        status = status_map.get(
            raw_result.get("status", "unknown").lower(),
            AssertionStatus.UNKNOWN,
        )
        score = float(raw_result.get("score", 0.0))

        result = AssertionResult(
            assertion=assertion,
            status=status,
            evidence=raw_result.get("evidence"),
            location=raw_result.get("location"),
            score=score,
        )
        results.append(result)

        # Create issues for failed/partial assertions
        if status in (AssertionStatus.FAIL, AssertionStatus.PARTIAL):
            severity = Severity.MAJOR if assertion.importance > 0.7 else Severity.MINOR
            issues.append(Issue(
                id=f"intent-{i}-{assertion.type.value}",
                severity=severity,
                category=Category.INTENT,
                title=f"Intent not met: {assertion.description}",
                description=(
                    f"Expected: {assertion.expect}\n"
                    f"Status: {status.value}\n"
                    f"Evidence: {result.evidence or 'None found'}"
                ),
                location=Location(file=result.location) if result.location else None,
                suggestion=f"Implement: {assertion.expect}",
                confidence=0.8,
                engine="intent",
                rule_id=f"intent-{assertion.type.value}",
            ))

    intent_spec.results = results
    return intent_spec, issues
