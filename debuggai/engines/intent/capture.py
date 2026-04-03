"""Intent capture — gather the original intent from various sources."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from debuggai.utils.git import get_commit_message, is_git_repo


def capture_intent(
    cli_intent: Optional[str] = None,
    spec_file: Optional[str] = None,
    from_commit: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> tuple[str, str]:
    """Capture intent from the best available source.

    Returns (intent_text, source_name).
    """
    # Priority: explicit CLI > spec file > commit message
    if cli_intent:
        return cli_intent, "cli"

    if spec_file:
        path = Path(spec_file)
        if path.exists():
            return path.read_text().strip(), "spec_file"

    # Check for .debuggai-intent.md in project dir
    if project_dir:
        intent_file = Path(project_dir) / ".debuggai-intent.md"
        if intent_file.exists():
            return intent_file.read_text().strip(), "spec_file"

    # Fall back to git commit message
    if from_commit and is_git_repo(project_dir):
        try:
            msg = get_commit_message(from_commit, cwd=project_dir)
            if msg:
                return msg, "git_commit"
        except RuntimeError:
            pass

    # Try HEAD commit
    if is_git_repo(project_dir):
        try:
            msg = get_commit_message("HEAD", cwd=project_dir)
            if msg:
                return msg, "git_commit"
        except RuntimeError:
            pass

    return "", "none"
