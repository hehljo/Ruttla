#!/usr/bin/env python3
"""Funktionsinventar: fremde API (OpenAPI) gegen den eigenen Code abgleichen.

Ein Werkzeug fuer jedes Projekt; die Projektdaten stehen in einer TOML-Konfiguration.

  api_inventar.py KONFIG --refresh   Spec neu holen, kompakten Schnappschuss schreiben
  api_inventar.py KONFIG             Inventar-Markdown erzeugen
  api_inventar.py KONFIG --check     Exit 1, wenn das Inventar veraltet ist

"umgesetzt" kommt ausschliesslich aus dem Code-Scan, nie aus der Entscheidungsdatei.
Exit 2 = nicht gemessen (Schnappschuss fehlt, null Operationen, kein Code gefunden).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MARKER = "<!-- api-inventar v1 -->"
METHODS = ("get", "post", "put", "delete", "patch")
STATUS_DONE, STATUS_SKIP, STATUS_OPEN = "umgesetzt", "weggelassen", "offen"


@dataclass
class Fund:
    datei: str
    zeile: int
    methode: str
    pfad: str


@dataclass
class Operation:
    methode: str
    pfad: str
    bereich: str
    zweck: str
    op_id: str
    funde: list[Fund] = field(default_factory=list)


def norm_spec(pfad: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", pfad).rstrip("/") or "/"


def extract_spec(text: str) -> dict:
    """OpenAPI als JSON-Datei oder in eine Doku-Seite eingebettet."""
    text = text.lstrip()
    if text.startswith("{"):
        return json.loads(text)
    pos = text.find('"openapi"')
    if pos < 0:
        raise ValueError("keine OpenAPI-Spec in der Quelle gefunden")
    start = text.rindex("{", 0, pos)
    spec, _ = json.JSONDecoder().raw_decode(text[start:])
    return spec


def refresh(cfg: dict, basis: Path) -> None:
    q = cfg["quelle"]
    with urllib.request.urlopen(q["url"], timeout=60) as r:  # noqa: S310 - feste Konfig-URL
        roh = r.read()
    spec = extract_spec(roh.decode("utf-8"))
    ops = [
        {"methode": m.upper(), "pfad": p, "bereich": (o.get("tags") or ["-"])[0],
         "zweck": (o.get("summary") or "").strip(), "op_id": o.get("operationId", "")}
        for p, d in spec.get("paths", {}).items() for m, o in d.items() if m in METHODS
    ]
    if not ops:
        raise SystemExit("nicht gemessen: Spec enthaelt null Operationen")
    snap = {
        "quelle": q["url"], "titel": spec.get("info", {}).get("title", ""),
        "version": str(spec.get("info", {}).get("version", "")).strip(),
        "abgerufen": dt.date.today().isoformat(), "sha256": hashlib.sha256(roh).hexdigest(),
        "operationen": sorted(ops, key=lambda o: (o["bereich"], o["pfad"], o["methode"])),
    }
    ziel = basis / q["snapshot"]
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(snap, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(ops)} Operationen, Version {snap['version']} -> {ziel}")


def scan_code(cfg: dict, basis: Path, erste_segmente: set[str]) -> list[Fund]:
    c = cfg["code"]
    param = re.compile(c["param_pattern"])
    methode_re = re.compile(c["method_pattern"])
    block_ende = re.compile(c["block_end_pattern"])
    seg = "|".join(re.escape(s) for s in sorted(erste_segmente, key=len, reverse=True))
    pfad_re = re.compile(r'"[^"\n]*?(/(?:' + seg + r')(?:/[^"?\s#&]*)?)[^"\n]*"')
    funde: list[Fund] = []
    for root in c["roots"]:
        for datei in sorted((basis / root).glob(c["glob"])):
            text = datei.read_text(encoding="utf-8", errors="replace")
            ohne_param = param.sub("{}", text)
            for m in pfad_re.finditer(ohne_param):
                pfad = m.group(1).rstrip("/") or "/"
                rest = ohne_param[m.end():]
                ende = block_ende.search(rest)
                block = rest[: ende.start()] if ende else rest
                mm = methode_re.search(block)
                zeile = ohne_param.count("\n", 0, m.start()) + 1
                funde.append(Fund(str(datei.relative_to(basis)), zeile,
                                  mm.group(1) if mm else c["default_method"], pfad))
    return funde


def build(cfg: dict, basis: Path) -> tuple[str, int]:
    snap_pfad = basis / cfg["quelle"]["snapshot"]
    if not snap_pfad.exists():
        return "", 2
    snap = json.loads(snap_pfad.read_text(encoding="utf-8"))
    ops = [Operation(**o) for o in snap["operationen"]]
    if not ops:
        return "", 2
    nach_pfad: dict[str, list[Operation]] = {}
    for o in ops:
        nach_pfad.setdefault(norm_spec(o.pfad), []).append(o)
    # Nur feste erste Segmente als Suchanker; "{}" am Anfang traefe jeden Pfad-String im Code.
    erste = {norm_spec(o.pfad).split("/")[1] for o in ops if norm_spec(o.pfad) != "/"} - {"{}"}
    funde = scan_code(cfg, basis, erste)
    if not funde:
        return "", 2
    fremd, abweichung = [], []
    for f in funde:
        kandidaten = nach_pfad.get(f.pfad)
        if not kandidaten:
            fremd.append(f)
            continue
        treffer = [o for o in kandidaten if o.methode == f.methode]
        if treffer:
            treffer[0].funde.append(f)
        else:
            abweichung.append((f, "/".join(o.methode for o in kandidaten)))
    ent_pfad = basis / cfg["ausgabe"]["entscheidungen"]
    ent = tomllib.loads(ent_pfad.read_text(encoding="utf-8")) if ent_pfad.exists() else {}
    per_bereich, per_op = ent.get("bereiche", {}), ent.get("operationen", {})

    def status(o: Operation) -> tuple[str, str]:
        if o.funde:
            return STATUS_DONE, ", ".join(f"`{f.datei}:{f.zeile}`" for f in o.funde)
        e = per_op.get(o.op_id) or per_bereich.get(o.bereich)
        if e and e.get("status") == STATUS_SKIP and e.get("grund"):
            return STATUS_SKIP, e["grund"]
        return STATUS_OPEN, (e or {}).get("notiz", "")

    bereiche: dict[str, list[Operation]] = {}
    for o in ops:
        bereiche.setdefault(o.bereich, []).append(o)
    zeilen = [MARKER, f"# {cfg['ausgabe']['titel']}", "",
              f"Generiert von `api_inventar.py` — nicht von Hand bearbeiten. Entscheidungen: "
              f"`{cfg['ausgabe']['entscheidungen']}`.", "",
              f"Quelle: {snap['quelle']} · {snap['titel']} {snap['version']} · abgerufen {snap['abgerufen']} · "
              f"SHA-256 `{snap['sha256'][:16]}…`", "",
              "| Bereich | gesamt | umgesetzt | weggelassen | offen |", "|---|---:|---:|---:|---:|"]
    summe = [0, 0, 0, 0]
    for name, liste in sorted(bereiche.items()):
        st = [status(o)[0] for o in liste]
        n = [len(liste), st.count(STATUS_DONE), st.count(STATUS_SKIP), st.count(STATUS_OPEN)]
        summe = [a + b for a, b in zip(summe, n)]
        zeilen.append(f"| {name} | " + " | ".join(map(str, n)) + " |")
    zeilen.append("| **Summe** | " + " | ".join(f"**{x}**" for x in summe) + " |")
    zeilen += ["", "## Abweichungen", ""]
    if abweichung:
        zeilen += ["Pfad bekannt, aber HTTP-Methode passt nicht zur Spec:", "",
                   "| Ort | Code | Spec |", "|---|---|---|"]
        zeilen += [f"| `{f.datei}:{f.zeile}` | {f.methode} `{f.pfad}` | {m} |" for f, m in abweichung]
    if fremd:
        zeilen += ["", "Pfade im Code, die die Spec nicht kennt (undokumentiert/Legacy — Risiko bei Server-Updates):", "", "| Ort | Code |", "|---|---|"]
        zeilen += [f"| `{f.datei}:{f.zeile}` | {f.methode} `{f.pfad}` |" for f in fremd]
    if not (abweichung or fremd):
        zeilen.append("Keine.")
    for name, liste in sorted(bereiche.items()):
        zeilen += ["", f"## {name}", "", "| Status | Methode | Pfad | Zweck | Ort / Grund |",
                   "|---|---|---|---|---|"]
        for o in liste:
            s, info = status(o)
            zweck = o.zweck.replace("|", "\\|")
            zeilen.append(f"| {s} | {o.methode} | `{o.pfad}` | {zweck} | {info} |")
    return "\n".join(zeilen) + "\n", 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("konfig", type=Path)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    cfg = tomllib.loads(a.konfig.read_text(encoding="utf-8"))
    basis = (a.konfig.parent / cfg.get("basis", ".")).resolve()
    if a.refresh:
        refresh(cfg, basis)
    text, rc = build(cfg, basis)
    if rc:
        print("nicht gemessen: Schnappschuss fehlt, null Operationen oder kein Code-Fund", file=sys.stderr)
        return rc
    ziel = basis / cfg["ausgabe"]["datei"]
    if a.check:
        alt = ziel.read_text(encoding="utf-8") if ziel.exists() else ""
        if alt != text:
            print(f"veraltet: {ziel} — Generator ohne --check laufen lassen", file=sys.stderr)
            return 1
        print(f"aktuell: {ziel}")
        return 0
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")
    print(f"geschrieben: {ziel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
