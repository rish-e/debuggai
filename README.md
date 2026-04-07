<p align="center">
  <h1 align="center">DebuggAI</h1>
  <p align="center">The universal verification layer for AI-generated software.</p>
</p>

<p align="center">
  <a href="https://github.com/rish-e/debuggai/blob/main/LICENSE"><img src="https://img.shields.io/github/license/rish-e/debuggai" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python">
  <img src="https://img.shields.io/badge/version-1.0.0-green" alt="Version">
</p>

---

AI-generated code has **1.7x more bugs** than human-written code. DebuggAI catches them — hallucinated APIs, security vulnerabilities, performance anti-patterns, and intent mismatches — before they reach production.

---

## How to Use

There are **two ways** to use DebuggAI. Pick whichever fits your workflow.

### Option A: Inside Claude Code / Cursor (recommended)

Use DebuggAI without leaving your AI coding workflow. Just talk naturally.

**One-time setup:**

```bash
pip install debuggai
debuggai setup
```

Then **restart Claude Code** (or Cursor).

**That's it.** Now just ask Claude:

- *"scan this project for bugs"*
- *"scan src/app.py for security issues"*
- *"verify this code matches: add user authentication with OAuth"*
- *"fix the issues you found"*
- *"show me scan history"*

Claude will use DebuggAI's tools automatically. No commands to memorize — just describe what you want.

### Option B: Terminal CLI

Run scans directly from your terminal.

```bash
cd ~/my-project

debuggai scan --no-llm                # Scan everything (no API key needed)
debuggai scan --file src/app.py       # Scan specific file
debuggai scan --diff HEAD~1           # Scan what changed since last commit
debuggai scan --staged                # Scan staged changes before committing
debuggai verify --intent "add OAuth"  # Verify code matches what you asked AI to build
debuggai fix                          # Generate fixes for detected issues
debuggai fix --apply                  # Auto-apply high-confidence fixes
debuggai history                      # Show quality trends over time
debuggai dismiss <rule-id>            # Dismiss a false positive
```

---

## What It Catches

### Hallucinated Imports
AI tools make up packages that don't exist. DebuggAI checks your actual dependency tree.

```
!!! [IMPORT] Hallucinated import: fastapi_magic_router  src/app.py:4
   Module 'fastapi_magic_router' is not installed and not in standard library
   Fix: Verify that 'fastapi_magic_router' exists. Install it or remove the import.
```

### Security Vulnerabilities
15+ security patterns tuned for AI code — XSS, SQL injection, hardcoded secrets, eval, command injection, insecure deserialization, and more. Framework-aware: won't flag safe patterns like parameterized queries or React JSX escaping.

```
!!! [SECURITY] SQL injection vulnerability  src/db.py:17
   SQL query built with string interpolation instead of parameterized queries.
   Fix: Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
```

### Performance Anti-Patterns
O(n²) loops, I/O inside loops, sync blocking calls, N+1 queries.

```
 !! [PERFORMANCE] I/O operation in loop: requests.get  src/sync.py:39
   'requests.get' called inside a loop at line 39. Each iteration performs I/O.
   Fix: Batch I/O operations outside the loop, or use async/concurrent patterns.
```

### LLM-Powered Deep Review
Sends code to Claude for semantic analysis — logic errors, incomplete error handling, architectural drift, dead code. Requires an Anthropic API key.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
debuggai scan --file src/app.py
```

### Intent Verification (Prompt Fidelity Score)
Compares what you asked the AI to build vs. what was actually built.

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

---

## v1.0 Features

### Auto-Fix Engine
DebuggAI generates fix diffs with confidence scores. Review and apply with one click.

```bash
debuggai fix                    # Generate fixes, show diffs
debuggai fix --apply            # Apply all high-confidence fixes
debuggai fix --min-confidence 0.9  # Only fixes above 90% confidence
```

```
Fix 1 confidence: 92%
  [CRITICAL] SQL injection vulnerability — src/db.py:17
  Use parameterized query instead of f-string
  - cursor.execute(f"SELECT * FROM users WHERE id = '{user_id}'")
  + cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

### Framework-Aware Context
DebuggAI auto-detects your tech stack and adjusts accordingly:
- **React/Vue/Svelte** detected → innerHTML in JSX auto-escaping recognized, XSS severity adjusted
- **Django/SQLAlchemy/Prisma** detected → ORM parameterization recognized, SQL injection severity adjusted
- **Vercel/Netlify** detected → serverless constraints applied
- **CLI tool** detected → browser-specific rules suppressed

No configuration needed — reads your `package.json`, `requirements.txt`, `vercel.json`, `Dockerfile` automatically.

### Dismissal Memory
Tired of a false positive? Dismiss it. After 3 dismissals of the same rule, it auto-suppresses permanently.

```bash
debuggai dismiss nested-loop-on2 --reason "acceptable for small data"
# "Rule 'nested-loop-on2' dismissed (1x). 2 more to auto-suppress."

debuggai dismiss nested-loop-on2
# "Rule 'nested-loop-on2' dismissed (2x). 1 more to auto-suppress."

debuggai dismiss nested-loop-on2
# "Rule 'nested-loop-on2' auto-suppressed (dismissed 3x)"
```

### Scan History & Quality Tracking
Every scan is saved to a local SQLite database. Track quality over time.

```bash
debuggai history
```

```
DebuggAI Scan History

  Since last scan: -4 issues, +2 new, -6 fixed

  Timestamp              Issues  Crit  Major Duration
  ────────────────────── ────── ───── ────── ────────
  2026-04-03T20:18:27         6     1      5     53ms
  2026-04-03T20:18:19        10     3      7    134ms
  2026-04-03T19:30:23        24     1     23    330ms
```

### Custom YAML Rules
Define your own rules in Semgrep-style YAML. DebuggAI ships with built-in rule packs for security, performance, and AI patterns.

```yaml
# .debuggai/rules/my-rules.yaml
rules:
  - id: no-console-log
    regex: 'console\.log\s*\('
    languages: [javascript, typescript]
    severity: minor
    category: ai_pattern
    message: "console.log left in code"
    suggestion: "Remove or replace with proper logging library."
```

Rules are auto-loaded from:
- `rules/` directory (built-in, ships with DebuggAI)
- `.debuggai/rules/` in your project (project-specific)

### Smart False Positive Reduction
DebuggAI automatically skips:
- Build artifacts (`.vercel/`, `dist/`, `build/`, `node_modules/`)
- Minified/bundled files (detected by line length heuristics)
- Safe innerHTML (template literals with no user input)
- Environment variable usage (`os.getenv`, `process.env`)
- Parameterized SQL queries (using `?` placeholders)
- Browser profile directories, vendor code, third-party bundles

---

## Why DebuggAI?

Traditional linters weren't designed for AI-generated code. They miss what AI specifically gets wrong:

| Problem | How Often in AI Code | DebuggAI Detection |
|---------|---------------------|-------------------|
| Hallucinated imports | Very common | AST + dependency resolution |
| XSS vulnerabilities | 2.74x more likely | Pattern + AST + framework context |
| Excessive I/O operations | 8x more frequent | AST loop analysis |
| Hardcoded secrets | 1.88x more likely | Regex + env var awareness |
| Missing error handling | 1.75x more frequent | LLM semantic review |
| Intent mismatches | Universal | Prompt Fidelity scoring |

---

## Persona Testing (v3.0)

Test your software from the **customer's perspective**, not just the developer's. DebuggAI discovers who your users are, then finds issues they'd encounter.

```bash
debuggai persona                              # Discover ICPs + analyze
debuggai persona --discover                   # Just discover personas
debuggai persona --persona "content creator"  # Test for specific persona
```

**What it discovers:**
```
Personas Discovered — my-app (consumer)

  1. Content Creator (primary) — non-technical
     Goals: Upload and process content quickly
     Pain points: Confusing error messages, no progress feedback

  2. Mobile User (secondary) — non-technical
     Goals: Complete tasks on the go
     Pain points: Tiny touch targets, slow loading on 4G

  3. First-Time Visitor (tertiary) — non-technical
     Goals: Understand what this product does in seconds
     Pain points: No clear value proposition, complex signup
```

**What it checks per persona:**

| Persona Type | Checks |
|-------------|--------|
| Non-technical user | Technical jargon in UI, raw error codes, missing loading feedback |
| Mobile user | Viewport meta tag, hover-only interactions, large assets |
| Developer | Missing API docs |
| Admin | Missing export, missing bulk operations |
| All personas | Unfriendly error messages, missing loading states, missing empty states |

### Live Browser Testing

The agent opens a **real browser**, navigates your site as the persona, and reports what the experience was like — step by step.

```bash
pip install debuggai[live]        # Install Playwright
playwright install chromium       # Download browser

debuggai persona --live http://localhost:3000
debuggai persona --live https://mysite.com --persona "first-time visitor"
```

```
DebuggAI Experience Report
Persona: First-Time Content Creator — non-technical
Goal: Upload and edit a video
Experience Score: 42/100

  Step 1: Landing page .......................... smooth
    "Clean page with clear title."

  Step 2: Looking for upload .................... confused
    "Upload button is below the fold. Almost gave up."
    FRICTION: Primary CTA not visible without scrolling.

  Step 3: Processing ............................ frustrated
    "Spinner with no ETA. Thought it was broken after 30s."
    FRICTION: No time estimate. No 'don't close' warning.

Top Improvements:
  1. Move upload button above the fold
  2. Add processing ETA
  3. Label export formats with use cases
```

Requires `ANTHROPIC_API_KEY` for Claude Vision evaluation. Cost: ~$0.03-0.09 per persona run.

---

## Deep Analysis (v2.0)

Go beyond file-by-file scanning. Deep analysis understands your entire project — deployment model, runtime behavior, architectural patterns — and finds system-level bugs that no linter can catch.

```bash
debuggai deep                       # Full analysis
debuggai deep --focus security      # Security architecture
debuggai deep --focus performance   # Runtime behavior + leaks
debuggai deep --focus deployment    # Deployment model fit
debuggai deep --no-llm              # Static analysis only (faster, free)
```

**What it finds that `debuggai scan` can't:**

| Category | Example |
|----------|---------|
| Serverless state | In-memory rate limiter resets on cold start |
| CORS abuse | `origin: *` lets any website drain your paid API |
| Memory leaks | Blob URLs never revoked, event listeners accumulating |
| Race conditions | Button clickable during async processing |
| Timeout mismatches | 600s timeout on Vercel (max 30s) |
| Missing safeguards | File upload with no size limit, API call with no timeout |

**How it works:**
1. Indexes your entire project — structure, dependencies, config files, deployment model
2. Runs static architectural analysis (serverless anti-patterns, runtime behavior, resource lifecycle)
3. Applies domain-specific rule packs (serverless, browser, React, API)
4. Optionally sends full project context to Claude for holistic LLM review

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `debuggai setup` | Auto-register MCP server in Claude Code / Cursor |
| `debuggai init` | Initialize config for a project (auto-detects languages) |
| `debuggai scan` | Scan code for bugs, security issues, performance problems |
| `debuggai verify` | Verify code matches a natural language intent |
| `debuggai fix` | Generate and optionally apply fixes |
| `debuggai history` | Show scan history and quality trends |
| `debuggai dismiss` | Dismiss a false positive rule |
| `debuggai config` | Show current configuration |
| `debuggai serve` | Start MCP server (used internally) |

### `debuggai scan` flags

| Flag | Description |
|------|-------------|
| `--file, -f` | File or directory to scan |
| `--diff, -d` | Git ref to diff against (e.g., `HEAD~1`) |
| `--staged, -s` | Scan staged changes only |
| `--intent, -i` | Intent to verify alongside scan |
| `--no-llm` | Skip LLM analysis (faster, no API key needed) |
| `--format, -o` | Output format: `terminal`, `markdown`, `json` |
| `--strict` | Report all severities including minor and info |

Exit codes: 0 = clean, 1 = major issues, 2 = critical issues.

### `debuggai fix` flags

| Flag | Description |
|------|-------------|
| `--file, -f` | File or directory to fix |
| `--apply` | Auto-apply all fixes |
| `--min-confidence` | Minimum confidence threshold (default: 0.7) |

### `debuggai verify` flags

| Flag | Description |
|------|-------------|
| `--intent, -i` | Intent to verify (required) |
| `--file, -f` | File or directory to verify against |
| `--diff, -d` | Git ref to verify against |

---

## MCP Server

DebuggAI includes a built-in Python MCP server — no npm or Node.js required.

```bash
debuggai setup              # Auto-register (recommended)
```

**Tools** (available to Claude / Cursor automatically):

| Tool | Description |
|------|-------------|
| `scan_code` | Scan code for bugs |
| `verify_intent` | Verify code matches intent |
| `fix_issues` | Generate and apply fixes |
| `show_history` | Show scan history and trends |
| `dismiss_rule` | Dismiss a false positive |
| `get_report` | Get full JSON report |
| `init_project` | Initialize config |

**Slash commands** (type these in Claude Code):

| Command | Description |
|---------|-------------|
| `/scan` | Scan current project |
| `/verify` | Verify code matches intent |
| `/fix` | Generate and apply fixes |
| `/history` | Show quality trends |
| `/init` | Initialize config |

---

## Configuration

Create a `.debuggai.yaml` in your project root (or run `debuggai init`):

```yaml
project:
  name: "my-project"
  type: "fullstack"

code:
  languages: [python, typescript]
  strictness: medium   # low (critical only) | medium (default) | high (everything)
  ignore:
    - "*.test.*"
    - "node_modules/"
  rules:
    security: true
    performance: true
    ai_patterns: true

reporting:
  format: markdown
  severity_threshold: minor
  output: stdout
```

---

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
debuggai scan --staged --no-llm
```

---

## Architecture

```
debuggai/
├── engines/
│   ├── code/           # Code QA Engine
│   │   ├── imports.py      # Hallucinated import detector
│   │   ├── security.py     # Security vulnerability scanner
│   │   ├── performance.py  # Performance anti-pattern detector
│   │   ├── llm_review.py   # LLM-powered semantic review
│   │   ├── rules.py        # Custom YAML rule engine
│   │   └── scanner.py      # Orchestrates all code analyzers
│   ├── intent/         # Intent Verification Engine
│   │   ├── capture.py      # Intent capture from CLI/git/files
│   │   ├── parser.py       # Assertion extraction via LLM
│   │   └── scorer.py       # Prompt Fidelity scoring
│   └── fix.py          # Auto-fix generation and application
├── models/             # Pydantic data models
├── reports/            # Report generation (JSON, Markdown, terminal)
├── context.py          # Framework and deployment detection
├── storage.py          # SQLite history, dismissals, quality tracking
├── mcp_server.py       # Python MCP server (no npm needed)
├── cli.py              # Click CLI entry point
└── orchestrator.py     # Engine coordination + context + storage
```

## Supported Languages

| Language | Import Detection | Security | Performance | Custom Rules |
|----------|:---:|:---:|:---:|:---:|
| Python | Yes | Yes | Yes | Yes |
| JavaScript | Yes | Yes | Yes | Yes |
| TypeScript | Yes | Yes | Yes | Yes |
| Go | Planned | Planned | Planned | Yes |
| Rust | Planned | Planned | Planned | Yes |
| Java | Planned | Planned | Planned | Yes |

## Roadmap

- **v0.1** — Code QA + Intent Verification + CLI + MCP Server
- **v1.0** — Auto-fix, framework detection, dismissal memory, scan history, custom YAML rules
- **v3.1** (current) — Live Browser Agent: Playwright opens your site, navigates as a persona, reports the experience
- **v3.0** — Persona-Based Testing: ICP discovery, customer-perspective analysis, per-persona UX checks
- **v2.1** — Hardened: parallel scanning, incremental caching, 33 tests, API error handling, false positive fixes
- **v2.0** — Deep Analysis Engine, architectural anti-patterns, runtime behavior analysis, domain rule packs
- **v2.5** — Cloud dashboard, team features, GitHub PR integration (GitHub App), quality gates
- **v3.0** — Autonomous testing agent (Playwright + LLM), self-healing tests

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

Apache 2.0 — see [LICENSE](LICENSE).
