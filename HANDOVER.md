# HANDOVER

Stand: 2026-09-24. Aktueller Stand, nächste Schritte und Validierung: **STATUS.md**.
Befundhistorie mit Prävention: **LESSONS_LEARNED.md**. Änderungen: **CHANGELOG.md**.

## Was wurde zuletzt beendet?
- PR #1 auf GitHub gemergt, lokaler Branch `main` synchronisiert.
- Woodpecker-Logo (`docs/icon/logo.svg`) mit dynamischem Specht-Rot (`#C92A2A` / `#FF6B6B`) integriert.
- Specht-Metapher in `README.md`, `README.de.md` und `docs/decisions/ADR-0001-public-naming.md` verankert.
- Install-Prompts in `README.md`, `README.de.md` und `docs/integrations/github-actions.md` auf die neue GitHub-Repo-URL gesetzt.
- `OWNER_ALLOWED` in `tests/test_provenance.py` erweitert (Provenance-Guard grün).
- `src/ruttla/cli.py` ergänzt: `--changed-only` nutzt ohne Argument standardmäßig `HEAD` (`tests/test_runner.py` getestet).
- Paket lokal via `pip install -e /root/Ruttla --break-system-packages` installiert; CLI `ruttla` ist im System-PATH verfügbar.
- Pi-Skill `/root/.pi/agent/skills/ruttla.md` angelegt.
- Globale Richtlinie in `/root/.pi/agent/AGENTS.md` und `/root/.claude/CLAUDE.md` hinterlegt.
- Commit `9d1cefd` direkt auf `main` gepusht; CI-Lauf 35975401774 mit 16/16 Jobs grün.

---

## Startpunkt nächste Session:
1. `HANDOVER.md` committen/pushen.
2. Phase P06 starten: P06-T001 (Finding-Fingerprint) oder Performance-Budgetlauf (`python scripts/benchmark.py --files 10000 --pad-kb 10`).
