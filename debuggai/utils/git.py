"""Git utilities for DebuggAI."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FileDiff:
    """A single file's diff information."""

    path: str
    status: str  # A=added, M=modified, D=deleted, R=renamed
    old_path: Optional[str] = None
    hunks: list[str] = field(default_factory=list)
    content: Optional[str] = None
    language: Optional[str] = None


def _run_git(args: list[str], cwd: Optional[str] = None) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def is_git_repo(path: Optional[str] = None) -> bool:
    """Check if path is inside a git repository."""
    try:
        _run_git(["rev-parse", "--git-dir"], cwd=path)
        return True
    except (RuntimeError, FileNotFoundError):
        return False


def get_repo_root(path: Optional[str] = None) -> str:
    """Get the root directory of the git repository."""
    return _run_git(["rev-parse", "--show-toplevel"], cwd=path).strip()


def get_staged_diff(cwd: Optional[str] = None) -> str:
    """Get diff of staged changes."""
    return _run_git(["diff", "--cached"], cwd=cwd)


def get_diff(ref: str = "HEAD~1", cwd: Optional[str] = None) -> str:
    """Get diff against a reference."""
    return _run_git(["diff", ref], cwd=cwd)


def get_changed_files(ref: Optional[str] = None, staged: bool = False, cwd: Optional[str] = None) -> list[FileDiff]:
    """Get list of changed files with their diffs."""
    if staged:
        args = ["diff", "--cached", "--name-status"]
    elif ref:
        args = ["diff", "--name-status", ref]
    else:
        args = ["diff", "--name-status", "HEAD"]

    output = _run_git(args, cwd=cwd)
    files = []

    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][0]  # First char: A, M, D, R
        file_path = parts[-1]

        ext_to_lang = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
        }
        lang = ext_to_lang.get(Path(file_path).suffix.lower())

        # Get the actual diff content for this file
        if staged:
            diff_args = ["diff", "--cached", "--", file_path]
        elif ref:
            diff_args = ["diff", ref, "--", file_path]
        else:
            diff_args = ["diff", "HEAD", "--", file_path]

        try:
            diff_content = _run_git(diff_args, cwd=cwd)
        except RuntimeError:
            diff_content = ""

        files.append(
            FileDiff(
                path=file_path,
                status=status,
                old_path=parts[1] if status == "R" and len(parts) > 2 else None,
                hunks=[diff_content] if diff_content else [],
                language=lang,
            )
        )

    return files


def get_file_content(file_path: str, ref: Optional[str] = None, cwd: Optional[str] = None) -> Optional[str]:
    """Read file content, optionally at a specific git ref."""
    if ref:
        try:
            return _run_git(["show", f"{ref}:{file_path}"], cwd=cwd)
        except RuntimeError:
            return None
    else:
        full_path = Path(cwd or ".") / file_path
        if full_path.exists():
            return full_path.read_text()
        return None


def get_commit_message(ref: str = "HEAD", cwd: Optional[str] = None) -> str:
    """Get commit message for a ref."""
    return _run_git(["log", "-1", "--format=%B", ref], cwd=cwd).strip()
