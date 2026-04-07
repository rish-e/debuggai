# Contributing to DebuggAI

Thanks for your interest in contributing to DebuggAI. This document covers the essentials.

## Development Setup

```bash
git clone https://github.com/rish-e/debuggai.git
cd debuggai
pip install -e ".[dev]"
```

The MCP server is Python-native (no npm required). For live persona testing:

```bash
pip install -e ".[live]"
playwright install chromium
```

## Running Tests

```bash
pytest
```

## Project Structure

```
debuggai/
├── debuggai/           # Python core package
│   ├── engines/        # Analysis engines (code, intent, creative)
│   ├── models/         # Pydantic data models
│   ├── reports/        # Report generation
│   ├── utils/          # Git, LLM, FFmpeg utilities
│   ├── cli.py          # CLI entry point
│   ├── config.py       # Configuration system
│   └── orchestrator.py # Engine coordination
├── mcp-server/         # TypeScript MCP server
├── rules/              # YAML rule definitions
└── tests/              # Tests and fixtures
```

## Adding a New Detection Rule

### Security/Performance Pattern (regex or AST-based)

Add patterns to the appropriate file in `debuggai/engines/code/`:

- `security.py` for security vulnerabilities
- `performance.py` for performance anti-patterns
- `imports.py` for import-related checks

Each pattern follows this structure:

```python
(
    re.compile(r"""your_pattern_here"""),
    Severity.CRITICAL,       # CRITICAL | MAJOR | MINOR | INFO
    "Short title",
    "Detailed description of the issue.",
    "Suggested fix.",
    "rule-id",               # Unique identifier
)
```

### Adding Language Support

1. Add tree-sitter grammar to `pyproject.toml` dependencies
2. Add file extension mapping in `engines/code/scanner.py` (`SUPPORTED_EXTENSIONS`)
3. Add import resolution logic in `engines/code/imports.py`
4. Add language-specific patterns to security/performance scanners

## Code Style

- Python: formatted with `ruff`, line length 100
- TypeScript: standard TS conventions
- Commits: imperative mood, concise ("Add Go import detection", not "Added Go import detection")

## Pull Requests

1. Fork the repo and create a branch from `main`
2. Add tests for new features
3. Ensure `pytest` and `ruff check` pass
4. Submit a PR with a clear description of the change

## Reporting Issues

Open an issue with:
- DebuggAI version (`debuggai --version`)
- Python version
- What you ran and what happened
- Expected behavior

## Adding Custom Rules (YAML)

Rule packs live in `rules/`. Format:

```yaml
rules:
  - id: "my-rule"
    severity: major
    category: security
    pattern: "dangerous_function\\("
    languages: [python, javascript]
    title: "Dangerous function usage"
    description: "This function is unsafe because..."
    suggestion: "Use safe_function() instead."
```

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
