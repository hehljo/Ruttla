"""Git hook index modes, not source syntax: intentionally a Python check.

Git is only queried for paths and metadata. No hook or target code is run.
Ordinary scans do not trust fixture declarations or infer index modes from
working-tree permissions. Tests use real disposable repositories.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from ruttla.core import (
    CheckResult, Context, Finding, SelfTestCase, Severity, Status,
    register, result_for, unmeasured,
)

CHECK_ID = "repo.git_hook_not_executable"
TITLE = "Git-Hook ist im Index nicht ausführbar"
GUIDELINE = "CLAUDE.md § Gates — Git-Hooks brauchen den ausführbaren Indexmodus"
# Git githooks(5), including receive-side and newer reference hooks.
HOOK_NAMES = frozenset("""
applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit
prepare-commit-msg commit-msg post-commit pre-rebase post-checkout post-merge
pre-push pre-receive update proc-receive post-receive post-update
reference-transaction push-to-checkout pre-auto-gc post-rewrite
sendemail-validate fsmonitor-watchman p4-changelist p4-prepare-changelist
p4-post-changelist p4-pre-submit post-index-change
""".split())


def _probe(mode: str, path: str = ".husky/pre-commit", hooks_path: str | None = None):
    declaration: dict = {"modes": {path: mode}}
    if hooks_path is not None:
        declaration["hooks_path"] = hooks_path
    return {path: "#!/bin/sh\nexit 0\n",
            ".ruttla-selftest/git-index.json": json.dumps(declaration)}


@register(
    CHECK_ID, TITLE, severity=Severity.ERROR, safe_by_default=True,
    guideline=GUIDELINE, tags=("git", "hooks", "index-mode"),
    references=("https://git-scm.com/docs/githooks",
                "https://git-scm.com/docs/git-ls-files",
                "https://git-scm.com/docs/git-config#Documentation/git-config.txt-corehooksPath"),
    rationale=(
        "Reproduced on 22.10.2026: a tracked pre-commit hook had index mode "
        "100644; Git skipped it. The repair changed the index to 100755. "
        "Checks tracked standard hook names directly in .husky (excluding _) "
        "and the configured core.hooksPath within the scan root. This is an "
        "index contract, not proof that a hook runs: permissions, Husky shell "
        "wrappers, disabled hooks and invocation flags remain runtime concerns. "
        "A wrapper may intentionally invoke a 644 script through sh; the "
        "requested executable-index policy still applies to .husky entries. "
        "Untracked, conflicted or external hooks never become a measured pass."
    ),
    self_tests=[
        SelfTestCase("gesund: ausführbarer Index", _probe("100755"), Status.PASS),
        SelfTestCase("defekt: nicht ausführbarer Index", _probe("100644"), Status.FAIL,
                     expect_finding_contains="100644"),
        SelfTestCase("gesund: eigener Hookordner", _probe("100755", "hooks/commit-msg", "hooks"), Status.PASS),
        SelfTestCase("defekt: eigener Hookordner", _probe("100644", "hooks/pre-push", "hooks"), Status.FAIL),
        SelfTestCase("ungemessen: kein Index", {".husky/pre-commit": "exit 0\n"}, Status.UNMEASURED),
        SelfTestCase("ungemessen: Husky-Hilfsordner", _probe("100644", ".husky/_/pre-commit", ".husky/_"), Status.UNMEASURED),
    ],
)
def check_git_hooks(ctx: Context) -> CheckResult:
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", ctx.root, *args],
                              capture_output=True, timeout=30)

    try:
        top = git("rev-parse", "--show-toplevel")
        if top.returncode:
            return unmeasured(CHECK_ID, TITLE, "Kein lesbares Git-Arbeitsverzeichnis mit Index.")
        repo = Path(os.fsdecode(top.stdout).strip()).resolve()
        root = Path(ctx.root).resolve()
        index = git("ls-files", "--stage", "--full-name", "-z")
        config = git("config", "--path", "--get", "core.hooksPath")
    except (OSError, subprocess.SubprocessError):
        return unmeasured(CHECK_ID, TITLE, "Git-Index oder Hook-Konfiguration nicht lesbar.")
    if index.returncode or config.returncode not in (0, 1):
        return unmeasured(CHECK_ID, TITLE, "Git-Index oder core.hooksPath nicht lesbar.")

    directories = {repo / ".husky"}
    incomplete = []
    if config.returncode == 0:
        configured = Path(os.fsdecode(config.stdout).rstrip("\n"))
        directory = (repo / configured).resolve()
        if directory.is_relative_to(root):
            directories.add(directory)
        else:
            incomplete.append("core.hooksPath liegt außerhalb der Prüfwurzel")
    findings = []
    candidates = set()
    for record in index.stdout.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, _oid, stage = metadata.decode("ascii").split()
        path = repo / os.fsdecode(raw_path)
        if (not path.is_relative_to(root) or path.parent not in directories
                or path.name not in HOOK_NAMES
                or path.is_relative_to(repo / ".husky" / "_")):
            continue
        rel = path.relative_to(root).as_posix()
        if stage != "0" or mode not in ("100644", "100755"):
            incomplete.append(f"{rel}: kein regulärer, konfliktfreier Indexeintrag")
            continue
        candidates.add(rel)
        if mode == "100644":
            findings.append(Finding(
                CHECK_ID, Severity.ERROR,
                "Git-Hook hat Indexmodus 100644 und ist nach dem Checkout nicht ausführbar.",
                file=rel, line=1, evidence=f"100644 {rel}",
                fix="Ausführbarkeit im Arbeitsbaum setzen und mit git update-index --chmod=+x für diesen Hook im Index sichern; Indexmodus 100755 prüfen.",
                guideline=GUIDELINE,
            ))
    if incomplete and not findings:
        return CheckResult(CHECK_ID, Status.UNMEASURED, TITLE,
                           reason="; ".join(sorted(set(incomplete))),
                           units_examined=len(candidates), unit_label="Git-Hook-Kandidaten")
    return result_for(CHECK_ID, TITLE, findings, len(candidates), "Git-Hook-Kandidaten")
