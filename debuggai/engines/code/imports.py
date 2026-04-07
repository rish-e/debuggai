"""Hallucinated import detector — finds imports that reference non-existent packages/modules."""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from debuggai.models.issues import Category, Issue, Location, Severity

# Common standard library modules that should never be flagged
PYTHON_STDLIB = {
    "abc", "aifc", "argparse", "array", "ast", "asyncio", "atexit", "base64",
    "binascii", "bisect", "builtins", "calendar", "cgi", "cgitb", "chunk",
    "cmath", "cmd", "code", "codecs", "codeop", "collections", "colorsys",
    "compileall", "concurrent", "configparser", "contextlib", "contextvars",
    "copy", "copyreg", "cProfile", "crypt", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis",
    "distutils", "doctest", "email", "encodings", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
    "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob",
    "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "lib2to3", "linecache",
    "locale", "logging", "lzma", "mailbox", "mailcap", "marshal", "math",
    "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc",
    "nis", "nntplib", "numbers", "operator", "optparse", "os", "ossaudiodev",
    "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
    "platform", "plistlib", "poplib", "posix", "posixpath", "pprint",
    "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr",
    "pydoc", "queue", "quopri", "random", "re", "readline", "reprlib",
    "resource", "rlcompleter", "runpy", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtpd",
    "smtplib", "sndhdr", "socket", "socketserver", "spwd", "sqlite3",
    "ssl", "stat", "statistics", "string", "stringprep", "struct",
    "subprocess", "sunau", "symtable", "sys", "sysconfig", "syslog",
    "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test",
    "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
    "turtle", "turtledemo", "types", "typing", "unicodedata", "unittest",
    "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml",
    "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "_thread",
    "typing_extensions", "annotations", "__future__",
}

# Node.js built-in modules
NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "console", "constants",
    "crypto", "dgram", "dns", "domain", "events", "fs", "http", "https",
    "module", "net", "os", "path", "perf_hooks", "process", "punycode",
    "querystring", "readline", "repl", "stream", "string_decoder", "sys",
    "timers", "tls", "tty", "url", "util", "v8", "vm", "wasi",
    "worker_threads", "zlib", "node:test", "node:assert",
}


def check_python_imports(file_path: str, content: str, project_dir: Optional[str] = None) -> list[Issue]:
    """Check Python imports for hallucinated packages."""
    issues = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return issues

    installed_packages = _get_installed_python_packages()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if _is_hallucinated_python(root_module, installed_packages, project_dir, file_path):
                    issues.append(_make_import_issue(
                        file_path, node.lineno, alias.name, "python",
                        f"Module '{alias.name}' is not installed and not in standard library"
                    ))

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_module = node.module.split(".")[0]
                if _is_hallucinated_python(root_module, installed_packages, project_dir, file_path):
                    issues.append(_make_import_issue(
                        file_path, node.lineno, node.module, "python",
                        f"Module '{node.module}' is not installed and not in standard library"
                    ))

    return issues


def _is_hallucinated_python(
    module: str,
    installed: set[str],
    project_dir: Optional[str],
    source_file: str,
) -> bool:
    """Check if a Python module is hallucinated."""
    if module in PYTHON_STDLIB:
        return False
    if module in installed:
        return False

    # Check if it's a local module (relative to project dir and parents)
    dirs_to_check = []
    if project_dir:
        dirs_to_check.append(Path(project_dir))
        dirs_to_check.append(Path(project_dir).parent)  # Check parent (for package imports)
    dirs_to_check.append(Path(source_file).parent)

    for check_dir in dirs_to_check:
        local_path = check_dir / module
        local_init = check_dir / module / "__init__.py"
        local_file = check_dir / f"{module}.py"
        if local_path.exists() or local_init.exists() or local_file.exists():
            return False

    # Check if importable (catches pip -e installed packages)
    try:
        import importlib.util
        if importlib.util.find_spec(module) is not None:
            return False
    except (ModuleNotFoundError, ValueError):
        pass

    return True


_cached_python_packages: Optional[set[str]] = None
_cached_npm_packages: dict[str, set[str]] = {}


def _get_installed_python_packages() -> set[str]:
    """Get set of installed Python packages. Cached per session."""
    global _cached_python_packages
    if _cached_python_packages is not None:
        return _cached_python_packages
    try:
        result = subprocess.run(
            ["pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            packages = json.loads(result.stdout)
            _cached_python_packages = {
                pkg["name"].lower().replace("-", "_")
                for pkg in packages
            }
            return _cached_python_packages
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    _cached_python_packages = set()
    return _cached_python_packages


def check_js_imports(file_path: str, content: str, project_dir: Optional[str] = None) -> list[Issue]:
    """Check JavaScript/TypeScript imports for hallucinated packages."""
    issues = []
    installed = _get_installed_npm_packages(project_dir)

    # Match: import ... from "package"
    import_pattern = re.compile(
        r"""(?:import|export)\s+.*?from\s+['"]([^'"./][^'"]*?)['"]""",
        re.MULTILINE,
    )
    # Match: require("package")
    require_pattern = re.compile(
        r"""require\s*\(\s*['"]([^'"./][^'"]*?)['"]\s*\)""",
        re.MULTILINE,
    )

    for line_num, line in enumerate(content.split("\n"), 1):
        for pattern in [import_pattern, require_pattern]:
            for match in pattern.finditer(line):
                pkg = match.group(1)
                # Get the package name (handle scoped packages @org/pkg)
                if pkg.startswith("@"):
                    pkg_name = "/".join(pkg.split("/")[:2])
                else:
                    pkg_name = pkg.split("/")[0]

                if _is_hallucinated_js(pkg_name, installed):
                    issues.append(_make_import_issue(
                        file_path, line_num, pkg, "javascript",
                        f"Package '{pkg_name}' is not in node_modules or package.json"
                    ))

    return issues


def _is_hallucinated_js(package: str, installed: set[str]) -> bool:
    """Check if a JS/TS package is hallucinated."""
    if package in NODE_BUILTINS or package.startswith("node:"):
        return False
    # Skip path aliases (@/, ~/, #/) — these are resolved by bundler/tsconfig, not npm
    if package.startswith("@/") or package.startswith("~/") or package.startswith("#/"):
        return False
    if package in installed:
        return False
    # Common aliases/built-in patterns
    if package in {"react", "react-dom", "next", "vue", "svelte", "angular"}:
        # Only flag if truly not installed
        return package not in installed
    return True


def _get_installed_npm_packages(project_dir: Optional[str] = None) -> set[str]:
    """Get set of installed npm packages from package.json. Cached per project dir."""
    cache_key = str(project_dir or Path.cwd())
    if cache_key in _cached_npm_packages:
        return _cached_npm_packages[cache_key]

    packages: set[str] = set()
    search_dir = Path(project_dir) if project_dir else Path.cwd()

    # Check package.json
    pkg_json = search_dir / "package.json"
    if pkg_json.exists():
        try:
            with open(pkg_json) as f:
                pkg = json.load(f)
            for key in ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]:
                if key in pkg:
                    packages.update(pkg[key].keys())
        except (json.JSONDecodeError, KeyError):
            pass

    # Also check node_modules for packages installed but not in package.json
    node_modules = search_dir / "node_modules"
    if node_modules.exists():
        for item in node_modules.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                if item.name.startswith("@"):
                    for sub in item.iterdir():
                        if sub.is_dir():
                            packages.add(f"{item.name}/{sub.name}")
                else:
                    packages.add(item.name)

    _cached_npm_packages[cache_key] = packages
    return packages


def _make_import_issue(
    file_path: str,
    line: int,
    import_name: str,
    language: str,
    description: str,
) -> Issue:
    """Create an Issue for a hallucinated import."""
    return Issue(
        id=f"import-{file_path}:{line}-{import_name}",
        severity=Severity.CRITICAL,
        category=Category.IMPORT,
        title=f"Hallucinated import: {import_name}",
        description=description,
        location=Location(file=file_path, line=line),
        suggestion=f"Verify that '{import_name}' exists. Install it or remove the import.",
        confidence=0.9,
        engine="code",
        rule_id="hallucinated-import",
        evidence=f"Import '{import_name}' not found in installed {language} packages",
    )


def scan_imports(file_path: str, content: str, project_dir: Optional[str] = None) -> list[Issue]:
    """Scan a file for hallucinated imports based on file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".py":
        return check_python_imports(file_path, content, project_dir)
    elif ext in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return check_js_imports(file_path, content, project_dir)
    return []
