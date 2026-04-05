"""Custom YAML rule engine — Semgrep-style rules for DebuggAI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from debuggai.models.issues import Category, Issue, Location, Severity

# Default rules directory (bundled with package)
BUILTIN_RULES_DIR = Path(__file__).parent.parent.parent / "rules"
# Project-local rules
PROJECT_RULES_DIR = ".debuggai/rules"


def load_rules(
    project_dir: Optional[str] = None,
    rule_dirs: Optional[list[str]] = None,
) -> list[dict]:
    """Load all YAML rules from built-in + project + custom directories."""
    rules = []

    dirs_to_check = [BUILTIN_RULES_DIR]

    if project_dir:
        local_rules = Path(project_dir) / PROJECT_RULES_DIR
        if local_rules.exists():
            dirs_to_check.append(local_rules)

    if rule_dirs:
        dirs_to_check.extend(Path(d) for d in rule_dirs)

    for rules_dir in dirs_to_check:
        if not rules_dir.exists():
            continue
        for yaml_file in sorted(rules_dir.rglob("*.yaml")):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if data and "rules" in data:
                    for rule in data["rules"]:
                        rule["_source"] = str(yaml_file)
                        rules.append(rule)
            except (yaml.YAMLError, OSError):
                continue

    return rules


def scan_with_rules(
    file_path: str,
    content: str,
    rules: list[dict],
) -> list[Issue]:
    """Scan a file using custom YAML rules."""
    issues = []
    ext = Path(file_path).suffix.lower()

    # Map extensions to language names
    ext_to_lang = {
        ".py": "python", ".js": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "typescript", ".go": "go",
        ".rs": "rust", ".java": "java", ".rb": "ruby",
    }
    file_lang = ext_to_lang.get(ext, "")

    lines = content.split("\n")

    for rule in rules:
        # Check if rule applies to this file's language
        rule_langs = rule.get("languages", [])
        if rule_langs and file_lang not in rule_langs:
            continue

        # Check file pattern match (if specified)
        file_patterns = rule.get("files", [])
        if file_patterns:
            from fnmatch import fnmatch
            if not any(fnmatch(file_path, p) for p in file_patterns):
                continue

        rule_id = rule.get("id", "custom-rule")
        pattern = rule.get("pattern")
        regex = rule.get("regex")

        if not pattern and not regex:
            continue

        # Compile regex with safety checks
        if regex:
            # Reject patterns likely to cause catastrophic backtracking
            if len(regex) > 500:
                continue
            dangerous_patterns = ["(.*)*", "(.+)+", "(a+)+", "(a*)*"]
            if any(dp in regex for dp in dangerous_patterns):
                continue
            try:
                compiled = re.compile(regex)
            except re.error:
                continue
        elif pattern:
            # Simple pattern: treat as literal search with $VAR as wildcard
            escaped = re.escape(pattern)
            escaped = escaped.replace(r"\$", "$")
            # Replace $IDENTIFIER with a capturing group
            escaped = re.sub(r'\$[A-Z_]+', r'\\S+', escaped)
            try:
                compiled = re.compile(escaped)
            except re.error:
                continue

        # Map severity
        severity_map = {
            "critical": Severity.CRITICAL, "error": Severity.CRITICAL,
            "major": Severity.MAJOR, "warning": Severity.MAJOR,
            "minor": Severity.MINOR, "info": Severity.INFO,
        }
        severity = severity_map.get(
            rule.get("severity", "major").lower(), Severity.MAJOR
        )

        # Map category
        category_map = {
            "security": Category.SECURITY, "performance": Category.PERFORMANCE,
            "logic": Category.LOGIC, "style": Category.STYLE,
            "ai_pattern": Category.AI_PATTERN,
        }
        category = category_map.get(
            rule.get("category", "logic").lower(), Category.LOGIC
        )

        # Check for pattern-not (exclusion)
        pattern_not = rule.get("pattern-not") or rule.get("regex-not")
        not_compiled = None
        if pattern_not:
            try:
                not_compiled = re.compile(pattern_not)
            except re.error:
                pass

        # Scan lines
        for line_num, line in enumerate(lines, 1):
            if compiled.search(line):
                # Check exclusion
                if not_compiled and not_compiled.search(line):
                    continue

                issues.append(Issue(
                    id=f"rule-{rule_id}-{file_path}:{line_num}",
                    severity=severity,
                    category=category,
                    title=rule.get("message", rule_id),
                    description=rule.get("description", ""),
                    location=Location(file=file_path, line=line_num),
                    suggestion=rule.get("suggestion"),
                    confidence=float(rule.get("confidence", 0.8)),
                    engine="rules",
                    rule_id=rule_id,
                    evidence=line.strip()[:200],
                ))

    return issues
