# DebuggAI

The universal verification layer for AI-generated software.

DebuggAI catches bugs that AI coding tools introduce — hallucinated APIs, security vulnerabilities, performance anti-patterns, and intent mismatches — before they reach production.

## Install

```bash
pip install debuggai
```

## Quick Start

```bash
# Initialize in your project
debuggai init

# Scan for issues
debuggai scan

# Scan specific file
debuggai scan --file src/app.py

# Scan git changes
debuggai scan --diff HEAD~1

# Verify code matches intent
debuggai verify --intent "add user authentication with OAuth"
```

## License

Apache 2.0
