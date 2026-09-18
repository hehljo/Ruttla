#!/usr/bin/env bash
# Auto-Push für CODE_QUALITY_GENERAL.
#
# Pusht NUR, wenn die Sabotage-Gegenprobe grün ist — ein Gate, dessen eigene
# Gegenprobe rot ist, hat im Repo nichts verloren.
#
#   ./autopush.sh              # einmal: prüfen, committen, pushen
#   ./autopush.sh --watch      # dauerhaft beobachten (alle 60 s)
#   ./autopush.sh --watch 300  # eigenes Intervall in Sekunden
#
# Exit: 0 gepusht oder nichts zu tun · 1 Gegenprobe rot · 3 Fehler

set -u
cd "$(dirname "$0")" || exit 3

run_once() {
  # Ausgabe in eine Variable, Status SOFORT danach, dann erst filtern.
  # 'python3 … | tail' liefert immer die 0 von tail.
  local out status
  out=$(python3 master_gate.py --self-test --no-color 2>&1)
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "Gegenprobe rot — kein Push." >&2
    echo "$out" | grep -E '✗|DURCHGEFALLEN|NICHT GEMESSEN' >&2
    return 1
  fi

  if [ -z "$(git status --porcelain)" ]; then
    return 0
  fi

  local proben
  proben=$(echo "$out" | grep -oE '[0-9]+/[0-9]+ Sabotage-Proben' | head -1)
  local checks
  checks=$(echo "$out" | grep -oE '^[0-9]+ Checks registriert' | grep -oE '^[0-9]+')

  git add -A
  git commit -q -m "Checks aktualisiert: ${checks:-?} Checks, ${proben:-Gegenprobe grün}

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>" || return 3

  if ! git push -q origin HEAD 2>/dev/null; then
    echo "Push fehlgeschlagen — Commit liegt lokal." >&2
    return 3
  fi
  echo "Gepusht: $(git log -1 --format=%h) (${checks:-?} Checks, ${proben:-?})"
  return 0
}

if [ "${1:-}" = "--watch" ]; then
  interval="${2:-60}"
  echo "Beobachte $(pwd), Intervall ${interval}s. Abbruch mit Strg-C."
  while true; do
    run_once
    sleep "$interval"
  done
fi

run_once
