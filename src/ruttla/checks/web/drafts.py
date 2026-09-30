"""Bounded advisory for volatile React textarea drafts."""
from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, strip_comments, unmeasured,
)


@register(
    "web.textarea_draft_memory_only",
    "React-Textentwurf ohne erkennbaren Speicher- und Wiederherstellungspfad",
    platform="web", severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md — Entwurfswiederherstellung",
    references=["https://developer.chrome.com/docs/web-platform/page-lifecycle-api",
                "https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage"],
    rationale=(
        "React useState überlebt kein Reload oder Verwerfen eines Hintergrund-Tabs. "
        "Der Check erkennt direkt mit useState verwaltete, editierbare Textareas und "
        "prüft für genau ihren Zustand sichtbare Web-Storage-Lese- und Schreibpfade. "
        "Indirekte Hooks, IndexedDB, Serverentwürfe und deren Laufzeitqualität bleiben "
        "ungemessen. Advisory: kurzfristige Textfelder können bewusst flüchtig sein. "
        "Nicht automatisch sensible Daten speichern; Umfang und Löschung abstimmen."
    ),
    self_tests=[
        SelfTestCase(name="gesund: derselbe Entwurf wird gelesen und geschrieben", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(() => sessionStorage.getItem('draft') || '');\n"
            "useEffect(() => sessionStorage.setItem('draft', draft), [draft]);\n"
            "return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.PASS),
        SelfTestCase(name="gesund: nur lesende Anzeige", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(''); return <textarea readOnly value={draft} />;"}, expect=Status.UNMEASURED),
        SelfTestCase(name="defekt: Texteingabe nur im RAM", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(''); return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: nur Speichern reicht nicht", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(''); sessionStorage.setItem('draft', draft); "
            "return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: nur Wiederherstellen reicht nicht", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(() => localStorage.getItem('draft') || ''); "
            "return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: anderes Feld gespeichert", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(''); const theme = localStorage.getItem('theme'); "
            "localStorage.setItem('theme', theme); return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: Kommentar ist keine Sicherung", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(''); // sessionStorage.getItem('draft'); sessionStorage.setItem('draft', draft)\n"
            "return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.FAIL),
        SelfTestCase(name="indirekter Hook bleibt ungemessen", files={
            "src/Form.tsx": "const [draft, setDraft] = useDeviceDraft(); return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.UNMEASURED),
        SelfTestCase(name="defekt: verschiedene Speicherschlüssel", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(() => sessionStorage.getItem('old') || ''); "
            "sessionStorage.setItem('new', draft); return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: verschiedene Speicherarten", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(() => sessionStorage.getItem('draft') || ''); "
            "localStorage.setItem('draft', draft); return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.FAIL),
        SelfTestCase(name="IndexedDB-Wiederherstellung bleibt ungemessen", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(''); const db = indexedDB.open('drafts'); "
            "return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.UNMEASURED),
        SelfTestCase(name="gesund: JSON String roundtrip", files={
            "src/Form.tsx": "const [draft, setDraft] = useState(() => JSON.parse(localStorage.getItem('draft') || '\"\"')); "
            "localStorage.setItem('draft', JSON.stringify(draft)); return <textarea value={draft} onChange={e => setDraft(e.target.value)} />;"}, expect=Status.PASS),
    ],
)
def check_textarea_draft_memory_only(ctx: Context) -> CheckResult:
    title = "React-Textentwurf ohne erkennbaren Speicher- und Wiederherstellungspfad"
    check_id = "web.textarea_draft_memory_only"
    findings = []
    units = 0
    declaration = re.compile(r"\bconst\s*\[\s*(\w+)\s*,\s*(\w+)\s*\]\s*=\s*(?:React\.)?useState(?:<[^;=]+>)?\s*\(")
    textarea = re.compile(r"<textarea\b[\s\S]*?\s*/?>")
    for sf in ctx.files(".tsx", ".jsx"):
        code = strip_comments(sf.text, sf.ext)
        if re.search(r"\bindexedDB\s*\.", code):
            continue  # An asynchronous storage flow requires a browser gate.
        for field in textarea.finditer(code):
            tag = field.group()
            if re.search(r"\breadOnly\b", tag) or not re.search(r"\bonChange\s*=", tag):
                continue
            binding = re.search(r"\bvalue\s*=\s*\{\s*(\w+)\s*\}", tag)
            if not binding:
                continue
            name = binding.group(1)
            state = next((d for d in declaration.finditer(code) if d.group(1) == name), None)
            if not state:
                continue
            units += 1
            # Only match a literal storage key restored inside this initializer.
            # A custom loader cannot be proven by this bounded static check.
            initializer_end = code.find(';', state.end())
            initializer = code[state.end():initializer_end if initializer_end >= 0 else field.start()]
            reads = re.findall(r"\b(sessionStorage|localStorage)\.getItem\(\s*(['\"])([^'\"]+)\2\s*\)", initializer)
            serialized = bool(re.search(r"\bJSON\.parse\(", initializer))
            value = rf"JSON\.stringify\(\s*{re.escape(name)}\s*\)" if serialized else re.escape(name)
            persisted = any(re.search(
                rf"\b{store}\.setItem\(\s*(['\"]){re.escape(key)}\1\s*,\s*{value}\s*\)", code)
                for store, _, key in reads)
            if not persisted:
                findings.append(Finding(check_id=check_id, severity=Severity.WARNING,
                    message=f"Textarea-Zustand '{name}' hat keinen belegten lokalen Lese- und Schreibpfad; Reload kann Eingaben verlieren.",
                    file=sf.rel, line=sf.line_of(field.start()),
                    fix="Entwurfsumfang und Datenschutz klären; Save und Restore samt Reload/Hintergrundwechsel im echten Browser prüfen. Indirekte Speicherpfade separat validieren."))
    if not units:
        return unmeasured(check_id, title, "Keine direkt mit useState verwaltete editierbare Textarea gefunden. Indirekte Speicherpfade sind nicht gemessen.", "web")
    return result_for(check_id, title, findings, units, "direkte Textarea-Zustände", "web")
