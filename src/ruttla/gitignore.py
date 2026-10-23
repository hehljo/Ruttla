"""Git is the ignore oracle; never interpret .gitignore patterns ourselves.

Only untracked ignored paths are returned. Git's --directory compression
does not hide tracked children, so tracked files win over ignore patterns.
No hooks, filters, target code or network access are needed.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

GIT_TIMEOUT_S = 30


def git_ignore_summary(coverage: dict) -> str:
    status = coverage.get("git_ignore_status", "unknown")
    if status == "applied":
        return (f"Git-Ignore angewendet: {coverage.get('files_excluded_by_gitignore', 0)} "
                f"Dateien und {coverage.get('dirs_excluded_by_gitignore', 0)} "
                "ganze Verzeichnisse ausgeschlossen (Inhalte nicht gezählt).")
    reasons = {
        "not_repository": "kein Git-Arbeitsbaum verfügbar",
        "git_unavailable": "git nicht verfügbar",
        "git_error": "Git-Abfrage fehlgeschlagen oder Zeitlimit erreicht",
        "disabled": "explizite Sicht inklusive ignorierter Dateien",
    }
    reason = reasons.get(status, status)
    return f"Git-Ignore NICHT angewendet: {reason}; bisherige Inventarausschlüsse gelten."


@dataclass
class GitIgnore:
    status: str
    files: set[str] = field(default_factory=set)
    dirs: set[str] = field(default_factory=set)


def git_ignored(root: str) -> GitIgnore:
    # Do not let the invoking shell redirect Git to another repository/index.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    cmd = ["git", "-c", "core.fsmonitor=false", "-C", root]
    try:
        repo = subprocess.run(cmd + ["rev-parse", "--is-inside-work-tree"],
                              env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=GIT_TIMEOUT_S)
        if repo.returncode != 0 or repo.stdout.strip() != b"true":
            return GitIgnore("not_repository")
        proc = subprocess.run(
            cmd + ["ls-files", "--others", "--ignored", "--exclude-standard",
                   "--directory", "-z", "--", "."],
            env=env, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=GIT_TIMEOUT_S,
        )
    except FileNotFoundError:
        return GitIgnore("git_unavailable")
    except (OSError, subprocess.SubprocessError):
        return GitIgnore("git_error")
    if proc.returncode != 0:
        return GitIgnore("git_error")
    ignored = GitIgnore("applied")
    for raw in proc.stdout.split(b"\0"):
        if raw:
            path = os.fsdecode(raw)
            if path.endswith("/"):
                ignored.dirs.add(path[:-1])
            else:
                ignored.files.add(path)
    return ignored
