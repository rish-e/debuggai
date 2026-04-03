"""Performance analyzer — detect performance anti-patterns in AI-generated code."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from debuggai.models.issues import Category, Issue, Location, Severity


def scan_performance(file_path: str, content: str) -> list[Issue]:
    """Scan a file for performance anti-patterns."""
    ext = Path(file_path).suffix.lower()
    if ext == ".py":
        return _scan_python_performance(file_path, content)
    elif ext in {".js", ".jsx", ".ts", ".tsx"}:
        return _scan_js_performance(file_path, content)
    return []


def _scan_python_performance(file_path: str, content: str) -> list[Issue]:
    """Detect Python-specific performance issues."""
    issues: list[Issue] = []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return issues

    # Detect nested loops (potential O(n²))
    _detect_nested_loops_python(tree, file_path, issues)
    # Detect I/O in loops
    _detect_io_in_loops_python(tree, file_path, content, issues)
    # Detect list concatenation in loops
    _detect_list_concat_in_loops(tree, file_path, content, issues)

    return issues


def _detect_nested_loops_python(tree: ast.AST, file_path: str, issues: list[Issue]) -> None:
    """Find nested for loops iterating over data structures."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            # Check if there's a nested loop inside
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, (ast.For, ast.AsyncFor)):
                    # Check if both loops iterate over variables (not range(small_number))
                    if _is_data_iteration(node) and _is_data_iteration(child):
                        issues.append(Issue(
                            id=f"perf-nested-loop-{file_path}:{node.lineno}",
                            severity=Severity.MAJOR,
                            category=Category.PERFORMANCE,
                            title="Potential O(n²) nested loop",
                            description=(
                                f"Nested loops at lines {node.lineno} and {child.lineno} "
                                "may cause O(n²) performance. AI tools commonly generate "
                                "nested iterations that can be optimized."
                            ),
                            location=Location(file=file_path, line=node.lineno, end_line=child.lineno),
                            suggestion="Consider using a lookup dict/set, or itertools for more efficient iteration.",
                            confidence=0.7,
                            engine="code",
                            rule_id="nested-loop-on2",
                        ))
                    break  # Only report outermost nested pair


def _is_data_iteration(node: ast.For | ast.AsyncFor) -> bool:
    """Check if a for loop iterates over a data variable (not a small range)."""
    if isinstance(node.iter, ast.Call):
        func = node.iter.func
        if isinstance(func, ast.Name) and func.id == "range":
            # range(10) is fine, range(len(x)) is not
            if node.iter.args:
                arg = node.iter.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, int) and arg.value <= 20:
                    return False
    return True


def _detect_io_in_loops_python(
    tree: ast.AST, file_path: str, content: str, issues: list[Issue]
) -> None:
    """Detect I/O operations inside loops."""
    io_functions = {
        "open", "read", "write", "print",
        "requests.get", "requests.post", "requests.put", "requests.delete",
        "urllib.request.urlopen", "httpx.get", "httpx.post",
    }

    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func_name = _get_call_name(child)
                    if func_name and any(func_name.endswith(io) for io in io_functions):
                        issues.append(Issue(
                            id=f"perf-io-loop-{file_path}:{child.lineno}",
                            severity=Severity.MAJOR,
                            category=Category.PERFORMANCE,
                            title=f"I/O operation in loop: {func_name}",
                            description=(
                                f"'{func_name}' called inside a loop at line {child.lineno}. "
                                "Each iteration performs I/O which is expensive."
                            ),
                            location=Location(file=file_path, line=child.lineno),
                            suggestion="Batch I/O operations outside the loop, or use async/concurrent patterns.",
                            confidence=0.8,
                            engine="code",
                            rule_id="io-in-loop",
                        ))


def _detect_list_concat_in_loops(
    tree: ast.AST, file_path: str, content: str, issues: list[Issue]
) -> None:
    """Detect string/list concatenation in loops (O(n²) pattern)."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            for child in ast.walk(node):
                if isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add):
                    if isinstance(child.target, ast.Name):
                        issues.append(Issue(
                            id=f"perf-concat-loop-{file_path}:{child.lineno}",
                            severity=Severity.MINOR,
                            category=Category.PERFORMANCE,
                            title="Concatenation in loop",
                            description=(
                                f"'+=' concatenation in loop at line {child.lineno}. "
                                "For strings this is O(n²). For lists, use .append() or list comprehension."
                            ),
                            location=Location(file=file_path, line=child.lineno),
                            suggestion="Use list.append() and ''.join(), or a list comprehension.",
                            confidence=0.6,
                            engine="code",
                            rule_id="concat-in-loop",
                        ))


def _get_call_name(node: ast.Call) -> str | None:
    """Get the full name of a function call."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    elif isinstance(node.func, ast.Attribute):
        parts = []
        current = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _scan_js_performance(file_path: str, content: str) -> list[Issue]:
    """Detect JS/TS performance issues using regex patterns."""
    issues: list[Issue] = []
    lines = content.split("\n")

    # Track if we're inside a loop
    loop_depth = 0
    loop_start_line = 0

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track loop depth (approximate)
        if re.search(r"\b(?:for|while|forEach|\.map|\.filter|\.reduce)\s*\(", stripped):
            if loop_depth == 0:
                loop_start_line = line_num
            loop_depth += 1

        # Detect fetch/axios in loops
        if loop_depth > 0 and re.search(r"\b(?:fetch|axios\.\w+|http\.\w+)\s*\(", stripped):
            issues.append(Issue(
                id=f"perf-fetch-loop-{file_path}:{line_num}",
                severity=Severity.MAJOR,
                category=Category.PERFORMANCE,
                title="HTTP request in loop",
                description=f"Network request inside a loop at line {line_num}. Each iteration makes a separate HTTP call.",
                location=Location(file=file_path, line=line_num),
                suggestion="Batch requests using Promise.all() or use a bulk API endpoint.",
                confidence=0.8,
                engine="code",
                rule_id="fetch-in-loop",
            ))

        # Detect querySelector in loops
        if loop_depth > 0 and re.search(r"document\.querySelector", stripped):
            issues.append(Issue(
                id=f"perf-dom-loop-{file_path}:{line_num}",
                severity=Severity.MINOR,
                category=Category.PERFORMANCE,
                title="DOM query in loop",
                description=f"DOM query inside a loop at line {line_num}. Cache the element reference outside the loop.",
                location=Location(file=file_path, line=line_num),
                suggestion="Move querySelector outside the loop and cache the result.",
                confidence=0.7,
                engine="code",
                rule_id="dom-in-loop",
            ))

        # Approximate loop end tracking
        if "}" in stripped and loop_depth > 0:
            loop_depth = max(0, loop_depth - stripped.count("}"))

        # Detect synchronous operations that should be async
        if re.search(r"\bfs\.readFileSync\b|\bfs\.writeFileSync\b", stripped):
            issues.append(Issue(
                id=f"perf-sync-io-{file_path}:{line_num}",
                severity=Severity.MINOR,
                category=Category.PERFORMANCE,
                title="Synchronous file I/O",
                description=f"Synchronous file operation at line {line_num} blocks the event loop.",
                location=Location(file=file_path, line=line_num),
                suggestion="Use fs.promises or the async fs methods (readFile, writeFile).",
                confidence=0.9,
                engine="code",
                rule_id="sync-io",
            ))

    return issues
