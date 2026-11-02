#!/usr/bin/env bash
# In tools/ ablegen. Konfiguration: tools/gates.conf (Tab-getrennte argv).
# Offline ohne Agent startbar. Während des Laufs keine Quellen ändern.
set -uo pipefail
cd -- "$(dirname -- "$0")/.." || exit 2
CONFIG=tools/gates.conf
MIN_FREI_GB="${MIN_FREI_GB:-10}"
LOG_BASE="${LOG_BASE:-build/qa}"
mkdir -p -- "$LOG_BASE" || { echo 'ROT: nicht gemessen — Logverzeichnis fehlt'; exit 2; }
LOGS=$(mktemp -d "$LOG_BASE/gates-$(date +%Y%m%d-%H%M%S)-XXXXXX") || exit 2
SUMMARY="$LOGS/summary.txt"
: > "$SUMMARY" || exit 2
failed=()
steps=0
say() { printf '%s\n' "$*"; printf '%s\n' "$*" >> "$SUMMARY" || exit 2; }
not_measured() { say "ROT: nicht gemessen — $*"; exit 2; }
say "LOGS: $LOGS"

# Messung vor dem ersten Prüfschritt; df-Status vor jeder Auswertung sichern.
[[ "$MIN_FREI_GB" =~ ^[0-9]+$ && ${#MIN_FREI_GB} -le 6 ]] || not_measured 'MIN_FREI_GB muss eine ganze Zahl bis 999999 sein'
df -Pk . > "$LOGS/disk.log" 2>&1
disk_status=$?
[ "$disk_status" -eq 0 ] || not_measured 'freier Platz nicht lesbar (disk.log)'
available_kb=$(awk 'NR==2 {print $4}' "$LOGS/disk.log")
[[ "$available_kb" =~ ^[0-9]+$ ]] || not_measured 'freier Platz nicht auswertbar (disk.log)'
minimum_kb=$((10#$MIN_FREI_GB * 1024 * 1024))
say "PLATZ: ${available_kb} KiB frei; mindestens ${MIN_FREI_GB} GiB nötig"
[ "$available_kb" -ge "$minimum_kb" ] || not_measured 'zu wenig freier Platz'

# flock gibt die Sperre beim Prozessende frei; die Sperrdatei bleibt erhalten.
exec 9> "$LOG_BASE/sammellauf.lock" || not_measured 'Sperre nicht anlegbar'
flock -n 9 || not_measured 'ein Sammellauf läuft bereits'

step() {
    local name="$1"; shift
    say "== $name"
    "$@" > "$LOGS/$name.log" 2>&1
    local status=$?
    say "EXIT=$status ($LOGS/$name.log)"
    [ "$status" -eq 0 ] || failed+=("$name")
}
trap 'say "ROT: nicht gemessen — Lauf unterbrochen"; exit 2' INT TERM HUP

# Erst vollständig validieren, dann ausführen. Keine eval/source-Ausführung.
[ -r "$CONFIG" ] || { say "ROT: Konfiguration fehlt ($CONFIG)"; exit 1; }
names=()
commands=()
while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != $'\t'* && "$line" != *$'\t' && "$line" != *$'\t\t'* && "$line" != *$'\r'* ]] || { say 'ROT: leeres Feld oder CR in gates.conf'; exit 1; }
    IFS=$'\t' read -r -a fields <<< "$line"
    [ "${#fields[@]}" -ge 2 ] || { say 'ROT: Schritt braucht Name und Befehl (Tab-getrennt)'; exit 1; }
    name="${fields[0]}"
    [[ "$name" =~ ^[a-zA-Z0-9_-]+$ && "$name" != ruttla ]] || { say "ROT: ungültiger/reservierter Schrittname ($name)"; exit 1; }
    for existing in "${names[@]}"; do
        [ "$existing" != "$name" ] || { say "ROT: doppelter Schritt ($name)"; exit 1; }
    done
    # Direkte Ruttla-Aufrufe gehören ausschließlich ans Ende des Runners.
    for token in "${fields[@]:1}"; do
        [[ "${token##*/}" != ruttla ]] || { say 'ROT: Ruttla ist als letzter Schritt fest eingebaut'; exit 1; }
    done
    names+=("$name")
    commands+=("$line")
done < "$CONFIG"
[ "${#commands[@]}" -gt 0 ] || { say 'ROT: null Schritte konfiguriert'; exit 1; }
for line in "${commands[@]}"; do
    IFS=$'\t' read -r -a fields <<< "$line"
    step "${fields[@]}"
    steps=$((steps + 1))
done
step ruttla ruttla --changed-only --format agent
if [ "${#failed[@]}" -gt 0 ]; then
    say "ROT: ${failed[*]}"
    exit 1
fi
say "GRÜN: alle Schritte ($steps konfiguriert + Ruttla)"
exit 0
