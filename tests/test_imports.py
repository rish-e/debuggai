"""Tests for hallucinated import detector."""

from debuggai.engines.code.imports import scan_imports


def test_detects_fake_python_import():
    code = "import nonexistent_magic_package"
    issues = scan_imports("test.py", code)
    assert any("nonexistent_magic_package" in i.title for i in issues)


def test_allows_stdlib_import():
    code = "import os\nimport json\nimport sys"
    issues = scan_imports("test.py", code)
    assert len(issues) == 0


def test_detects_fake_npm_package():
    code = 'import { magic } from "totally-fake-package-xyz";'
    issues = scan_imports("test.js", code)
    assert any("totally-fake-package-xyz" in i.title for i in issues)


def test_allows_relative_import():
    code = 'import { foo } from "./utils";'
    issues = scan_imports("test.js", code)
    assert len(issues) == 0


def test_allows_node_builtin():
    code = 'import fs from "fs";\nimport path from "path";'
    issues = scan_imports("test.js", code)
    assert len(issues) == 0
