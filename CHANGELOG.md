# Changelog

All notable changes to DebuggAI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.0] - 2026-04-07

### Fixed

- **Persona agent session crash**: Navigation failure no longer leaves dangling session; browser cleaned up properly on error
- **Event loop leak**: `end_session()` now closes the asyncio event loop; prevents resource leaks across multiple sessions
- **LLM client key mismatch**: Global client now tracks cached API key and recreates if key changes between calls
- **KeyError in severity sorting**: Replaced 4 hardcoded dict lookups with `.get()` via shared `SEVERITY_RANK` constant
- **Exit code logic in verify**: Fidelity score thresholds corrected (<40 = exit 2, <70 = exit 1, >=70 = exit 0)
- **Intent verification crash**: `score_intent()` failure no longer crashes entire scan (wrapped in try/except)

### Improved

- **Package list caching**: `pip list` and `node_modules` traversal now cached per session — was running per-file (100 files = 100 subprocess calls → now 1)
- **Shared constants**: Severity ranking, language maps, skip directories extracted to `utils/constants.py` — eliminates 12 duplicate definitions
- **CONTRIBUTING.md**: Updated to reference Python MCP server (removed deleted TypeScript instructions)

## [3.1.0] - 2026-04-07

### Added

- **Live Persona Browser Agent** — opens a real browser, navigates your website AS a specific persona
  - `debuggai persona --live http://localhost:3000` — full experience test
  - `live_persona_test` MCP tool for Claude Code integration
  - Uses Playwright + Claude Vision: screenshot → evaluate from persona's perspective → decide next action → repeat
  - Reports step-by-step journey with friction points, feelings (smooth/confused/frustrated/lost), and experience score (0-100)
  - Smart element finding: tries text match, ARIA roles, placeholders, labels
  - Configurable max steps (default 15)
  - Works on localhost and deployed sites
  - Cost: ~$0.03-0.09 per persona run
- **Experience Report** — new report format showing the persona's journey through your app
  - Terminal and Markdown output formats
  - Per-step: observation, feeling, friction, action taken
  - Summary: experience score, friction count, top improvements
- `playwright` added as optional dependency (`pip install debuggai[live]`)

## [3.0.0] - 2026-04-07

### Added

- **Persona-Based Testing** — test software from the customer's perspective, not just the developer's
  - `debuggai persona` command discovers ICPs and finds persona-specific issues
  - `discover_personas` MCP tool identifies who uses the software from codebase signals
  - `persona_test` MCP tool finds UX issues specific to each persona
  - `/persona` slash command for Claude Code
  - **ICP Discovery Engine**: Reads README, UI patterns, features, config to infer target personas
    - Detects app type (consumer, b2b, developer-tool)
    - Infers 2-4 personas with goals, pain points, devices, and key flows
    - Signal-based heuristics (free) + optional LLM-powered discovery (deeper)
  - **Persona Static Analyzer**: Checks code for persona-specific issues
    - Non-technical users: technical jargon in UI, raw error codes shown to users
    - Mobile users: missing viewport meta, hover-only interactions, large assets
    - Developer users: missing API documentation
    - Admin users: missing export functionality
    - All personas: unfriendly error messages, missing loading states, missing empty states
  - Works on any project — auto-adapts to the codebase (tested on video editors, admin dashboards, CLI tools)
- **False positive fix**: `@/` path aliases (Next.js/TypeScript) no longer flagged as hallucinated imports
- **False positive fix**: SQLite `.execute().fetchone()` no longer flagged as HTTP call
- **False positive fix**: SQL arithmetic inside strings (`value + 1`) no longer flagged as injection

## [2.1.0] - 2026-04-05

### Fixed

- **API error handling**: All LLM calls now catch `anthropic.APIError`, `APIConnectionError`, `RateLimitError`, and `AuthenticationError` — scans degrade gracefully instead of crashing
- **Model parameterization**: Model name configurable via `DEBUGGAI_MODEL` env var (no more hardcoded model that breaks on deprecation)
- **Race condition in dismissals**: Fixed NULL handling in SQLite UNIQUE constraint, dismissal count tracking now atomic
- **Silent failures replaced with logging**: Storage, dismissal filtering, and history save now log warnings via Python logging instead of silently swallowing errors
- **Block comment handling**: Security scanner now correctly skips single-line `/* ... */` block comments
- **Event listener leak detection**: Tracks (event_type, handler_name) pairs instead of just event types — reduces false positives from shared event names with different handlers
- **`range(len(x))` detection**: Performance analyzer now correctly identifies `range(len(data))` as data-dependent iteration (O(n²) risk)
- **Docstring/triple-quote skipping**: Security scanner skips lines containing `"""` or `'''` to avoid self-detecting patterns in docstrings

### Added

- **Parallel file scanning**: `ThreadPoolExecutor` scans up to 8 files concurrently
- **Incremental caching**: File hashes cached in `.debuggai/cache.json` — unchanged files are skipped on re-scan
- **MCP path validation**: Target paths validated to prevent scanning arbitrary directories
- **Regex safety**: Custom YAML rules reject patterns over 500 chars or with known catastrophic backtracking patterns
- **33 unit tests**: Security scanner, import detector, performance analyzer, storage layer, and context detection all tested

### Changed

- Quality delta uses scan ID ordering (not timestamp) to handle same-second scans correctly

## [2.0.0] - 2026-04-03

### Added

- **Deep Analysis Engine** — holistic architectural analysis that understands entire projects
  - `debuggai deep` command with `--focus` (all, security, performance, deployment)
  - `deep_analysis` MCP tool + `/deep` slash command
  - **Layer 1: Project Indexer** — builds dependency graph, extracts structure, generates architecture summary via LLM
  - **Layer 2: Architectural Anti-Pattern Detection**:
    - Stateful code in serverless environments (in-memory maps/sets that reset on cold start)
    - CORS wildcard enabling API abuse
    - Missing cache headers on large assets (WASM, fonts)
    - Timeout values exceeding platform limits (Vercel 30s, Lambda 900s)
    - Recursive serverless invocations (DoW attack risk)
  - **Layer 3: Runtime Behavior Analysis**:
    - Memory leaks: addEventListener without removeEventListener, blob URLs without revokeObjectURL, useEffect without cleanup
    - Race conditions: async handlers without re-entry guards
    - Missing safeguards: API calls without timeout, file uploads without size validation
  - **Layer 4: Domain-Specific Rule Packs** (14 new rules across 4 packs):
    - `serverless.yaml` — global state, connection reuse, /tmp cleanup
    - `browser.yaml` — AbortController, DOM ready, localStorage error handling
    - `react.yaml` — setState in render, array index keys, missing dep arrays
    - `api.yaml` — rate limiting, input validation, error leaking, auth checks
  - **Holistic LLM Review** — sends full project context to Claude for system-level analysis (optional, requires API key)

### Changed

- Report model now includes `architecture_summary` and `project_context` fields
- Serverless state detection scoped to server-side files only (api/, functions/, etc.)
- Version bumped to 2.0.0

## [1.0.0] - 2026-04-03

### Added

- **Auto-Fix Engine**: Generate fix diffs via Claude with confidence scores
  - `debuggai fix` generates fixes, `debuggai fix --apply` applies them
  - `fix_issues` MCP tool + `/fix` slash command
  - Configurable minimum confidence threshold
- **Framework-Aware Context Detection**: Auto-detects tech stack and deployment model
  - Reads package.json, requirements.txt, vercel.json, Dockerfile
  - Detects React, Django, Next.js, Express, Vue, Svelte, FastAPI, Flask
  - Adjusts severity based on context (XSS suppressed for CLI tools, SQL injection downgraded with ORM)
  - Detects deployment model (Vercel, Netlify, Lambda, Docker, Heroku)
- **Dismissal Memory System**: Learn from user feedback
  - `debuggai dismiss <rule-id>` records dismissals
  - Auto-suppresses rules after 3 dismissals of the same pattern
  - SQLite-backed, persists across sessions
  - `dismiss_rule` MCP tool
- **Scan History & Quality Tracking**: Track quality over time
  - Every scan saved to local SQLite database
  - `debuggai history` shows trends with deltas (+3 new, -5 fixed)
  - `show_history` MCP tool + `/history` slash command
  - Issue lifecycle tracking: new, fixed, recurring, dismissed
- **Custom YAML Rule Engine**: Semgrep-style rules
  - Define rules in YAML with regex/pattern matching
  - Auto-loaded from `rules/` (built-in) and `.debuggai/rules/` (project)
  - 8 built-in rules: JWT secrets, bcrypt rounds, debug mode, TODO/FIXME, console.log, commented-out code, unbounded queries
- **Python-native MCP Server**: No npm/Node.js required
  - `debuggai setup` auto-registers in Claude Code / Cursor settings
  - `debuggai-mcp` entry point for direct MCP usage
  - 7 tools: scan_code, verify_intent, fix_issues, show_history, dismiss_rule, get_report, init_project
  - 5 slash commands: /scan, /verify, /fix, /history, /init

### Improved

- **False Positive Reduction**: Major accuracy improvements
  - Auto-skips build artifacts (.vercel/, dist/, build/, node_modules/)
  - Skips minified/bundled files (detected by line length heuristics)
  - Smarter innerHTML detection (only flags variable assignment, not template literals)
  - Smarter secret detection (skips os.getenv, process.env patterns)
  - Smarter SQL injection detection (skips parameterized queries with ? placeholders, column name toggles)
  - Removed print() from I/O-in-loop detection (it's logging, not I/O)
  - Context-aware severity adjustment based on detected framework
- **MCP Server rewritten in Python**: Single `pip install` gets everything, no npm dependency

### Changed

- MCP server moved from TypeScript (`mcp-server/`) to Python (`debuggai/mcp_server.py`)
- `debuggai setup` command replaces manual JSON config editing

## [0.1.0] - 2026-04-03

### Added

- **CLI tool** with `init`, `scan`, `verify`, and `config` commands
- **Code QA Engine** with 4 analyzers:
  - Hallucinated import detector (Python + JavaScript/TypeScript)
  - Security vulnerability scanner (15 patterns: XSS, SQLi, hardcoded secrets, eval, command injection, insecure deserialization, and more)
  - Performance anti-pattern detector (O(n^2) loops, I/O in loops, sync blocking, N+1 queries)
  - LLM-powered semantic review via Claude API
- **Intent Verification Engine**:
  - Captures intent from CLI flags, spec files, and git commit messages
  - Extracts structured assertions from natural language via LLM
  - Scores each assertion against actual code
  - Computes Prompt Fidelity Score (0-100)
- **Report generator** with 3 output formats: terminal (Rich), Markdown, JSON
- **Configuration system** with `.debuggai.yaml` and auto-detection of project languages
- Support for Python, JavaScript, and TypeScript codebases
