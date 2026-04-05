"""Deep analyzer — architectural anti-patterns + runtime behavior analysis.

Layer 2: Finds issues that only exist because of how the system is deployed.
Layer 3: Finds runtime behavior bugs without executing code.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from debuggai.engines.deep.indexer import ProjectIndex, FileInfo
from debuggai.models.issues import Category, Issue, Location, Severity


def analyze_architecture(index: ProjectIndex) -> list[Issue]:
    """Run all architectural and runtime analysis on an indexed project."""
    issues: list[Issue] = []

    # Layer 2: Architectural anti-patterns
    issues.extend(_check_serverless_state(index))
    issues.extend(_check_cors_abuse(index))
    issues.extend(_check_cache_headers(index))
    issues.extend(_check_timeout_mismatches(index))
    issues.extend(_check_recursive_invocation(index))

    # Layer 3: Runtime behavior
    issues.extend(_check_memory_leaks(index))
    issues.extend(_check_race_conditions(index))
    issues.extend(_check_missing_safeguards(index))

    return issues


# ── Layer 2: Architectural Anti-Patterns ──────────────────────


def _check_serverless_state(index: ProjectIndex) -> list[Issue]:
    """Detect stateful code in serverless environments."""
    if not index.context.is_serverless:
        return []

    issues = []
    # Only check server-side files (api routes, functions, handlers)
    server_indicators = ["api/", "functions/", "pages/api/", "app/api/", "server/", "lambda/"]

    for f in index.files:
        if not f.has_global_state:
            continue
        # Skip client-side files — they run in the browser, not serverless
        if not any(ind in f.path for ind in server_indicators):
            continue

        file_path = Path(index.root) / f.path
        if not file_path.exists():
            continue
        content = file_path.read_text()
        lines = content.split("\n")

        for line_num in f.global_state_lines:
            if line_num > len(lines):
                continue
            line = lines[line_num - 1].strip()

            # Check if it looks like a cache, counter, rate limiter, or session store
            state_patterns = [
                (r'(?:cache|Cache|CACHE)', "cache"),
                (r'(?:rate|Rate|limit|Limit|throttle)', "rate limiter"),
                (r'(?:session|Session|SESSION)', "session store"),
                (r'(?:counter|count|COUNT)', "counter"),
                (r'(?:Map|map|dict|Dict)\s*\(', "in-memory map"),
                (r'\{\s*\}', "in-memory object"),
                (r'\[\s*\]', "in-memory array"),
            ]

            state_type = "mutable state"
            for pattern, name in state_patterns:
                if re.search(pattern, line):
                    state_type = name
                    break

            issues.append(Issue(
                id=f"deep-serverless-state-{f.path}:{line_num}",
                severity=Severity.CRITICAL,
                category=Category.LOGIC,
                title=f"Stateful {state_type} in serverless function",
                description=(
                    f"Module-level {state_type} at {f.path}:{line_num} will reset on every "
                    f"cold start. Deployed on {index.context.deployment}, which is stateless. "
                    f"Any accumulated state (rate limits, cached data, counters) is lost "
                    f"when the function container is recycled."
                ),
                location=Location(file=f.path, line=line_num),
                suggestion=(
                    f"Use persistent storage instead: Redis/Upstash for rate limiting, "
                    f"database for caching, external session store for sessions."
                ),
                confidence=0.85,
                engine="deep",
                rule_id="serverless-stateful-code",
                evidence=line[:200],
            ))

    return issues


def _check_cors_abuse(index: ProjectIndex) -> list[Issue]:
    """Detect CORS wildcard combined with API keys/paid services."""
    issues = []
    has_wildcard_cors = False
    cors_file = ""
    cors_line = 0

    # Check vercel.json headers
    if "vercel.json" in index.config_files:
        content = index.config_files["vercel.json"]
        if '"*"' in content and ("Access-Control-Allow-Origin" in content or "access-control" in content.lower()):
            has_wildcard_cors = True
            cors_file = "vercel.json"
            for i, line in enumerate(content.split("\n"), 1):
                if '"*"' in line:
                    cors_line = i
                    break

    # Check source files for cors: "*"
    if not has_wildcard_cors:
        for f in index.files:
            file_path = Path(index.root) / f.path
            if not file_path.exists():
                continue
            try:
                content = file_path.read_text()
            except (UnicodeDecodeError, PermissionError):
                continue
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(r"""(?:cors|CORS|origin|Origin)\s*[:=]\s*['"]?\*['"]?""", line):
                    has_wildcard_cors = True
                    cors_file = f.path
                    cors_line = i
                    break
            if has_wildcard_cors:
                break

    if has_wildcard_cors and index.context.is_api:
        issues.append(Issue(
            id=f"deep-cors-wildcard-{cors_file}:{cors_line}",
            severity=Severity.CRITICAL,
            category=Category.SECURITY,
            title="CORS wildcard allows any website to use your API",
            description=(
                f"Access-Control-Allow-Origin: * at {cors_file}:{cors_line} "
                f"means any website can make requests to your API endpoints. "
                f"If you have API keys or paid services behind these endpoints, "
                f"anyone can drain your quota or abuse your service."
            ),
            location=Location(file=cors_file, line=cors_line),
            suggestion="Set origin to your specific domain(s), or validate the Origin header.",
            confidence=0.9,
            engine="deep",
            rule_id="cors-wildcard-api",
        ))

    return issues


def _check_cache_headers(index: ProjectIndex) -> list[Issue]:
    """Detect large static assets without cache headers."""
    issues = []
    root = Path(index.root)

    # Check for large static files
    static_dirs = ["public", "static", "assets", "dist"]
    large_extensions = {".wasm", ".js", ".css", ".woff2", ".woff", ".ttf", ".otf"}

    for static_dir in static_dirs:
        dir_path = root / static_dir
        if not dir_path.exists():
            continue
        for path in dir_path.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in large_extensions:
                continue
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb < 1:
                continue

            # Check if vercel.json or similar has cache headers for this type
            has_cache = False
            if "vercel.json" in index.config_files:
                vj = index.config_files["vercel.json"]
                if "Cache-Control" in vj or "cache-control" in vj:
                    has_cache = True

            if not has_cache:
                rel = str(path.relative_to(root))
                issues.append(Issue(
                    id=f"deep-no-cache-{rel}",
                    severity=Severity.MAJOR,
                    category=Category.PERFORMANCE,
                    title=f"Large asset without cache headers ({size_mb:.1f}MB)",
                    description=(
                        f"{rel} is {size_mb:.1f}MB but has no Cache-Control headers. "
                        f"Every visitor re-downloads it on every page load."
                    ),
                    location=Location(file=rel),
                    suggestion=(
                        f"Add Cache-Control headers for static assets. "
                        f"For immutable assets: Cache-Control: public, max-age=31536000, immutable"
                    ),
                    confidence=0.8,
                    engine="deep",
                    rule_id="missing-cache-headers",
                ))

    return issues


def _check_timeout_mismatches(index: ProjectIndex) -> list[Issue]:
    """Detect API calls with timeouts longer than serverless execution limit."""
    if not index.context.is_serverless:
        return []

    issues = []
    # Serverless timeout limits
    limits = {
        "vercel": 30,     # Hobby: 30s, Pro: 5min
        "netlify": 26,
        "aws-lambda": 900,
    }
    max_timeout = limits.get(index.context.deployment or "", 30)

    for f in index.files:
        file_path = Path(index.root) / f.path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        # Look for timeout settings that exceed the platform limit
        for i, line in enumerate(content.split("\n"), 1):
            timeout_match = re.search(r'timeout\s*[:=]\s*(\d+)', line, re.IGNORECASE)
            if timeout_match:
                timeout_val = int(timeout_match.group(1))
                # Heuristic: if > 1000, probably milliseconds
                if timeout_val > 1000:
                    timeout_val = timeout_val // 1000
                if timeout_val > max_timeout:
                    issues.append(Issue(
                        id=f"deep-timeout-mismatch-{f.path}:{i}",
                        severity=Severity.MAJOR,
                        category=Category.LOGIC,
                        title=f"Timeout ({timeout_val}s) exceeds {index.context.deployment} limit ({max_timeout}s)",
                        description=(
                            f"Timeout set to {timeout_val}s at {f.path}:{i}, but {index.context.deployment} "
                            f"kills functions after {max_timeout}s. The request will be terminated before "
                            f"the timeout fires."
                        ),
                        location=Location(file=f.path, line=i),
                        suggestion=f"Set timeout to less than {max_timeout}s, or add retry logic.",
                        confidence=0.7,
                        engine="deep",
                        rule_id="timeout-exceeds-platform",
                        evidence=line.strip()[:200],
                    ))

    return issues


def _check_recursive_invocation(index: ProjectIndex) -> list[Issue]:
    """Detect serverless functions that might invoke themselves."""
    if not index.context.is_serverless:
        return []

    issues = []
    for f in index.files:
        # Only check API route files
        if not any(d in f.path for d in ["api/", "functions/", "pages/api/", "app/api/"]):
            continue

        file_path = Path(index.root) / f.path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        # Check if the file makes HTTP requests to its own API
        for i, line in enumerate(content.split("\n"), 1):
            if re.search(r'(?:fetch|axios|http)\s*\(\s*[\'"`](?:https?://.*)?/api/', line):
                issues.append(Issue(
                    id=f"deep-recursive-invocation-{f.path}:{i}",
                    severity=Severity.CRITICAL,
                    category=Category.LOGIC,
                    title="Possible recursive serverless invocation",
                    description=(
                        f"API route at {f.path}:{i} makes an HTTP request to /api/*, which may "
                        f"trigger another serverless function invocation. On {index.context.deployment}, "
                        f"this can create an infinite loop costing hundreds of dollars in minutes."
                    ),
                    location=Location(file=f.path, line=i),
                    suggestion="Use direct function calls instead of HTTP requests within the same service.",
                    confidence=0.6,
                    engine="deep",
                    rule_id="recursive-serverless-invocation",
                    evidence=line.strip()[:200],
                ))

    return issues


# ── Layer 3: Runtime Behavior Analysis ────────────────────────


def _check_memory_leaks(index: ProjectIndex) -> list[Issue]:
    """Detect common memory leak patterns without running code."""
    issues = []

    for f in index.files:
        if f.language not in ("javascript", "typescript"):
            continue

        file_path = Path(index.root) / f.path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        lines = content.split("\n")

        # 1. addEventListener without removeEventListener
        # Track (event_type, handler_name) pairs for accuracy
        add_listeners: list[tuple[int, str, str]] = []  # (line, event, handler)
        remove_pairs: set[tuple[str, str]] = set()  # (event, handler)

        for i, line in enumerate(lines, 1):
            add_match = re.search(r'addEventListener\s*\(\s*[\'"](\w+)[\'"]\s*,\s*(\w+)', line)
            if add_match:
                add_listeners.append((i, add_match.group(1), add_match.group(2)))
            elif re.search(r'addEventListener\s*\(\s*[\'"](\w+)[\'"]', line):
                # Anonymous handler — always a leak candidate
                m = re.search(r'addEventListener\s*\(\s*[\'"](\w+)[\'"]', line)
                add_listeners.append((i, m.group(1), "<anonymous>"))

            rem_match = re.search(r'removeEventListener\s*\(\s*[\'"](\w+)[\'"]\s*,\s*(\w+)', line)
            if rem_match:
                remove_pairs.add((rem_match.group(1), rem_match.group(2)))

        for line_num, event_type, handler in add_listeners:
            if (event_type, handler) not in remove_pairs and handler != "<anonymous>":
                # Check if ANY removal exists for this event (weaker match)
                if any(evt == event_type for evt, _ in remove_pairs):
                    continue  # Different handler removed for same event — likely OK
            if handler == "<anonymous>" or (event_type, handler) not in remove_pairs:
                issues.append(Issue(
                    id=f"deep-event-leak-{f.path}:{line_num}",
                    severity=Severity.MAJOR,
                    category=Category.PERFORMANCE,
                    title=f"Event listener '{event_type}' never removed",
                    description=(
                        f"addEventListener('{event_type}') at {f.path}:{line_num} has no matching "
                        f"removeEventListener. If this function runs multiple times (e.g., on re-render), "
                        f"listeners accumulate — each call adds another handler."
                    ),
                    location=Location(file=f.path, line=line_num),
                    suggestion="Add a corresponding removeEventListener in cleanup/teardown.",
                    confidence=0.75,
                    engine="deep",
                    rule_id="event-listener-leak",
                ))

        # 2. createObjectURL without revokeObjectURL
        create_urls: list[int] = []
        has_revoke = "revokeObjectURL" in content

        for i, line in enumerate(lines, 1):
            if "createObjectURL" in line:
                create_urls.append(i)

        if create_urls and not has_revoke:
            for line_num in create_urls:
                issues.append(Issue(
                    id=f"deep-blob-leak-{f.path}:{line_num}",
                    severity=Severity.MAJOR,
                    category=Category.PERFORMANCE,
                    title="Blob URL created but never revoked",
                    description=(
                        f"URL.createObjectURL() at {f.path}:{line_num} with no URL.revokeObjectURL() "
                        f"in the file. Blob URLs hold data in memory until revoked. After multiple "
                        f"operations, this leaks hundreds of MB."
                    ),
                    location=Location(file=f.path, line=line_num),
                    suggestion="Call URL.revokeObjectURL(url) when the blob URL is no longer needed.",
                    confidence=0.85,
                    engine="deep",
                    rule_id="blob-url-leak",
                ))

        # 3. React useEffect without cleanup
        for i, line in enumerate(lines, 1):
            if "useEffect" in line:
                # Look ahead for return statement in the effect
                block_end = min(i + 30, len(lines))
                block = "\n".join(lines[i:block_end])
                # Check if there's addEventListener in the effect without cleanup return
                if "addEventListener" in block and "return" not in block.split("}, [")[0] if "}, [" in block else block:
                    issues.append(Issue(
                        id=f"deep-useeffect-cleanup-{f.path}:{i}",
                        severity=Severity.MAJOR,
                        category=Category.PERFORMANCE,
                        title="useEffect adds listener without cleanup",
                        description=(
                            f"useEffect at {f.path}:{i} adds an event listener but doesn't "
                            f"return a cleanup function. Every re-render adds a new listener "
                            f"without removing the old one."
                        ),
                        location=Location(file=f.path, line=i),
                        suggestion="Return a cleanup function: return () => element.removeEventListener(...)",
                        confidence=0.8,
                        engine="deep",
                        rule_id="useeffect-missing-cleanup",
                    ))

    return issues


def _check_race_conditions(index: ProjectIndex) -> list[Issue]:
    """Detect potential race conditions from unguarded async operations."""
    issues = []

    for f in index.files:
        if f.language not in ("javascript", "typescript"):
            continue

        file_path = Path(index.root) / f.path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        lines = content.split("\n")

        # Look for async operations triggered by UI events without guard variables
        # Pattern: onclick/addEventListener handler that starts async work without checking isProcessing
        for i, line in enumerate(lines, 1):
            # Find event handlers that call async functions
            if re.search(r'(?:onclick|addEventListener|\.on\()\s*.*(?:async|await|fetch|\.then)', line):
                # Check surrounding context for guard variable
                context_start = max(0, i - 10)
                context_end = min(len(lines), i + 20)
                context_block = "\n".join(lines[context_start:context_end])

                guard_patterns = [
                    r'(?:isProcessing|isLoading|isBusy|isRunning|disabled|loading)',
                    r'if\s*\(\s*(?:isProcessing|isLoading|isBusy)',
                    r'\.disabled\s*=\s*true',
                ]
                has_guard = any(re.search(p, context_block) for p in guard_patterns)

                if not has_guard:
                    issues.append(Issue(
                        id=f"deep-race-condition-{f.path}:{i}",
                        severity=Severity.MAJOR,
                        category=Category.LOGIC,
                        title="Async operation without re-entry guard",
                        description=(
                            f"Event handler at {f.path}:{i} starts an async operation but doesn't "
                            f"prevent re-triggering. If the user clicks again during processing, "
                            f"parallel operations may conflict or crash."
                        ),
                        location=Location(file=f.path, line=i),
                        suggestion="Add a guard variable (e.g., isProcessing) and disable the trigger during async work.",
                        confidence=0.6,
                        engine="deep",
                        rule_id="unguarded-async-handler",
                    ))

    return issues


def _check_missing_safeguards(index: ProjectIndex) -> list[Issue]:
    """Detect missing operational safeguards."""
    issues = []

    for f in index.files:
        file_path = Path(index.root) / f.path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        lines = content.split("\n")

        # 1. External API calls without timeout
        for i, line in enumerate(lines, 1):
            if re.search(r'(?:fetch|axios\.\w+|requests\.\w+|httpx\.\w+|urllib)', line):
                # Check if timeout is set nearby
                context = "\n".join(lines[max(0, i-3):min(len(lines), i+5)])
                if "timeout" not in context.lower():
                    issues.append(Issue(
                        id=f"deep-no-timeout-{f.path}:{i}",
                        severity=Severity.MAJOR,
                        category=Category.LOGIC,
                        title="External API call without timeout",
                        description=(
                            f"HTTP request at {f.path}:{i} has no timeout. If the remote server "
                            f"hangs, your application hangs indefinitely."
                        ),
                        location=Location(file=f.path, line=i),
                        suggestion="Add a timeout: fetch(url, {signal: AbortSignal.timeout(10000)}) or requests.get(url, timeout=10)",
                        confidence=0.7,
                        engine="deep",
                        rule_id="missing-api-timeout",
                        evidence=line.strip()[:200],
                    ))

        # 2. File input without size validation (web apps)
        if index.context.is_web_app and f.language in ("javascript", "typescript"):
            has_file_input = False
            has_size_check = False
            file_input_line = 0

            for i, line in enumerate(lines, 1):
                if re.search(r'(?:type\s*=\s*[\'"]file[\'"]|\.files\[|FileReader|readAsArrayBuffer)', line):
                    has_file_input = True
                    if not file_input_line:
                        file_input_line = i
                if re.search(r'\.size\s*[><=]|maxSize|MAX_SIZE|file_size|fileSize', line):
                    has_size_check = True

            if has_file_input and not has_size_check:
                issues.append(Issue(
                    id=f"deep-no-filesize-check-{f.path}:{file_input_line}",
                    severity=Severity.MAJOR,
                    category=Category.LOGIC,
                    title="File upload without size validation",
                    description=(
                        f"File input handling at {f.path}:{file_input_line} with no size check. "
                        f"A user could upload a multi-GB file and crash the browser or exceed "
                        f"server limits."
                    ),
                    location=Location(file=f.path, line=file_input_line),
                    suggestion="Check file.size before processing: if (file.size > MAX_SIZE) return alert(...)",
                    confidence=0.8,
                    engine="deep",
                    rule_id="missing-filesize-validation",
                ))

    return issues
