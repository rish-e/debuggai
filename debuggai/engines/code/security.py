"""Security scanner — detect common vulnerabilities in AI-generated code."""

from __future__ import annotations

import re
from pathlib import Path

from debuggai.models.issues import Category, Issue, Location, Severity

# Security patterns: (pattern, severity, title, description, suggestion, rule_id)
# Grouped by language applicability
UNIVERSAL_PATTERNS: list[tuple[re.Pattern, Severity, str, str, str, str]] = [
    (
        re.compile(r"""(?:api[_-]?key|api[_-]?secret|auth[_-]?token|access[_-]?token|secret[_-]?key|private[_-]?key)\s*[=:]\s*['"][A-Za-z0-9+/=_\-]{16,}['"]""", re.IGNORECASE),
        Severity.CRITICAL,
        "Hardcoded secret/API key",
        "A secret or API key appears to be hardcoded in source code. This is a severe security risk if committed to version control.",
        "Move secrets to environment variables or a secrets manager. Use os.environ or process.env.",
        "hardcoded-secret",
    ),
    (
        re.compile(r"""(?:password|passwd|pwd)\s*[=:]\s*['"][^'"]{4,}['"]""", re.IGNORECASE),
        Severity.CRITICAL,
        "Hardcoded password",
        "A password appears to be hardcoded. AI tools frequently generate placeholder credentials that get shipped to production.",
        "Use environment variables for credentials. Never hardcode passwords.",
        "hardcoded-password",
    ),
]

PYTHON_PATTERNS: list[tuple[re.Pattern, Severity, str, str, str, str]] = [
    (
        re.compile(r"""(?:execute|executemany)\s*\(\s*(?:f['"]|['"].*?%s|['"].*?\+|['"].*?\.format)"""),
        Severity.CRITICAL,
        "SQL injection vulnerability",
        "SQL query built with string interpolation/concatenation instead of parameterized queries.",
        "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
        "sql-injection",
    ),
    (
        re.compile(r"""subprocess\.(?:call|run|Popen)\s*\([^)]*shell\s*=\s*True"""),
        Severity.MAJOR,
        "Command injection risk (shell=True)",
        "Using shell=True with subprocess can lead to command injection if input is not sanitized.",
        "Use shell=False (default) and pass arguments as a list instead of a string.",
        "command-injection",
    ),
    (
        re.compile(r"""eval\s*\("""),
        Severity.CRITICAL,
        "Dangerous eval() usage",
        "eval() executes arbitrary code and is a critical security risk. AI often uses eval for quick parsing.",
        "Use ast.literal_eval() for safe literal parsing, or json.loads() for JSON.",
        "dangerous-eval",
    ),
    (
        re.compile(r"""pickle\.loads?\s*\("""),
        Severity.MAJOR,
        "Insecure deserialization (pickle)",
        "pickle.load() can execute arbitrary code when deserializing untrusted data.",
        "Use json for serialization, or ensure only trusted data is deserialized.",
        "insecure-deserialization",
    ),
    (
        re.compile(r"""yaml\.load\s*\([^)]*\)(?!.*Loader)"""),
        Severity.MAJOR,
        "Unsafe YAML loading",
        "yaml.load() without specifying a safe Loader can execute arbitrary code.",
        "Use yaml.safe_load() or yaml.load(data, Loader=yaml.SafeLoader).",
        "unsafe-yaml",
    ),
    (
        re.compile(r"""verify\s*=\s*False"""),
        Severity.MAJOR,
        "SSL verification disabled",
        "Disabling SSL verification makes connections vulnerable to MITM attacks.",
        "Remove verify=False. If using self-signed certs, provide the cert path instead.",
        "ssl-disabled",
    ),
]

JS_TS_PATTERNS: list[tuple[re.Pattern, Severity, str, str, str, str]] = [
    (
        # Only flag innerHTML when assigned a variable or expression, not string/template literals
        # This catches: innerHTML = userInput, innerHTML = getData()
        # This skips: innerHTML = '', innerHTML = `<div>...`, innerHTML = '<tag>'
        re.compile(r"""\.innerHTML\s*=\s*[a-zA-Z_$]"""),
        Severity.CRITICAL,
        "XSS vulnerability (innerHTML)",
        "Setting innerHTML with a variable enables cross-site scripting if the value contains user input.",
        "Use textContent for text, or sanitize with DOMPurify.sanitize() before setting innerHTML.",
        "xss-innerhtml",
    ),
    (
        re.compile(r"""dangerouslySetInnerHTML\s*=\s*\{"""),
        Severity.MAJOR,
        "XSS risk (dangerouslySetInnerHTML)",
        "dangerouslySetInnerHTML can lead to XSS if the content isn't sanitized.",
        "Sanitize content with DOMPurify before passing to dangerouslySetInnerHTML, or use a safe alternative.",
        "xss-react-dangerous",
    ),
    (
        re.compile(r"""(?:eval|Function)\s*\("""),
        Severity.CRITICAL,
        "Dangerous eval/Function usage",
        "eval() and new Function() execute arbitrary code and are security risks.",
        "Use JSON.parse() for data parsing. Avoid eval entirely.",
        "dangerous-eval-js",
    ),
    (
        re.compile(r"""(?:query|sql)\s*(?:=|:)\s*(?:`[^`]*\$\{|['"].*?\+)"""),
        Severity.CRITICAL,
        "SQL injection vulnerability",
        "SQL query built with template literals or concatenation instead of parameterized queries.",
        "Use parameterized queries with your database library (e.g., $1, ? placeholders).",
        "sql-injection-js",
    ),
    (
        re.compile(r"""document\.write\s*\("""),
        Severity.MAJOR,
        "document.write usage",
        "document.write can overwrite the entire page and is a security risk with dynamic content.",
        "Use DOM manipulation methods (createElement, appendChild) instead.",
        "document-write",
    ),
    (
        re.compile(r"""localStorage\.setItem\s*\(\s*['"](?:token|jwt|auth|session|password|secret)""", re.IGNORECASE),
        Severity.MAJOR,
        "Sensitive data in localStorage",
        "Storing tokens/secrets in localStorage makes them accessible to XSS attacks.",
        "Use httpOnly cookies for session tokens, or encrypt before storing.",
        "localstorage-sensitive",
    ),
    (
        re.compile(r"""(?:cors|CORS).*(?:origin|Origin)\s*[:=]\s*['"]\*['"]"""),
        Severity.MAJOR,
        "CORS allows all origins",
        "Setting CORS origin to '*' allows any website to make requests to your API.",
        "Restrict CORS to specific trusted origins.",
        "cors-wildcard",
    ),
]


def scan_security(file_path: str, content: str) -> list[Issue]:
    """Scan a file for security vulnerabilities."""
    issues: list[Issue] = []
    ext = Path(file_path).suffix.lower()
    lines = content.split("\n")

    # Select patterns based on file type
    patterns = list(UNIVERSAL_PATTERNS)
    if ext == ".py":
        patterns.extend(PYTHON_PATTERNS)
    elif ext in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        patterns.extend(JS_TS_PATTERNS)

    in_block_comment = False
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track block comments (/* ... */)
        if "/*" in stripped:
            if "*/" not in stripped:
                in_block_comment = True
            continue  # Skip both single-line and multi-line block comments
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue

        # Skip single-line comments
        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*"):
            continue
        # Skip lines that are regex/pattern definitions (avoid self-detection)
        if "re.compile" in stripped or "Pattern" in stripped:
            continue
        # Skip lines that are just string literals (descriptions, error messages)
        if stripped.startswith('"') or stripped.startswith("'") or stripped.startswith('"""') or stripped.startswith("f'"):
            continue
        # Skip triple-quoted docstrings
        if '"""' in stripped or "'''" in stripped:
            continue

        for pattern, severity, title, desc, suggestion, rule_id in patterns:
            if pattern.search(line):
                # Skip secret/password rules when the value comes from env vars (that's correct usage)
                if rule_id in ("hardcoded-secret", "hardcoded-password"):
                    if any(safe in stripped for safe in [
                        "os.getenv", "os.environ", "process.env",
                        "getenv(", "environ[", "environ.get",
                        "config(", "Config(",
                    ]):
                        continue

                # Skip SQL injection when the query uses ? placeholders for values
                # (f-strings for column/table names with ? for values is safe)
                if rule_id in ("sql-injection", "sql-injection-js"):
                    nearby_block = "\n".join(lines[max(0, line_num - 25):min(len(lines), line_num + 10)])
                    # Safe: f-string for structure but ? for values
                    if "?" in nearby_block and ("placeholders" in nearby_block or
                        "params" in nearby_block or ", vals" in nearby_block or
                        ", params" in nearby_block or "VALUES (" in nearby_block.upper()):
                        continue
                    # Safe: only interpolating table/column names from a hardcoded loop
                    if "for table in" in nearby_block or "for col in" in nearby_block:
                        continue
                    # Safe: column name toggle (col = "x" if cond else "y")
                    if re.search(r'col\s*=\s*["\']', nearby_block):
                        continue

                # Avoid duplicate issues on the same line with the same rule
                issue_id = f"sec-{rule_id}-{file_path}:{line_num}"
                if not any(i.id == issue_id for i in issues):
                    issues.append(Issue(
                        id=issue_id,
                        severity=severity,
                        category=Category.SECURITY,
                        title=title,
                        description=desc,
                        location=Location(file=file_path, line=line_num),
                        suggestion=suggestion,
                        confidence=0.85,
                        engine="code",
                        rule_id=rule_id,
                        evidence=stripped[:200],
                    ))

    return issues
