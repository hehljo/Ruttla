#!/usr/bin/env python3
"""Rollt den Ruttla-Aufruf-Workflow per Draft-PR in die eigenen GitHub-Repos aus.

Ohne `--apply` nur Plan (kein Schreibzugriff). Mit `--apply` je Repo: Branch
`ruttla-gate` vom Default-Branch, Datei `.github/workflows/ruttla.yml` aus der
Vorlage (Default-Branch eingesetzt), Draft-PR. Nie Merge, nie Push auf den
Default-Branch. Repos, die die Datei schon haben oder archiviert sind, werden
übersprungen. Private Repos nur mit `--include-private` (Actions-Minuten kosten).

Exit: 0 Plan/Ausrollen ohne Fehler · 1 mindestens ein Repo fehlgeschlagen · 3 Bedienfehler
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "docs/integrations/templates/ruttla-caller.yml"
TARGET = ".github/workflows/ruttla.yml"
BRANCH = "ruttla-gate"
TITLE = "Add Ruttla quality gate"
BODY = ("Adds the shared Ruttla gate (logic lives centrally in hehljo/Ruttla). "
        "Profile and accepted findings are read from the base branch on pull requests; "
        "exit 2 (nothing measured) counts as failure.\n\nDraft — review before merging.")


def gh(*args: str, input_data: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, input=input_data,
                          timeout=120)


def repos(owner: str | None) -> list[dict]:
    cmd = ["repo", "list", *( [owner] if owner else []), "--limit", "1000", "--json",
           "nameWithOwner,visibility,isArchived,isFork,defaultBranchRef"]
    done = gh(*cmd)
    if done.returncode != 0:
        raise SystemExit(f"gh repo list: {done.stderr.strip()}")
    return json.loads(done.stdout)


def has_target(repo: str, branch: str) -> bool:
    return gh("api", f"repos/{repo}/contents/{TARGET}?ref={branch}").returncode == 0


def content_for(branch: str) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    return text.replace("branches: [main]", f"branches: [{branch}]")


def apply(repo: str, branch: str) -> str:
    sha = gh("api", f"repos/{repo}/git/ref/heads/{branch}", "--jq", ".object.sha")
    if sha.returncode != 0:
        return f"Fehler: Default-Branch nicht lesbar ({sha.stderr.strip()})"
    made = gh("api", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{BRANCH}",
              "-f", f"sha={sha.stdout.strip()}")
    if made.returncode != 0 and "Reference already exists" not in made.stderr:
        return f"Fehler: Branch ({made.stderr.strip()})"
    payload = json.dumps({"message": TITLE, "branch": BRANCH,
                          "content": base64.b64encode(content_for(branch).encode()).decode()})
    put = gh("api", "-X", "PUT", f"repos/{repo}/contents/{TARGET}", "--input", "-",
             input_data=payload)
    if put.returncode != 0:
        return f"Fehler: Datei ({put.stderr.strip()})"
    pr = gh("pr", "create", "--repo", repo, "--draft", "--base", branch, "--head", BRANCH,
            "--title", TITLE, "--body", BODY)
    if pr.returncode != 0:
        return f"Fehler: PR ({pr.stderr.strip()})"
    return f"Draft-PR {pr.stdout.strip()}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--owner", help="Konto/Organisation (Vorgabe: angemeldetes Konto)")
    ap.add_argument("--only", action="append", default=[], help="nur dieses Repo (owner/name)")
    ap.add_argument("--include-private", action="store_true")
    ap.add_argument("--include-forks", action="store_true")
    ap.add_argument("--apply", action="store_true", help="wirklich Branch + Draft-PR anlegen")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 3
    if not TEMPLATE.is_file():
        print(f"Vorlage fehlt: {TEMPLATE}", file=sys.stderr)
        return 3
    failed = 0
    for r in sorted(repos(args.owner), key=lambda r: r["nameWithOwner"].lower()):
        name, branch = r["nameWithOwner"], (r.get("defaultBranchRef") or {}).get("name")
        if args.only and name not in args.only:
            continue
        reason = ("archiviert" if r["isArchived"] else "Fork" if r["isFork"] and
                  not args.include_forks else "privat (--include-private)"
                  if r["visibility"] != "PUBLIC" and not args.include_private else
                  "leer" if not branch else None)
        if reason is None and has_target(name, branch):
            reason = "hat den Workflow schon"
        if reason:
            print(f"skip   {name:<45} {reason}")
            continue
        if not args.apply:
            print(f"plan   {name:<45} {r['visibility'].lower()} · Basis {branch}")
            continue
        outcome = apply(name, branch)
        failed += outcome.startswith("Fehler")
        print(f"{'FEHLER' if outcome.startswith('Fehler') else 'done  '} {name:<45} {outcome}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
