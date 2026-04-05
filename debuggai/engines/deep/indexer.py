"""Project indexer — builds a structured map of the entire codebase.

Extracts file structure, dependencies, imports, exports, and generates
an architecture summary via LLM.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from debuggai.context import ProjectContext, detect_context

SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java"}

SKIP_DIRS = {
    "node_modules", "__pycache__", ".venv", "venv", ".git", ".vercel", ".next",
    ".nuxt", "dist", "build", "out", ".cache", "coverage", ".nyc_output",
    "browser-profile", "vendor", "third_party", ".tox", ".mypy_cache",
}


@dataclass
class FileInfo:
    """Information about a single source file."""
    path: str
    language: str
    size_bytes: int
    line_count: int
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    has_global_state: bool = False
    global_state_lines: list[int] = field(default_factory=list)


@dataclass
class ProjectIndex:
    """Complete indexed representation of a project."""
    root: str
    context: ProjectContext
    files: list[FileInfo] = field(default_factory=list)
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)  # file -> [imported files]
    config_files: dict[str, str] = field(default_factory=dict)  # filename -> content
    total_lines: int = 0
    total_files: int = 0
    architecture_summary: str = ""

    def get_top_files(self, n: int = 20) -> list[FileInfo]:
        """Get the most important files by import count (most-imported first)."""
        import_counts: dict[str, int] = {}
        for deps in self.dependency_graph.values():
            for dep in deps:
                import_counts[dep] = import_counts.get(dep, 0) + 1

        scored = []
        for f in self.files:
            score = import_counts.get(f.path, 0) * 10 + f.line_count
            scored.append((score, f))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:n]]

    def to_context_string(self, max_chars: int = 100000) -> str:
        """Generate a context string for LLM analysis."""
        parts: list[str] = []

        # Project overview
        parts.append(f"PROJECT: {Path(self.root).name}")
        parts.append(f"Files: {self.total_files}, Lines: {self.total_lines}")
        parts.append(f"Languages: {', '.join(set(f.language for f in self.files))}")
        parts.append(f"Deployment: {self.context.deployment or 'unknown'}")
        parts.append(f"Frameworks: {', '.join(self.context.frameworks) or 'none detected'}")
        parts.append(f"Serverless: {self.context.is_serverless}")
        parts.append(f"Web app: {self.context.is_web_app}, API: {self.context.is_api}, CLI: {self.context.is_cli}")
        parts.append(f"ORM: {self.context.has_orm}, Template escaping: {self.context.has_template_escaping}")
        parts.append("")

        # Config files
        for name, content in self.config_files.items():
            chunk = f"--- CONFIG: {name} ---\n{content[:2000]}\n"
            parts.append(chunk)

        # File tree
        parts.append("--- FILE TREE ---")
        for f in self.files:
            markers = []
            if f.has_global_state:
                markers.append("GLOBAL_STATE")
            if f.classes:
                markers.append(f"classes:{','.join(f.classes[:3])}")
            if f.functions:
                markers.append(f"fns:{len(f.functions)}")
            marker_str = f" [{', '.join(markers)}]" if markers else ""
            parts.append(f"  {f.path} ({f.line_count}L){marker_str}")
        parts.append("")

        # Top files — full content
        total = sum(len(p) for p in parts)
        top_files = self.get_top_files(30)
        for f in top_files:
            file_path = Path(self.root) / f.path
            if not file_path.exists():
                continue
            try:
                content = file_path.read_text()
            except (UnicodeDecodeError, PermissionError):
                continue
            chunk = f"--- {f.path} ---\n{content}\n"
            if total + len(chunk) > max_chars:
                break
            parts.append(chunk)
            total += len(chunk)

        return "\n".join(parts)


def index_project(project_dir: str) -> ProjectIndex:
    """Index an entire project — structure, dependencies, globals, configs."""
    root = Path(project_dir).resolve()
    ctx = detect_context(str(root))

    index = ProjectIndex(root=str(root), context=ctx)

    # Collect config files
    config_names = [
        "package.json", "tsconfig.json", "vercel.json", "netlify.toml",
        "railway.json", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "serverless.yml", "serverless.yaml", ".env.example",
        "requirements.txt", "pyproject.toml", "Pipfile",
        "next.config.js", "next.config.mjs", "vite.config.ts", "webpack.config.js",
        ".debuggai.yaml", "Procfile",
    ]
    for name in config_names:
        path = root / name
        if path.exists():
            try:
                index.config_files[name] = path.read_text()[:5000]
            except (UnicodeDecodeError, PermissionError):
                pass

    # Index source files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue

        # Skip minified files
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        lines = content.split("\n")
        if len(lines) > 0 and len(content) / len(lines) > 500 and len(lines) < 50:
            continue  # Minified

        rel_path = str(path.relative_to(root))
        lang = _ext_to_lang(path.suffix.lower())

        file_info = FileInfo(
            path=rel_path,
            language=lang,
            size_bytes=len(content.encode()),
            line_count=len(lines),
        )

        # Extract structure
        file_info.imports = _extract_imports(content, lang)
        file_info.functions = _extract_functions(content, lang)
        file_info.classes = _extract_classes(content, lang)
        file_info.has_global_state, file_info.global_state_lines = _detect_global_state(content, lang)

        index.files.append(file_info)
        index.total_lines += file_info.line_count

        # Build dependency graph
        index.dependency_graph[rel_path] = _resolve_imports(file_info.imports, rel_path, str(root))

    index.total_files = len(index.files)
    return index


def generate_architecture_summary(index: ProjectIndex, api_key: Optional[str] = None) -> str:
    """Use LLM to generate a concise architecture summary."""
    if not api_key:
        return _generate_basic_summary(index)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    # Build a condensed view for the LLM
    file_tree = "\n".join(f"  {f.path} ({f.line_count}L, {f.language})" for f in index.files)
    configs = "\n".join(f"--- {name} ---\n{content[:1000]}" for name, content in index.config_files.items())
    ctx = index.context

    prompt = f"""Analyze this project and write a concise architecture summary (300-500 words).

PROJECT: {Path(index.root).name}
DEPLOYMENT: {ctx.deployment or 'unknown'}
FRAMEWORKS: {', '.join(ctx.frameworks) or 'none'}
SERVERLESS: {ctx.is_serverless}
WEB APP: {ctx.is_web_app} | API: {ctx.is_api} | CLI: {ctx.is_cli}
FILES: {index.total_files} | LINES: {index.total_lines}

FILE TREE:
{file_tree}

CONFIG FILES:
{configs}

GLOBAL STATE FILES: {', '.join(f.path for f in index.files if f.has_global_state) or 'none'}

Write:
1. What this app does (one sentence)
2. Architecture pattern (monolith, microservices, SPA+API, static, etc.)
3. Client/server boundaries
4. Data flow (how data moves through the system)
5. External dependencies/APIs
6. Key deployment constraints
7. Potential architectural concerns (1-3 bullet points)"""

    response = client.messages.create(
        model=os.environ.get("DEBUGGAI_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


def _generate_basic_summary(index: ProjectIndex) -> str:
    """Generate a basic summary without LLM."""
    ctx = index.context
    parts = [
        f"Project: {Path(index.root).name}",
        f"Type: {'web app' if ctx.is_web_app else 'CLI' if ctx.is_cli else 'library'}",
        f"Deployment: {ctx.deployment or 'unknown'}",
        f"Frameworks: {', '.join(ctx.frameworks) or 'none'}",
        f"Languages: {', '.join(set(f.language for f in index.files))}",
        f"Files: {index.total_files}, Lines: {index.total_lines}",
        f"Serverless: {ctx.is_serverless}",
    ]
    if any(f.has_global_state for f in index.files):
        state_files = [f.path for f in index.files if f.has_global_state]
        parts.append(f"Files with global state: {', '.join(state_files[:5])}")
    return "\n".join(parts)


# ── Extraction helpers ────────────────────────────────────────


def _ext_to_lang(ext: str) -> str:
    return {
        ".py": "python", ".js": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "typescript", ".mjs": "javascript",
        ".cjs": "javascript", ".go": "go", ".rs": "rust", ".java": "java",
    }.get(ext, "unknown")


def _extract_imports(content: str, lang: str) -> list[str]:
    imports = []
    if lang == "python":
        for m in re.finditer(r'^(?:from\s+(\S+)\s+import|import\s+(\S+))', content, re.MULTILINE):
            imports.append(m.group(1) or m.group(2))
    elif lang in ("javascript", "typescript"):
        for m in re.finditer(r'''(?:import|require)\s*(?:\(?\s*['"]([^'"]+)['"]|.*?from\s+['"]([^'"]+)['"])''', content):
            imports.append(m.group(1) or m.group(2))
    return imports


def _extract_functions(content: str, lang: str) -> list[str]:
    fns = []
    if lang == "python":
        for m in re.finditer(r'^(?:async\s+)?def\s+(\w+)', content, re.MULTILINE):
            fns.append(m.group(1))
    elif lang in ("javascript", "typescript"):
        for m in re.finditer(r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)\s*=>|function))', content):
            fns.append(m.group(1) or m.group(2))
    return fns


def _extract_classes(content: str, lang: str) -> list[str]:
    classes = []
    if lang == "python":
        for m in re.finditer(r'^class\s+(\w+)', content, re.MULTILINE):
            classes.append(m.group(1))
    elif lang in ("javascript", "typescript"):
        for m in re.finditer(r'class\s+(\w+)', content):
            classes.append(m.group(1))
    return classes


def _detect_global_state(content: str, lang: str) -> tuple[bool, list[int]]:
    """Detect module-level mutable state assignments."""
    state_lines = []
    lines = content.split("\n")

    if lang == "python":
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip imports, comments, constants (ALL_CAPS), class/function defs
            if not stripped or stripped.startswith(("#", "import ", "from ", "def ", "class ", "@")):
                continue
            if line[0] == " " or line[0] == "\t":
                continue  # Indented = not module level
            # Module-level assignment to mutable type
            if re.match(r'^[a-z_]\w*\s*=\s*(?:\{|\[|dict\(|set\(|collections\.)', stripped):
                state_lines.append(i)

    elif lang in ("javascript", "typescript"):
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "/*", "*", "import ", "export ")):
                continue
            # Module-level let/var with mutable values (not const)
            if re.match(r'^(?:let|var)\s+\w+\s*=\s*(?:new\s+Map|new\s+Set|\{|\[)', stripped):
                state_lines.append(i)

    return bool(state_lines), state_lines


def _resolve_imports(imports: list[str], source_file: str, project_root: str) -> list[str]:
    """Resolve imports to actual file paths within the project."""
    resolved = []
    root = Path(project_root)
    source_dir = (root / source_file).parent

    for imp in imports:
        # Skip external packages
        if not imp.startswith(".") and "/" not in imp:
            continue

        # Try relative resolution
        candidates = [
            source_dir / f"{imp}.py",
            source_dir / imp / "__init__.py",
            source_dir / f"{imp}.ts",
            source_dir / f"{imp}.js",
            source_dir / f"{imp}.tsx",
            source_dir / f"{imp}.jsx",
            source_dir / imp / "index.ts",
            source_dir / imp / "index.js",
        ]
        for c in candidates:
            if c.exists():
                try:
                    resolved.append(str(c.relative_to(root)))
                except ValueError:
                    pass
                break

    return resolved
