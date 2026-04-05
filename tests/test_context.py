"""Tests for framework and deployment context detection."""

import json
import tempfile
from pathlib import Path

from debuggai.context import detect_context, should_adjust_severity


def test_detects_vercel():
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "vercel.json").write_text("{}")
        ctx = detect_context(tmpdir)
        assert ctx.deployment == "vercel"
        assert ctx.is_serverless is True


def test_detects_docker():
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "Dockerfile").write_text("FROM node:20")
        ctx = detect_context(tmpdir)
        assert ctx.deployment == "docker"
        assert ctx.is_serverless is False


def test_detects_react():
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = {"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}
        (Path(tmpdir) / "package.json").write_text(json.dumps(pkg))
        ctx = detect_context(tmpdir)
        assert "react" in ctx.frameworks
        assert ctx.has_template_escaping is True
        assert ctx.is_web_app is True


def test_detects_django():
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "requirements.txt").write_text("django==4.2\ndjango-rest-framework")
        ctx = detect_context(tmpdir)
        assert "django" in ctx.frameworks
        assert ctx.has_orm is True
        assert ctx.has_csrf_protection is True


def test_xss_suppressed_for_cli():
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = {"bin": {"mycli": "./index.js"}}
        (Path(tmpdir) / "package.json").write_text(json.dumps(pkg))
        ctx = detect_context(tmpdir)
        assert ctx.is_cli is True

        result = should_adjust_severity(ctx, "xss-innerhtml", "security")
        assert result == "suppress"


def test_sql_downgraded_with_orm():
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = {"dependencies": {"prisma": "^5.0.0", "@prisma/client": "^5.0.0"}}
        (Path(tmpdir) / "package.json").write_text(json.dumps(pkg))
        ctx = detect_context(tmpdir)
        assert ctx.has_orm is True

        result = should_adjust_severity(ctx, "sql-injection", "security")
        assert result == "minor"
