# HANDOVER

Stand: 2026-09-24. Aktueller Stand, nächste Schritte und Validierung: **STATUS.md**.
Befundhistorie mit Prävention: **LESSONS_LEARNED.md**. Änderungen: **CHANGELOG.md**.

## Was wurde zuletzt beendet?
- PR #1 auf GitHub gemergt, lokaler Branch `main` ist synchron mit `origin/main`.
- Install-Prompts in `README.md`, `README.de.md` und `docs/integrations/github-actions.md` auf die neue GitHub-Repo-URL gesetzt.
- `OWNER_ALLOWED` in `tests/test_provenance.py` erweitert (Provenance-Guard grün).
- `src/ruttla/cli.py` ergänzt: `--changed-only` nutzt ohne Argument standardmäßig `HEAD` (`tests/test_runner.py` getestet).
- Paket lokal via `pip install -e /root/Ruttla --break-system-packages` installiert; CLI `ruttla` ist im System-PATH verfügbar.
- Pi-Skill `/root/.pi/agent/skills/ruttla.md` angelegt.
- Globale Richtlinie in `/root/.pi/agent/AGENTS.md` und `/root/.claude/CLAUDE.md` hinterlegt.
- Alle 102 Unittests, Self-Test (206/206 Sabotage-Proben), Doku-Check und Strict-Self-Scan grün.

---

## Startpunkt nächste Session:
1. Commit-Freigabe für die offenen Änderungen auf `main` einholen.
2. Phase P06 starten: P06-T001 (Finding-Fingerprint) oder Performance-Budgetlauf (`python scripts/benchmark.py --files 10000 --pad-kb 10`).
