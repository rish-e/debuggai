"""Intent parser — extract testable assertions from natural language intent."""

from __future__ import annotations

from typing import Optional

from debuggai.models.assertions import Assertion, AssertionType, IntentSpec
from debuggai.utils.llm import extract_intent_assertions


def parse_intent(
    intent_text: str,
    source: str,
    code_context: str = "",
    api_key: Optional[str] = None,
) -> IntentSpec:
    """Parse natural language intent into structured assertions.

    Uses Claude to extract testable assertions from the intent.
    """
    if not intent_text.strip():
        return IntentSpec(raw_intent=intent_text, source=source)

    raw_assertions = extract_intent_assertions(
        intent=intent_text,
        code_context=code_context,
        api_key=api_key,
    )

    assertions: list[Assertion] = []
    for raw in raw_assertions:
        try:
            type_map = {
                "dependency": AssertionType.DEPENDENCY,
                "route": AssertionType.ROUTE,
                "behavior": AssertionType.BEHAVIOR,
                "security": AssertionType.SECURITY,
                "function": AssertionType.FUNCTION,
                "file": AssertionType.FILE,
                "pattern": AssertionType.PATTERN,
                "ui": AssertionType.UI,
            }
            assertion_type = type_map.get(
                raw.get("type", "behavior").lower(),
                AssertionType.BEHAVIOR,
            )
            assertions.append(Assertion(
                type=assertion_type,
                description=raw.get("description", ""),
                expect=raw.get("expect", ""),
                importance=float(raw.get("importance", 0.8)),
            ))
        except (KeyError, ValueError, TypeError):
            continue

    return IntentSpec(
        raw_intent=intent_text,
        source=source,
        assertions=assertions,
    )
