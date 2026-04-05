"""Tests for security scanner."""

from debuggai.engines.code.security import scan_security


def test_detects_hardcoded_secret():
    code = 'api_key = "sk-proj-abc123def456ghi789jkl012"'
    issues = scan_security("test.py", code)
    assert any(i.rule_id == "hardcoded-secret" for i in issues)


def test_skips_env_var_secret():
    code = 'api_key = os.getenv("API_KEY", "")'
    issues = scan_security("test.py", code)
    assert not any(i.rule_id == "hardcoded-secret" for i in issues)


def test_detects_sql_injection_python():
    code = '''cursor.execute(f"SELECT * FROM users WHERE id = '{user_id}'")'''
    issues = scan_security("test.py", code)
    assert any(i.rule_id == "sql-injection" for i in issues)


def test_skips_parameterized_sql():
    code = '''cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))'''
    issues = scan_security("test.py", code)
    assert not any(i.rule_id == "sql-injection" for i in issues)


def test_detects_eval():
    code = "result = eval(user_input)"
    issues = scan_security("test.py", code)
    assert any(i.rule_id == "dangerous-eval" for i in issues)


def test_detects_xss_innerhtml_variable():
    code = "element.innerHTML = userInput"
    issues = scan_security("test.js", code)
    assert any(i.rule_id == "xss-innerhtml" for i in issues)


def test_skips_innerhtml_template_literal():
    code = "element.innerHTML = `<div class='stat'>hello</div>`"
    issues = scan_security("test.js", code)
    assert not any(i.rule_id == "xss-innerhtml" for i in issues)


def test_skips_innerhtml_empty_string():
    code = "container.innerHTML = '';"
    issues = scan_security("test.js", code)
    assert not any(i.rule_id == "xss-innerhtml" for i in issues)


def test_skips_comments():
    code = "# api_key = 'sk-proj-abc123def456ghi789jkl012'"
    issues = scan_security("test.py", code)
    assert len(issues) == 0


def test_skips_block_comments():
    code = "/* api_key = 'sk-proj-abc123def456ghi789jkl012' */"
    issues = scan_security("test.js", code)
    assert len(issues) == 0


def test_detects_pickle():
    code = "data = pickle.loads(untrusted_bytes)"
    issues = scan_security("test.py", code)
    assert any(i.rule_id == "insecure-deserialization" for i in issues)


def test_detects_cors_wildcard():
    code = 'cors: { origin: "*" }'
    issues = scan_security("test.js", code)
    assert any(i.rule_id == "cors-wildcard" for i in issues)
