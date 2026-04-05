"""Tests for storage layer — history and dismissals."""

import tempfile
from pathlib import Path

from debuggai.storage import (
    get_db,
    save_scan,
    save_issues,
    get_scan_history,
    get_quality_delta,
    dismiss_issue,
    is_suppressed,
    clear_dismissal,
)


def test_save_and_retrieve_scan():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = get_db(tmpdir)
        scan_id = save_scan(db, "test-project", ".", 5, 1, 2, 1, 1)
        assert scan_id > 0

        history = get_scan_history(db)
        assert len(history) == 1
        assert history[0]["total_issues"] == 5
        assert history[0]["critical"] == 1
        db.close()


def test_quality_delta():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = get_db(tmpdir)
        save_scan(db, "proj", ".", 10, 3, 5, 2, 0)
        save_scan(db, "proj", ".", 7, 1, 4, 2, 0)

        delta = get_quality_delta(db, "proj")
        assert delta is not None
        assert delta["delta_total"] == -3
        assert delta["delta_critical"] == -2
        db.close()


def test_dismissal_auto_suppress():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = get_db(tmpdir)

        # First two dismissals — not suppressed
        dismiss_issue(db, "test-rule")
        assert not is_suppressed(db, "test-rule")

        dismiss_issue(db, "test-rule")
        assert not is_suppressed(db, "test-rule")

        # Third dismissal — auto-suppressed
        dismiss_issue(db, "test-rule")
        assert is_suppressed(db, "test-rule")
        db.close()


def test_clear_dismissal():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = get_db(tmpdir)
        dismiss_issue(db, "rule-x")
        dismiss_issue(db, "rule-x")
        dismiss_issue(db, "rule-x")
        assert is_suppressed(db, "rule-x")

        clear_dismissal(db, "rule-x")
        assert not is_suppressed(db, "rule-x")
        db.close()


def test_save_issues():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = get_db(tmpdir)
        scan_id = save_scan(db, "proj", ".", 2, 1, 1, 0, 0)
        save_issues(db, scan_id, [
            {"rule_id": "xss", "file": "app.js", "line": 10, "severity": "critical", "category": "security", "title": "XSS"},
            {"rule_id": "perf", "file": "app.py", "line": 20, "severity": "major", "category": "performance", "title": "Loop"},
        ])

        rows = db.execute("SELECT COUNT(*) as cnt FROM issue_log WHERE scan_id = ?", (scan_id,)).fetchone()
        assert rows["cnt"] == 2
        db.close()
