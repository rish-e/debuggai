# Changelog

All notable changes to DebuggAI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- **MCP server** (TypeScript) with `scan_code`, `verify_intent`, `get_report`, `configure` tools
- Support for Python, JavaScript, and TypeScript codebases
