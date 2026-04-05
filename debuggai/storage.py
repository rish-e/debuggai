"""SQLite storage for scan history, dismissals, and quality tracking."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEBUGGAI_DIR = ".debuggai"
DB_FILENAME = "debuggai.db"


def get_db_path(project_dir: Optional[str] = None) -> Path:
    """Get path to the DebuggAI database for a project."""
    root = Path(project_dir) if project_dir else Path.cwd()
    db_dir = root / DEBUGGAI_DIR
    db_dir.mkdir(exist_ok=True)
    return db_dir / DB_FILENAME


def get_db(project_dir: Optional[str] = None) -> sqlite3.Connection:
    """Get a connection to the DebuggAI database, creating tables if needed."""
    db_path = get_db_path(project_dir)
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(db)
    return db


def _ensure_schema(db: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            project TEXT,
            target TEXT,
            total_issues INTEGER DEFAULT 0,
            critical INTEGER DEFAULT 0,
            major INTEGER DEFAULT 0,
            minor INTEGER DEFAULT 0,
            info INTEGER DEFAULT 0,
            fidelity_score REAL,
            duration_ms INTEGER,
            scan_mode TEXT
        );

        CREATE TABLE IF NOT EXISTS issue_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER REFERENCES scans(id),
            rule_id TEXT,
            file TEXT,
            line INTEGER,
            severity TEXT,
            category TEXT,
            title TEXT,
            status TEXT DEFAULT 'new',
            fingerprint TEXT
        );

        CREATE TABLE IF NOT EXISTS dismissals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            rule_id TEXT NOT NULL,
            file_pattern TEXT,
            reason TEXT,
            count INTEGER DEFAULT 1,
            auto_suppress INTEGER DEFAULT 0,
            UNIQUE(rule_id, file_pattern)
        );

        CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON scans(timestamp);
        CREATE INDEX IF NOT EXISTS idx_scans_project ON scans(project);
        CREATE INDEX IF NOT EXISTS idx_issue_log_scan ON issue_log(scan_id);
        CREATE INDEX IF NOT EXISTS idx_issue_log_fingerprint ON issue_log(fingerprint);
        CREATE INDEX IF NOT EXISTS idx_dismissals_rule ON dismissals(rule_id);
    """)
    db.commit()


# ── Scan History ──────────────────────────────────────────────


def save_scan(db: sqlite3.Connection, project: str, target: str,
              total: int, critical: int, major: int, minor: int, info: int,
              fidelity_score: Optional[float] = None,
              duration_ms: Optional[int] = None,
              scan_mode: str = "full") -> int:
    """Save a scan result. Returns the scan ID."""
    cursor = db.execute("""
        INSERT INTO scans (project, target, total_issues, critical, major, minor, info,
                          fidelity_score, duration_ms, scan_mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (project, target, total, critical, major, minor, info,
          fidelity_score, duration_ms, scan_mode))
    db.commit()
    return cursor.lastrowid


def save_issues(db: sqlite3.Connection, scan_id: int, issues: list[dict]) -> None:
    """Save issues from a scan."""
    for issue in issues:
        fingerprint = f"{issue.get('rule_id', '')}:{issue.get('file', '')}:{issue.get('line', 0)}"
        db.execute("""
            INSERT INTO issue_log (scan_id, rule_id, file, line, severity, category, title, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (scan_id, issue.get("rule_id"), issue.get("file"), issue.get("line"),
              issue.get("severity"), issue.get("category"), issue.get("title"), fingerprint))
    db.commit()


def get_scan_history(db: sqlite3.Connection, project: Optional[str] = None,
                     limit: int = 20) -> list[dict]:
    """Get recent scan history."""
    if project:
        rows = db.execute("""
            SELECT * FROM scans WHERE project = ? ORDER BY timestamp DESC LIMIT ?
        """, (project, limit)).fetchall()
    else:
        rows = db.execute("""
            SELECT * FROM scans ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_quality_delta(db: sqlite3.Connection, project: str) -> Optional[dict]:
    """Compare latest scan with previous scan to show delta."""
    rows = db.execute("""
        SELECT * FROM scans WHERE project = ? ORDER BY id DESC LIMIT 2
    """, (project,)).fetchall()

    if len(rows) < 2:
        return None

    current, previous = dict(rows[0]), dict(rows[1])
    return {
        "current": current,
        "previous": previous,
        "delta_total": current["total_issues"] - previous["total_issues"],
        "delta_critical": current["critical"] - previous["critical"],
        "delta_major": current["major"] - previous["major"],
        "new_issues": _count_new_issues(db, current["id"], previous["id"]),
        "fixed_issues": _count_fixed_issues(db, current["id"], previous["id"]),
    }


def _count_new_issues(db: sqlite3.Connection, current_scan_id: int, prev_scan_id: int) -> int:
    """Count issues in current scan that weren't in previous scan."""
    row = db.execute("""
        SELECT COUNT(*) as cnt FROM issue_log
        WHERE scan_id = ? AND fingerprint NOT IN (
            SELECT fingerprint FROM issue_log WHERE scan_id = ?
        )
    """, (current_scan_id, prev_scan_id)).fetchone()
    return row["cnt"]


def _count_fixed_issues(db: sqlite3.Connection, current_scan_id: int, prev_scan_id: int) -> int:
    """Count issues in previous scan that aren't in current scan (fixed)."""
    row = db.execute("""
        SELECT COUNT(*) as cnt FROM issue_log
        WHERE scan_id = ? AND fingerprint NOT IN (
            SELECT fingerprint FROM issue_log WHERE scan_id = ?
        )
    """, (prev_scan_id, current_scan_id)).fetchone()
    return row["cnt"]


# ── Dismissal Memory ─────────────────────────────────────────


def dismiss_issue(db: sqlite3.Connection, rule_id: str,
                  file_pattern: Optional[str] = None,
                  reason: str = "") -> None:
    """Record a dismissal. Auto-suppresses after 3 dismissals."""
    # Use explicit SELECT+UPDATE to handle NULL file_pattern correctly
    # (SQLite UNIQUE treats each NULL as distinct)
    existing = db.execute(
        "SELECT id, count FROM dismissals WHERE rule_id = ? AND COALESCE(file_pattern, '') = COALESCE(?, '')",
        (rule_id, file_pattern),
    ).fetchone()

    if existing:
        new_count = existing["count"] + 1
        auto_suppress = 1 if new_count >= 3 else 0
        db.execute(
            "UPDATE dismissals SET count = ?, auto_suppress = ?, timestamp = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (new_count, auto_suppress, existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO dismissals (rule_id, file_pattern, reason) VALUES (?, ?, ?)",
            (rule_id, file_pattern, reason or ""),
        )
    db.commit()


def is_suppressed(db: sqlite3.Connection, rule_id: str,
                  file_path: Optional[str] = None) -> bool:
    """Check if an issue should be auto-suppressed based on dismissal history."""
    row = db.execute("""
        SELECT auto_suppress FROM dismissals
        WHERE rule_id = ?
        AND (COALESCE(file_pattern, '') = '' OR ? LIKE '%' || file_pattern || '%')
        AND auto_suppress = 1
    """, (rule_id, file_path or "")).fetchone()

    return row is not None


def get_dismissals(db: sqlite3.Connection) -> list[dict]:
    """Get all dismissal records."""
    rows = db.execute("""
        SELECT * FROM dismissals ORDER BY count DESC
    """).fetchall()
    return [dict(r) for r in rows]


def clear_dismissal(db: sqlite3.Connection, rule_id: str,
                    file_pattern: Optional[str] = None) -> None:
    """Remove a dismissal (un-suppress a rule)."""
    if file_pattern:
        db.execute("DELETE FROM dismissals WHERE rule_id = ? AND file_pattern = ?",
                   (rule_id, file_pattern))
    else:
        db.execute("DELETE FROM dismissals WHERE rule_id = ?", (rule_id,))
    db.commit()
