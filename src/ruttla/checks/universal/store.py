"""Universal: App-Store-Metadaten, die App Review sicher ablehnt.

Gemessen wird an der Quelle der Store-Texte, unabhängig vom Werkzeug:
fastlane-deliver-Ordner (``metadata/<locale>/<feld>.txt``) und JSON-Profile,
die je Sprache ein ``subtitle`` bzw. ``reviewNotes`` tragen (eigene
Release-Werkzeuge). Erkannt wird an der Eigenschaft „trägt einen Store-Untertitel“,
nicht am Pfadnamen.
"""

from __future__ import annotations

import json
import os
import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    register,
    result_for,
    SelfTestCase,
    Severity,
    Status,
    unmeasured,
)

# Felder, die Apple bei Markenbegriffen ablehnt (5.2.5 / 2.3.7), und Felder,
# in denen ein verweisender Gebrauch („für iPhone“) zulässig sein kann.
_HARD_FIELDS = ("name", "subtitle", "keywords")
_SOFT_FIELDS = ("promotionalText", "description")
_FIELD_ALIASES = {
    "name": "name", "subtitle": "subtitle", "keywords": "keywords",
    "promotionalText": "promotionalText", "promotional_text": "promotionalText",
    "description": "description",
    "reviewNotes": "reviewNotes", "review_notes": "reviewNotes",
}
_FASTLANE_FIELDS = {
    "name.txt": "name", "subtitle.txt": "subtitle", "keywords.txt": "keywords",
    "promotional_text.txt": "promotionalText", "description.txt": "description",
}

# Apple-Produktnamen aus Apples Trademark List. Bewusst NICHT enthalten:
# Allerweltswörter mit Markenschutz (Apple, Finder, Safari, Spotlight,
# Photos) — App B (macOS) wurde mit dem Schlüsselwort „Finder“ freigegeben, und
# „Synology Photos“ ist ein Fremdprodukt. Ein Treffer dort wäre ein
# falsch-positiver Abbruch.
_APPLE_TERMS = re.compile(
    r"(?<![\w-])(?:"
    r"Mac(?!\s*-?\s*(?:Adresse|address))|MacBook|iMac|macOS|"
    r"iPhone|iPad|iPadOS|iOS|watchOS|tvOS|visionOS|"
    r"Apple\s+(?:Watch|TV|Pay|Music|Vision\s+Pro)|Vision\s+Pro|"
    r"AirPods|AirPlay|AirDrop|AirTag|iCloud|Siri|FaceTime|iMessage|"
    r"App\s+Store|HomePod|HomeKit|CarPlay|Xcode"
    r")(?![\w])",
)
# Im Schlüsselwortfeld steht oft alles klein: „mac“ als ganzes Stichwort.
_APPLE_KEYWORD_LOWER = re.compile(
    r"^(?:mac|macos|macbook|imac|iphone|ipad|ipados|ios|icloud|siri|"
    r"facetime|imessage|app store|airdrop|airplay|carplay|xcode)$",
    re.IGNORECASE,
)

# Belegt (App A (macOS), 04.10.2026, Guideline 2.1(a)): die Review Notes
# erklärten, ein Demo-Zugang sei nicht möglich. Apple akzeptiert das nicht.
_DEMO_REFUSED = re.compile(
    r"(?:demo|test|review)[\s-]*(?:account|konto|zugang|login|user|benutzer)\w*"
    r"[^.\n]{0,60}?(?:cannot|can't|can not|could not|not be provided|not possible|"
    r"unable|not available|kann\s+nicht|nicht\s+(?:möglich|bereitgestellt|verfügbar))"
    r"|\bno\s+(?:demo|test)\s+account\b"
    r"|\bkein(?:en)?\s+(?:demo|test)[\s-]*(?:konto|zugang|account)",
    re.IGNORECASE,
)
_SIGN_IN = re.compile(
    r"\b(?:sign[\s-]?in|log[\s-]?in|anmelde\w*|einloggen)\b", re.IGNORECASE)
_CREDENTIAL = re.compile(
    r"\b(?:username|user name|password|benutzername|passwort|kennwort)\b",
    re.IGNORECASE)
_DEMO_KEY = re.compile(r"demo", re.IGNORECASE)


def _line_of(text: str, value: str, nth: int = 0) -> int | None:
    """Zeile, in der ein JSON-Stringwert steht (n-tes Vorkommen: gleiche
    Notes in zwei Sprachblöcken sollen auf zwei Zeilen zeigen)."""
    probe = json.dumps(value, ensure_ascii=False)[1:-1][:60]
    idx = -1
    for _ in range(nth + 1):
        idx = text.find(probe, idx + 1) if probe else -1
        if idx < 0:
            return None
    return text.count("\n", 0, idx) + 1


def _has_demo_value(node) -> bool:
    """Trägt das Objekt einen nicht leeren Demo-Zugang (Name oder Verweis)?"""
    if not isinstance(node, dict):
        return False
    for key, value in node.items():
        if _DEMO_KEY.search(key) and value not in (None, "", {}, [], False):
            return True
    return False


def _json_records(ctx: Context) -> list[dict]:
    """Store-Sprachblöcke aus JSON: jedes Objekt mit String-``subtitle``
    oder String-``reviewNotes``. Ein Demo-Zugang zählt, wenn er im Block
    selbst oder in einem umgebenden Objekt derselben Datei steht."""
    records: list[dict] = []
    for f in ctx.files(".json"):
        seen: dict[str, int] = {}
        try:
            data = json.loads(f.text)
        except (ValueError, UnicodeDecodeError):
            continue

        def walk(node, path: list[str], demo_above: bool) -> None:
            if isinstance(node, dict):
                demo_here = demo_above or _has_demo_value(node)
                fields = {}
                for key, value in node.items():
                    canon = _FIELD_ALIASES.get(key)
                    if canon and isinstance(value, str):
                        fields[canon] = value
                if "subtitle" in fields or "reviewNotes" in fields:
                    nth = {}
                    for key, value in fields.items():
                        nth[key] = seen.get(value, 0)
                        seen[value] = nth[key] + 1
                    records.append({"nth": nth,
                        "file": f.rel, "text": f.text,
                        "where": "/".join(path) or "(Wurzel)",
                        "fields": fields, "demo": demo_here,
                    })
                for key, value in node.items():
                    walk(value, path + [str(key)], demo_here)
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, path + [str(i)], demo_above)

        walk(data, [], False)
    return records


def _fastlane_records(ctx: Context) -> list[dict]:
    """fastlane deliver: ``…/metadata/<locale>/<feld>.txt`` und
    ``…/metadata/review_information/{notes,demo_user}.txt``."""
    groups: dict[str, dict] = {}
    for f in ctx.files(".txt"):
        parts = f.rel.split("/")
        if len(parts) < 3 or parts[-3] != "metadata":
            continue
        base = os.path.basename(f.rel)
        folder = "/".join(parts[:-1])
        if parts[-2] == "review_information":
            rec = groups.setdefault(folder, {
                "file": None, "text": "", "where": folder, "fields": {},
                "demo": False})
            if base == "notes.txt":
                rec["file"], rec["text"] = f.rel, f.text
                rec["fields"]["reviewNotes"] = f.text
            elif base == "demo_user.txt" and f.text.strip():
                rec["demo"] = True
            continue
        canon = _FASTLANE_FIELDS.get(base)
        if canon:
            rec = groups.setdefault(f"{folder}/{base}", {
                "file": f.rel, "text": f.text, "where": parts[-2],
                "fields": {}, "demo": False})
            rec["fields"][canon] = f.text
    return [r for r in groups.values() if r["file"]]


def _store_records(ctx: Context) -> list[dict]:
    return _json_records(ctx) + _fastlane_records(ctx)


def _trademark_hits(field: str, value: str) -> list[str]:
    hits = [m.group(0) for m in _APPLE_TERMS.finditer(value)]
    if field == "keywords":
        hits += [w.strip() for w in value.split(",")
                 if _APPLE_KEYWORD_LOWER.match(w.strip())
                 and w.strip() not in hits]
    return sorted(set(hits))


_HEALTHY_JSON = json.dumps({"locales": {
    "de-DE": {"name": "{app}", "subtitle": "Synology Photos am Desktop",
              "keywords": "Fotoverwaltung,Album,Finder",
              "description": "Läuft auf jedem Mac mit macOS 15.",
              "reviewNotes": "Sign in with the demo account below.",
              "demoAccountName": "appreview"}}}, ensure_ascii=False)
_BROKEN_SUBTITLE_JSON = json.dumps({"locales": {
    "de-DE": {"name": "{app}", "subtitle": "Für Synology Photos am Mac",
              "keywords": "Album", "description": "x"}}}, ensure_ascii=False)
_TM_FIX = ("Plattformnamen streichen; die App erscheint ohnehin nur im "
           "passenden Store. Neutral: „Desktop“, „Rechner“, „computer“.")


def _trademark_result(ctx: Context, check_id: str, title: str,
                      fields: tuple[str, ...], severity: Severity,
                      verdict: str) -> CheckResult:
    """Gemeinsamer Messweg beider Marken-Checks; geprüft wird je Textfeld."""
    records = [r for r in _store_records(ctx)
               if any(k in r["fields"] for k in fields)]
    if not records:
        return unmeasured(check_id, title,
                          "Keine Store-Metadaten (fastlane metadata/ oder JSON "
                          f"mit {'/'.join(fields)}) gefunden.")
    findings: list[Finding] = []
    examined = 0
    for rec in records:
        for field in fields:
            value = rec["fields"].get(field)
            if value is None:
                continue
            examined += 1
            hits = _trademark_hits(field, value)
            if not hits:
                continue
            findings.append(Finding(
                check_id=check_id, severity=severity,
                message=f"{', '.join(hits)} in {field} ({rec['where']}): "
                        f"{verdict}",
                file=rec["file"], line=_line_of(rec["text"], value, rec.get("nth", {}).get(field, 0)),
                fix=_TM_FIX,
                guideline="App Review Guidelines 5.2.5",
            ))
    return result_for(check_id, title, findings, examined, "Store-Textfelder")


@register(
    "store.apple_trademark_in_metadata",
    "Apple-Marke in Name, Untertitel oder Schlüsselwörtern",
    severity=Severity.ERROR,
    guideline="App Review Guidelines 5.2.5 / 2.3.7; Apple Trademark List",
    references=(
        "https://developer.apple.com/app-store/review/guidelines/#intellectual-property",
        "https://www.apple.com/legal/intellectual-property/guidelinesfor3rdparties.html",
    ),
    # Hart ohne Profil: belegte Ablehnung, und ein Apple-Produktname im
    # Namen, Untertitel oder Schlüsselwort ist nie zulässig.
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            # Gesund-Referenz: „Finder“ als Schlüsselwort (App B (macOS) so
            # freigegeben), „Mac“ nur in der Beschreibung (eigener Check),
            # Fremdmarke „Synology Photos“ im Untertitel.
            name="gesund: Apple-Marke nur in der Beschreibung",
            files={"config/store/app.json": _HEALTHY_JSON},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: „Mac“ im Untertitel (App A (macOS), abgelehnt)",
            files={"config/store/app.json": _BROKEN_SUBTITLE_JSON},
            expect=Status.FAIL,
            expect_finding_contains="subtitle",
        ),
        SelfTestCase(
            name="negativ: fastlane-Schlüsselwort „iphone“ klein geschrieben",
            files={"fastlane/metadata/en-US/keywords.txt": "photo,iphone,album\n",
                   "fastlane/metadata/en-US/subtitle.txt": "Photos on the go\n"},
            expect=Status.FAIL,
            expect_finding_contains="iphone",
        ),
        SelfTestCase(
            # „Mac-Adresse“ ist Netzwerktechnik, kein Apple-Produkt.
            name="gesund: Mac-Adresse im Untertitel",
            files={"config/store/app.json": json.dumps({"locales": {"de-DE": {
                "subtitle": "Zeigt jede Mac-Adresse", "keywords": "netz"}}})},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="nicht gemessen: package.json mit iPhone-Stichwort ist kein Store-Text",
            files={"package.json": '{"name": "x", "description": "iPhone app",'
                                   ' "keywords": ["iphone"]}'},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_apple_trademark(ctx: Context) -> CheckResult:
    """Apple lehnt Apple-Produktnamen in Name, Untertitel und Schlüsselwörtern ab.

    Belegt am 04.10.2026 (App A (macOS), macOS): abgelehnt nach Guideline 5.2.5
    wegen „Mac“ im Untertitel („Für Synology Photos am Mac“). Ein Review-
    Durchlauf kostet Tage. Da die App ohnehin nur im passenden Store
    erscheint, trägt der Plattformname dort keine Information.
    """
    return _trademark_result(
        ctx, "store.apple_trademark_in_metadata",
        "Apple-Marke in Name, Untertitel oder Schlüsselwörtern",
        _HARD_FIELDS, Severity.ERROR,
        "App Review lehnt Apple-Marken hier ab (5.2.5/2.3.7).")


@register(
    "store.apple_trademark_in_description",
    "Apple-Marke in Beschreibung oder Werbetext",
    severity=Severity.WARNING,
    guideline="App Review Guidelines 5.2.5; Apple Trademark List",
    references=(
        "https://www.apple.com/legal/intellectual-property/guidelinesfor3rdparties.html",
    ),
    self_tests=[
        SelfTestCase(
            name="warnung: „Mac“ in der Beschreibung",
            files={"config/store/app.json": _HEALTHY_JSON},
            expect=Status.FAIL,
            expect_finding_contains="description",
        ),
        SelfTestCase(
            name="gesund: Beschreibung ohne Apple-Marke",
            files={"config/store/app.json": json.dumps({"locales": {"en-US": {
                "subtitle": "Synology Photos on the desktop",
                "description": "Fast and clear, straight from your NAS."}}})},
            expect=Status.PASS,
        ),
    ],
)
def check_apple_trademark_description(ctx: Context) -> CheckResult:
    """Verweisender Gebrauch („für Mac“) ist in der Beschreibung zulässig,
    „Mac-App“ als Wortteil aber schon grenzwertig. Nur Warnung: App A (macOS)
    wurde allein für den Untertitel abgelehnt, App B (macOS) trug „Mac“ in der
    Beschreibung und ging durch.
    """
    return _trademark_result(
        ctx, "store.apple_trademark_in_description",
        "Apple-Marke in Beschreibung oder Werbetext",
        _SOFT_FIELDS, Severity.WARNING,
        "verweisend zulässig, aber Ablehnungsrisiko — neutral formulieren.")


@register(
    "store.review_demo_access_missing",
    "Review Notes ohne Demo-Zugang für App Review",
    severity=Severity.WARNING,
    guideline="App Review Guidelines 2.1(a)",
    references=(
        "https://developer.apple.com/app-store/review/guidelines/#app-completeness",
    ),
    # Bewusst nur Warnung: App B (macOS) trug denselben Ablehnungssatz und wurde
    # freigegeben (der Reviewer hat einen SMB-Server, aber keinen Synology-
    # NAS). Ob die Gegenstelle für Apple verfügbar ist, steht nicht im Text.
    self_tests=[
        SelfTestCase(
            name="gesund: Anmeldung beschrieben, Demo-Zugang hinterlegt",
            files={"config/store/app.json": _HEALTHY_JSON},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: fastlane demo_user.txt neben notes.txt",
            files={
                "fastlane/metadata/review_information/notes.txt":
                    "Log in with username and password below.\n",
                "fastlane/metadata/review_information/demo_user.txt": "review\n",
            },
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="negativ: Notes lehnen Demo-Zugang ab (App A (macOS), abgelehnt)",
            files={"config/store/app.json": json.dumps({"locales": {"en-US": {
                "subtitle": "x",
                "reviewNotes": "A demo account cannot be provided: the app "
                               "only works against a NAS."}}})},
            expect=Status.FAIL,
            expect_finding_contains="2.1(a)",
        ),
        SelfTestCase(
            # Nur Warnung: App B (macOS) (SMB-Zugangsdaten in den Notes) wurde
            # ohne Demo-Zugang freigegeben.
            name="warnung: Anmeldung mit Passwort beschrieben, kein Demo-Zugang",
            files={"fastlane/metadata/review_information/notes.txt":
                   "Sign in with your username and password.\n"},
            expect=Status.FAIL,
            expect_finding_contains="Demo-Zugang",
        ),
        SelfTestCase(
            name="nicht gemessen: keine Review Notes",
            files={"config/store/app.json": json.dumps(
                {"locales": {"de-DE": {"subtitle": "x"}}})},
            expect=Status.UNMEASURED,
        ),
    ],
)
def check_review_demo_access(ctx: Context) -> CheckResult:
    """App Review braucht einen befüllten Demo-Zugang, wenn die App eine Anmeldung hat.

    Belegt am 04.10.2026 (App A (macOS)): die Review Notes erklärten, ein
    Demo-Zugang sei nicht möglich (App braucht einen eigenen NAS). Apple
    stoppte das Review nach Guideline 2.1(a) und verlangte einen Zugang mit
    echten Inhalten auf allen Seiten; ein Video reicht ausdrücklich nicht.
    Gemeldet wird, wenn die Notes einen Demo-Zugang ablehnen oder eine
    Anmeldung mit Zugangsdaten beschreiben, ohne dass im Block oder darüber
    ein Demo-Zugang steht. App B (macOS) wurde mit demselben Ablehnungssatz
    freigegeben — schwaches Signal, daher Warnung statt Abbruch.
    """
    check_id = "store.review_demo_access_missing"
    title = "Review Notes ohne Demo-Zugang für App Review"
    records = [r for r in _store_records(ctx) if "reviewNotes" in r["fields"]]
    if not records:
        return unmeasured(check_id, title, "Keine Review Notes gefunden.")
    findings: list[Finding] = []
    for rec in records:
        notes = rec["fields"]["reviewNotes"]
        line = _line_of(rec["text"], notes,
                        rec.get("nth", {}).get("reviewNotes", 0))
        if _DEMO_REFUSED.search(notes):
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=f"Review Notes ({rec['where']}) lehnen einen "
                        "Demo-Zugang ab — hat App Review die Gegenstelle nicht "
                        "selbst, stoppt Apple das Review (2.1(a)).",
                file=rec["file"], line=line,
                fix="Eigenen Review-Benutzer mit echten Inhalten auf einem "
                    "von außen erreichbaren Server anlegen und in App Store "
                    "Connect unter App Review Information eintragen; den "
                    "Ablehnungssatz aus den Notes streichen.",
                guideline="App Review Guidelines 2.1(a)",
            ))
        elif (not rec["demo"] and _SIGN_IN.search(notes)
              and _CREDENTIAL.search(notes)):
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=f"Review Notes ({rec['where']}) beschreiben eine "
                        "Anmeldung mit Zugangsdaten, aber kein Demo-Zugang "
                        "ist hinterlegt.",
                file=rec["file"], line=line,
                fix="Demo-Zugang hinterlegen (fastlane demo_user.txt bzw. "
                    "ein demo*-Feld im Store-Profil, Passwort aus einer "
                    "Secret-Datei) oder in den Notes erklären, dass die "
                    "Anmeldung optional ist.",
                guideline="App Review Guidelines 2.1(a)",
            ))
    return result_for(check_id, title, findings, len(records), "Review Notes")
