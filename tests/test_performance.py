"""Tests for performance anti-pattern detector."""

from debuggai.engines.code.performance import scan_performance


def test_detects_nested_loops():
    code = """
for user in users:
    for perm in permissions:
        if user.id == perm.user_id:
            pass
"""
    issues = scan_performance("test.py", code)
    assert any(i.rule_id == "nested-loop-on2" for i in issues)


def test_skips_small_range_loops():
    code = """
for i in range(5):
    for j in range(5):
        pass
"""
    issues = scan_performance("test.py", code)
    assert not any(i.rule_id == "nested-loop-on2" for i in issues)


def test_detects_io_in_loop():
    code = """
for uid in user_ids:
    response = requests.get(f"https://api.example.com/users/{uid}")
"""
    issues = scan_performance("test.py", code)
    assert any(i.rule_id == "io-in-loop" for i in issues)


def test_detects_fetch_in_loop_js():
    code = """
for (const id of ids) {
    const res = await fetch(`/api/users/${id}`);
}
"""
    issues = scan_performance("test.js", code)
    assert any(i.rule_id == "fetch-in-loop" for i in issues)


def test_detects_sync_io_js():
    code = 'const data = fs.readFileSync("config.json", "utf-8");'
    issues = scan_performance("test.js", code)
    assert any(i.rule_id == "sync-io" for i in issues)
