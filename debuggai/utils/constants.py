"""Shared constants used across DebuggAI modules."""

# Severity ranking for sorting issues (lower = more severe)
SEVERITY_RANK = {
    "critical": 0,
    "major": 1,
    "minor": 2,
    "info": 3,
}

# File extension to language mapping
EXT_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
}

# Supported source code extensions
SUPPORTED_EXTENSIONS = set(EXT_TO_LANGUAGE.keys())

# Directories that should always be skipped
SKIP_DIRS = {
    "node_modules", "__pycache__", ".venv", "venv", ".git",
    ".vercel", ".next", ".nuxt", ".output",
    "dist", "build", "out", ".cache",
    "vendor", "third_party", "third-party", "browser-profile",
    ".tox", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "coverage", ".nyc_output",
    "eggs", "*.egg-info", ".debuggai",
}
