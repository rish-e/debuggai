"""Main code scanning orchestrator — coordinates all code analysis engines."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from debuggai.config import DebuggAIConfig
from debuggai.engines.code.imports import scan_imports
from debuggai.engines.code.performance import scan_performance
from debuggai.engines.code.security import scan_security
from debuggai.engines.code.llm_review import review_with_llm
from debuggai.models.issues import Issue, Severity
from debuggai.utils.git import FileDiff


SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".rb", ".php", ".swift", ".kt",
}

# Directories that should always be skipped — build artifacts, vendored code, bundles
ALWAYS_IGNORE_DIRS = {
    "node_modules", "__pycache__", ".venv", "venv", ".git",
    ".vercel", ".next", ".nuxt", ".output",
    "dist", "build", "out", ".cache",
    "vendor", "third_party", "third-party", "browser-profile",
    ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "coverage", ".nyc_output",
    "eggs", "*.egg-info",
}


def scan_file(
    file_path: str,
    content: str,
    config: DebuggAIConfig,
    project_dir: Optional[str] = None,
    use_llm: bool = True,
) -> list[Issue]:
    """Run all code analysis engines on a single file."""
    ext = Path(file_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return []

    # Skip minified/bundled files — if average line length > 500 chars, it's not human-written
    lines = content.split("\n")
    if len(lines) > 0:
        avg_line_len = len(content) / len(lines)
        if avg_line_len > 500 and len(lines) < 50:
            return []

    issues: list[Issue] = []

    # 1. Hallucinated import detection (fast, no LLM)
    if config.code.rules.get("ai_patterns", True):
        issues.extend(scan_imports(file_path, content, project_dir))

    # 2. Security scanning (fast, regex + AST)
    if config.code.rules.get("security", True):
        issues.extend(scan_security(file_path, content))

    # 3. Performance analysis (fast, AST-based)
    if config.code.rules.get("performance", True):
        issues.extend(scan_performance(file_path, content))

    # 4. LLM-powered semantic review (slow, requires API key)
    if use_llm and config.anthropic_api_key:
        context = f"Project: {config.project_name or 'unknown'}, Type: {config.project_type}"
        issues.extend(review_with_llm(
            file_path, content,
            context=context,
            api_key=config.anthropic_api_key,
        ))

    # Filter by strictness
    issues = _filter_by_strictness(issues, config.code.strictness)

    # Deduplicate
    issues = _deduplicate(issues)

    return issues


def scan_files(
    files: list[FileDiff],
    config: DebuggAIConfig,
    project_dir: Optional[str] = None,
    use_llm: bool = True,
) -> list[Issue]:
    """Scan multiple changed files."""
    all_issues: list[Issue] = []

    for file_diff in files:
        if file_diff.status == "D":
            continue  # Skip deleted files

        # Check ignore patterns
        if _should_ignore(file_diff.path, config.code.ignore):
            continue

        # Read file content
        if file_diff.content:
            content = file_diff.content
        else:
            full_path = Path(project_dir or ".") / file_diff.path
            if full_path.exists():
                content = full_path.read_text()
            else:
                continue

        file_issues = scan_file(
            file_diff.path, content, config,
            project_dir=project_dir,
            use_llm=use_llm,
        )
        all_issues.extend(file_issues)

    return sorted(all_issues, key=lambda i: (
        {"critical": 0, "major": 1, "minor": 2, "info": 3}[i.severity.value],
        i.location.file if i.location else "",
        i.location.line if i.location else 0,
    ))


def scan_directory(
    directory: str,
    config: DebuggAIConfig,
    use_llm: bool = True,
) -> list[Issue]:
    """Scan all supported files in a directory. Uses parallel execution for speed."""
    import hashlib
    from concurrent.futures import ThreadPoolExecutor, as_completed

    root = Path(directory)
    cache = _load_cache(directory)

    # Collect files to scan
    files_to_scan: list[tuple[str, str, str]] = []  # (rel_path, content, file_hash)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        rel_path = str(path.relative_to(root))

        if _should_ignore(rel_path, config.code.ignore):
            continue

        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        # Incremental: skip if file hasn't changed
        file_hash = hashlib.md5(content.encode()).hexdigest()
        if rel_path in cache and cache[rel_path] == file_hash:
            continue

        files_to_scan.append((rel_path, content, file_hash))

    # Scan in parallel (LLM calls are IO-bound, pattern matching is CPU-bound)
    all_issues: list[Issue] = []
    new_cache: dict[str, str] = dict(cache)

    def _scan_one(args: tuple[str, str, str]) -> tuple[list[Issue], str, str]:
        rel_path, content, file_hash = args
        issues = scan_file(
            rel_path, content, config,
            project_dir=directory,
            use_llm=use_llm,
        )
        return issues, rel_path, file_hash

    # Use ThreadPoolExecutor for parallel scanning (up to 8 workers)
    max_workers = min(8, len(files_to_scan)) if files_to_scan else 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scan_one, f): f for f in files_to_scan}
        for future in as_completed(futures):
            try:
                issues, rel_path, file_hash = future.result()
                all_issues.extend(issues)
                new_cache[rel_path] = file_hash
            except Exception:
                pass  # Individual file failures don't stop the scan

    _save_cache(directory, new_cache)

    return sorted(all_issues, key=lambda i: (
        {"critical": 0, "major": 1, "minor": 2, "info": 3}[i.severity.value],
        i.location.file if i.location else "",
        i.location.line if i.location else 0,
    ))


def _load_cache(directory: str) -> dict[str, str]:
    """Load file hash cache for incremental scanning."""
    import json
    cache_path = Path(directory) / ".debuggai" / "cache.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(directory: str, cache: dict[str, str]) -> None:
    """Save file hash cache."""
    import json
    cache_dir = Path(directory) / ".debuggai"
    cache_dir.mkdir(exist_ok=True)
    try:
        (cache_dir / "cache.json").write_text(json.dumps(cache))
    except OSError:
        pass


def _should_ignore(file_path: str, ignore_patterns: list[str]) -> bool:
    """Check if a file should be ignored based on patterns."""
    from fnmatch import fnmatch

    # Always skip build artifacts, vendored code, bundles
    parts = Path(file_path).parts
    for part in parts:
        if part in ALWAYS_IGNORE_DIRS:
            return True

    # Skip minified/bundled files (single-line JS files over 1000 chars are likely bundles)
    if Path(file_path).suffix.lower() in {".js", ".cjs", ".mjs"}:
        base = Path(file_path).stem.lower()
        if any(tag in base for tag in [".min", "-min", "bundle", "vendor", "chunk", "core"]):
            return True

    for pattern in ignore_patterns:
        if fnmatch(file_path, pattern):
            return True
        if "/" in pattern or pattern.endswith("/"):
            clean = pattern.rstrip("/")
            if clean in file_path:
                return True
    return False


def _filter_by_strictness(issues: list[Issue], strictness: str) -> list[Issue]:
    """Filter issues based on strictness level."""
    thresholds = {
        "low": {Severity.CRITICAL},
        "medium": {Severity.CRITICAL, Severity.MAJOR},
        "high": {Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.INFO},
    }
    allowed = thresholds.get(strictness, thresholds["medium"])
    return [i for i in issues if i.severity in allowed]


def _deduplicate(issues: list[Issue]) -> list[Issue]:
    """Remove duplicate issues (same file, line, rule)."""
    seen: set[str] = set()
    unique: list[Issue] = []
    for issue in issues:
        key = f"{issue.location.file if issue.location else ''}:{issue.location.line if issue.location else 0}:{issue.rule_id or issue.title}"
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique
