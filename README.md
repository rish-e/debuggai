<p align="center">
  <h1 align="center">DebuggAI</h1>
  <p align="center">The universal verification layer for AI-generated software.</p>
</p>

<p align="center">
  <a href="https://github.com/rish-e/debuggai/actions"><img src="https://img.shields.io/github/actions/workflow/status/rish-e/debuggai/ci.yml?branch=main" alt="CI"></a>
  <a href="https://pypi.org/project/debuggai/"><img src="https://img.shields.io/pypi/v/debuggai" alt="PyPI"></a>
  <a href="https://github.com/rish-e/debuggai/blob/main/LICENSE"><img src="https://img.shields.io/github/license/rish-e/debuggai" alt="License"></a>
  <a href="https://pypi.org/project/debuggai/"><img src="https://img.shields.io/pypi/pyversions/debuggai" alt="Python"></a>
</p>

---

AI-generated code has **1.7x more bugs** than human-written code. 88% of developers don't trust it enough to deploy. DebuggAI is a specialized diagnostic engine that catches the bugs AI coding tools introduce — hallucinated APIs, security vulnerabilities, performance anti-patterns, and intent mismatches — before they reach production.

## Why DebuggAI?

Traditional linters and test tools weren't designed for AI-generated code. They miss the failure modes that AI coding tools specifically produce:

| Problem | How Often in AI Code | DebuggAI Detection |
|---------|---------------------|-------------------|
| Hallucinated imports (non-existent packages) | Very common | AST + dependency resolution |
| XSS vulnerabilities | 2.74x more likely | Pattern + AST analysis |
| Excessive I/O operations | 8x more frequent | AST loop analysis |
| Hardcoded secrets | 1.88x more likely | Regex + entropy detection |
| Missing error handling | 1.75x more frequent | LLM semantic review |
| Intent mismatches | Universal | Prompt Fidelity scoring |

## Install

```bash
pip install debuggai
```

Requires Python 3.10+.

## Quick Start

```bash
# Initialize DebuggAI in your project (auto-detects languages)
debuggai init

# Scan for issues
debuggai scan

# Scan a specific file
debuggai scan --file src/app.py

# Scan git changes since last commit
debuggai scan --diff HEAD~1

# Scan only staged changes (great for pre-commit)
debuggai scan --staged

# Verify code matches what you asked the AI to build
debuggai verify --intent "add user authentication with Google OAuth"
```

## What It Catches

### 1. Hallucinated Imports

AI tools frequently generate imports for packages that don't exist. DebuggAI resolves the full dependency tree (pip, npm, cargo) and flags imports that can't be found.

```
!!! [IMPORT] Hallucinated import: fastapi_magic_router  src/app.py:4
   Module 'fastapi_magic_router' is not installed and not in standard library
   Fix: Verify that 'fastapi_magic_router' exists. Install it or remove the import.
```

### 2. Security Vulnerabilities

15 security patterns tuned for AI-generated code — XSS, SQL injection, hardcoded secrets, eval usage, command injection, insecure deserialization, and more.

```
!!! [SECURITY] SQL injection vulnerability  src/db.py:17
   SQL query built with string interpolation instead of parameterized queries.
   Fix: Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
```

### 3. Performance Anti-Patterns

Detects O(n²) nested loops, I/O operations inside loops, synchronous blocking calls, and N+1 query patterns.

```
 !! [PERFORMANCE] I/O operation in loop: requests.get  src/sync.py:39
   'requests.get' called inside a loop at line 39. Each iteration performs I/O.
   Fix: Batch I/O operations outside the loop, or use async/concurrent patterns.
```

### 4. LLM-Powered Semantic Review

Sends code to Claude for deep analysis of logic errors, incomplete error handling, architectural drift, and dead code from AI iteration. Requires an Anthropic API key.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
debuggai scan --file src/app.py
```

### 5. Intent Verification (Prompt Fidelity Score)

Compares what you asked the AI to build against what was actually built. Extracts testable assertions from your intent and scores each one.

```bash
debuggai verify --intent "add user auth with Google OAuth" --file src/
```

```
Prompt Fidelity Score: 65/100

[+] OAuth dependency present (google-auth-library found)
[x] No /auth/google route found
[~] Token storage partially implemented (found in localStorage — insecure)
[+] Redirect to login page implemented
```

## CLI Reference

### `debuggai init [directory]`

Initialize DebuggAI for a project. Auto-detects languages and creates `.debuggai.yaml`.

### `debuggai scan`

Scan code for AI-generated bugs.

| Flag | Description |
|------|-------------|
| `--file, -f` | File or directory to scan |
| `--diff, -d` | Git ref to diff against (e.g., `HEAD~1`) |
| `--staged, -s` | Scan staged changes only |
| `--intent, -i` | Intent to verify alongside scan |
| `--spec` | Path to intent spec file |
| `--no-llm` | Skip LLM analysis (faster, no API key needed) |
| `--format, -o` | Output format: `terminal`, `markdown`, `json` |
| `--strict` | Report all severities including minor and info |
| `--config` | Path to config file |

**Exit codes**: 0 = clean, 1 = major issues found, 2 = critical issues found.

### `debuggai verify`

Verify code against a natural language intent.

| Flag | Description |
|------|-------------|
| `--intent, -i` | Intent to verify (required) |
| `--file, -f` | File or directory to verify against |
| `--diff, -d` | Git ref to verify against |
| `--format, -o` | Output format: `terminal`, `markdown`, `json` |

### `debuggai config`

Show current DebuggAI configuration.

## Configuration

Create a `.debuggai.yaml` in your project root (or run `debuggai init`):

```yaml
project:
  name: "my-project"
  type: "fullstack"    # fullstack | backend | frontend | creative

code:
  languages: [python, typescript]
  strictness: medium   # low | medium | high
  ignore:
    - "*.test.*"
    - "node_modules/"
    - "__pycache__/"
  rules:
    security: true
    performance: true
    ai_patterns: true

intent:
  sources:
    - git_commits
    - pr_descriptions
    - spec_files

reporting:
  format: markdown     # terminal | markdown | json
  severity_threshold: minor
  output: stdout       # stdout | file | both
```

### Strictness Levels

| Level | What gets reported |
|-------|-------------------|
| `low` | Critical only |
| `medium` | Critical + Major (default) |
| `high` | Everything including Minor and Info |

## MCP Server

DebuggAI includes an MCP server for integration with Claude Code, Cursor, and Windsurf.

```bash
cd mcp-server && npm install && npm run build
```

Add to your MCP config:

```json
{
  "mcpServers": {
    "debuggai": {
      "command": "node",
      "args": ["/path/to/debuggai/mcp-server/dist/index.js"]
    }
  }
}
```

**Available tools:**

| Tool | Description |
|------|-------------|
| `scan_code` | Scan code for AI-generated bugs |
| `verify_intent` | Verify code matches intent, get Prompt Fidelity Score |
| `get_report` | Get full JSON report for programmatic analysis |
| `configure` | Show or initialize DebuggAI config |

## CI/CD Integration

### GitHub Actions

```yaml
- name: DebuggAI Scan
  run: |
    pip install debuggai
    debuggai scan --format json --no-llm
  continue-on-error: false
```

### Pre-commit Hook

```bash
# In your pre-commit script or .husky/pre-commit
debuggai scan --staged --no-llm
```

## Architecture

```
debuggai/
├── engines/
│   ├── code/          # Code QA Engine
│   │   ├── imports.py     # Hallucinated import detector
│   │   ├── security.py    # Security vulnerability scanner
│   │   ├── performance.py # Performance anti-pattern detector
│   │   ├── llm_review.py  # LLM-powered semantic review
│   │   └── scanner.py     # Orchestrates all code analyzers
│   ├── intent/        # Intent Verification Engine
│   │   ├── capture.py     # Intent capture from CLI/git/files
│   │   ├── parser.py      # Assertion extraction via LLM
│   │   └── scorer.py      # Prompt Fidelity scoring
│   └── creative/      # Creative Output QA (coming in v1.0)
├── models/            # Pydantic data models
├── reports/           # Report generation (JSON, Markdown, terminal)
├── utils/             # Git, LLM, and FFmpeg utilities
└── cli.py             # Click CLI entry point
```

## Supported Languages

| Language | Import Detection | Security Scan | Performance Scan |
|----------|:---:|:---:|:---:|
| Python | Yes | Yes | Yes |
| JavaScript | Yes | Yes | Yes |
| TypeScript | Yes | Yes | Yes |
| Go | Planned | Planned | Planned |
| Rust | Planned | Planned | Planned |
| Java | Planned | Planned | Planned |

## Roadmap

- **v0.1** (current) — Code QA + Intent Verification + CLI + MCP Server
- **v1.0** — Creative Output QA (video/audio), auto-fix suggestions, GitHub PR comments
- **v1.5** — Cloud dashboard, team features, quality gates
- **v2.0** — Autonomous testing agent, self-healing tests, enterprise features

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

Apache 2.0 — see [LICENSE](LICENSE).
