"""Apple: Swift concurrency and SwiftData predicate traps.

Split from the original checks/apple.py; background and
shared helpers in _common.py.
"""

from __future__ import annotations

import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    register,
    result_for,
    SelfTestCase,
    Severity,
    snippet,
    Status,
    strip_comments,
    unmeasured,
)

from ._common import PLATFORM


# ===========================================================================
# Swift-Concurrency
# ===========================================================================

@register(
    "apple.mainactor_missing_on_observable",
    "ObservableObject/@Observable ohne @MainActor",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="guides/swift-concurrency.md",
    self_tests=[
        SelfTestCase(
            name="ViewModel ohne MainActor",
            files={"App/VM.swift": "import SwiftUI\nfinal class VM: ObservableObject {\n  @Published var x = 0\n}\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="ViewModel mit MainActor",
            files={"App/VM.swift": "import SwiftUI\n@MainActor\nfinal class VM: ObservableObject {\n  @Published var x = 0\n}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_mainactor(ctx: Context) -> CheckResult:
    """Ein ObservableObject treibt die Oberfläche. Ohne @MainActor ist jede
    Zuweisung aus einem Task ein Datenrennen — unter Swift 6 ein Fehler."""
    title = "ObservableObject/@Observable ohne @MainActor"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.mainactor_missing_on_observable", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    decl = re.compile(
        r"^[ \t]*(?:public\s+|internal\s+|final\s+|open\s+)*class\s+(\w+)\s*:\s*[^{]*\bObservableObject\b",
        re.MULTILINE,
    )
    observable_macro = re.compile(r"^[ \t]*@Observable[ \t]*$", re.MULTILINE)
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for m in decl.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            window = "\n".join(lines[max(0, line_no - 5): line_no])
            if "@MainActor" in window:
                continue
            findings.append(Finding(
                check_id="apple.mainactor_missing_on_observable",
                severity=Severity.WARNING,
                message=f"'{m.group(1)}' ist ObservableObject ohne @MainActor.",
                file=sf.rel, line=line_no, evidence=snippet(m.group(0)),
                fix="@MainActor vor die Klasse setzen — sonst ist jede Zuweisung "
                    "aus einem Task ein Datenrennen.",
                guideline="guides/swift-concurrency.md",
            ))
        for m in observable_macro.finditer(body):
            line_no = body.count("\n", 0, m.start()) + 1
            nxt = "\n".join(lines[line_no: line_no + 3])
            window = "\n".join(lines[max(0, line_no - 4): line_no])
            if "class" not in nxt or "@MainActor" in window or "@MainActor" in nxt:
                continue
            findings.append(Finding(
                check_id="apple.mainactor_missing_on_observable",
                severity=Severity.WARNING,
                message="@Observable-Klasse ohne @MainActor.",
                file=sf.rel, line=line_no, evidence=snippet(nxt.splitlines()[0] if nxt else ""),
                fix="@MainActor ergänzen.",
                guideline="guides/swift-concurrency.md",
            ))
    return result_for("apple.mainactor_missing_on_observable", title, findings,
                      len(swift), "Swift-Dateien", PLATFORM)


_OBS_CLASS = re.compile(
    r"^[ \t]*(?:@Observable[ \t]*\n[ \t]*)?(?:@\w+(?:\([^)]*\))?[ \t]*\n[ \t]*)*"
    r"(?:(?:public|internal|package|final|open)\s+)*class\s+(\w+)\b[^{]*\{",
    re.MULTILINE,
)
_STORED_VAR = re.compile(r"^[ \t]*(?:@\w+[ \t]+)*(?:(?:public|private|fileprivate|internal|package|open)(?:\(set\))?\s+)*var\s+(\w+)", re.MULTILINE)
_ASYNC_FUNC = re.compile(r"\bfunc\s+\w+\s*(?:<[^>]*>)?\s*\([^{]*?\)\s*async\b[^{]*\{")


def _block_end(text: str, open_idx: int) -> int:
    """Index der schließenden Klammer zur geschweiften Klammer bei open_idx."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text)


def _top_level(body: str) -> str:
    """Nur die Zeichen auf Klassenebene; verschachtelte Blöcke werden zu Leerzeichen."""
    out, depth = [], 0
    for ch in body:
        if ch == "{":
            depth += 1
        out.append(ch if depth == 0 or ch == "\n" else " ")
        if ch == "}":
            depth -= 1
    return "".join(out)


@register(
    "apple.observable_state_mutated_off_main",
    "Beobachteter Zustand wird nach await außerhalb des Main Threads gesetzt",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline="guides/swift-concurrency.md",
    safe_by_default=True,
    self_tests=[
        SelfTestCase(
            name="negativ: @Observable ohne MainActor setzt nach await",
            files={"App/Store.swift": "import Observation\n@Observable\npublic final class Store {\n"
                   "  public var items: [Int] = []\n"
                   "  public func refresh() async {\n    let list = await load()\n"
                   "    self.items = list\n  }\n  func load() async -> [Int] { [] }\n}\n"},
            expect=Status.FAIL,
            expect_finding_contains="items",
        ),
        SelfTestCase(
            name="gesund: Klasse ist @MainActor",
            files={"App/Store.swift": "import Observation\n@MainActor\n@Observable\npublic final class Store {\n"
                   "  public var items: [Int] = []\n"
                   "  public func refresh() async {\n    let list = await load()\n"
                   "    self.items = list\n  }\n  func load() async -> [Int] { [] }\n}\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: Zuweisung vor dem await, lokale Variable danach",
            files={"App/VM.swift": "import SwiftUI\nfinal class VM: ObservableObject {\n"
                   "  @Published var busy = false\n"
                   "  func run() async {\n    busy = true\n    var busy = await work()\n"
                   "    busy = !busy\n  }\n  func work() async -> Bool { true }\n}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_observable_mutated_off_main(ctx: Context) -> CheckResult:
    """Eine async-Methode einer nicht isolierten Klasse läuft nach jedem await
    auf dem globalen Executor. Setzt sie dort beobachteten Zustand, invalidiert
    SwiftUI Views außerhalb des Main Threads — AppKit bricht dann sporadisch mit
    'Update Constraints in Window' ab (Beleg 2026-09-28). Der Compiler meldet
    das bei '@unchecked Sendable' nicht, auch nicht im Swift-6-Modus."""
    title = "Beobachteter Zustand wird nach await außerhalb des Main Threads gesetzt"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.observable_state_mutated_off_main", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    findings: list[Finding] = []
    measured = 0
    for sf in swift:
        text = strip_comments(sf.text, sf.ext)
        for m in _OBS_CLASS.finditer(text):
            head = m.group(0)
            prefix = text[max(0, m.start() - 200):m.start()].splitlines()[-2:]
            observable = "@Observable" in head or re.search(r"\bObservableObject\b", head)
            if not observable:
                continue
            measured += 1
            if "@MainActor" in head or any("@MainActor" in ln for ln in prefix):
                continue
            open_idx = m.end() - 1
            body = text[open_idx + 1:_block_end(text, open_idx)]
            stored = set(_STORED_VAR.findall(_top_level(body)))
            if not stored:
                continue
            for fm in _ASYNC_FUNC.finditer(body):
                before = body[max(0, fm.start() - 80):fm.start()].splitlines()
                if before and "@MainActor" in before[-1]:
                    continue
                fopen = fm.end() - 1
                fbody = body[fopen + 1:_block_end(body, fopen)]
                if "MainActor.run" in fbody:
                    continue
                first_await = fbody.find("await ")
                if first_await < 0:
                    continue
                tail = fbody[first_await:]
                shadowed = set(re.findall(r"\b(?:let|var)\s+(\w+)", fbody))
                hit = None
                for am in re.finditer(r"(?<![\w.])(self\.)?(\w+)\s*(?:\+=|-=|=)(?!=)", tail):
                    name = am.group(2)
                    if name not in stored:
                        continue
                    if not am.group(1) and name in shadowed:
                        continue
                    pre = tail[max(0, am.start() - 12):am.start()]
                    if re.search(r"\b(?:let|var|case)\s+$", pre):
                        continue
                    hit = (name, am)
                    break
                if not hit:
                    continue
                abs_pos = open_idx + 1 + fopen + 1 + first_await + hit[1].start()
                line_no = text.count("\n", 0, abs_pos) + 1
                findings.append(Finding(
                    check_id="apple.observable_state_mutated_off_main",
                    severity=Severity.ERROR,
                    message=f"'{m.group(1)}' setzt '{hit[0]}' nach einem await ohne "
                            "Main-Actor-Isolation — die View-Aktualisierung läuft "
                            "auf einem Hintergrund-Thread.",
                    file=sf.rel, line=line_no, evidence=snippet(hit[1].group(0)),
                    fix="@MainActor vor die Klasse setzen (Netzwerk-/Datenträgerarbeit "
                        "bleibt in eigenen, nicht isolierten Typen).",
                    guideline="guides/swift-concurrency.md",
                ))
    if measured == 0:
        return unmeasured("apple.observable_state_mutated_off_main", title,
                          "Keine ObservableObject-/@Observable-Klasse gefunden.", PLATFORM)
    return result_for("apple.observable_state_mutated_off_main", title, findings,
                      measured, "beobachtete Klassen", PLATFORM)


@register(
    "apple.ui_update_off_main",
    "UI-Zustand wird aus einem Hintergrund-Kontext gesetzt",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="guides/swift-concurrency.md",
    self_tests=[
        SelfTestCase(
            name="Zustand im detached Task",
            files={"App/VM.swift": "import Foundation\nfunc load() {\n  Task.detached {\n    isLoading = false\n  }\n}\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Zustand ueber MainActor",
            files={"App/VM.swift": "import Foundation\nfunc load() {\n  Task.detached {\n    await MainActor.run { isLoading = false }\n  }\n}\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_ui_off_main(ctx: Context) -> CheckResult:
    title = "UI-Zustand wird aus einem Hintergrund-Kontext gesetzt"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.ui_update_off_main", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    detached = re.compile(r"Task\.detached\s*\{|DispatchQueue\.global\(")
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        lines = body.splitlines()
        for m in detached.finditer(body):
            start_line = body.count("\n", 0, m.start()) + 1
            block = lines[start_line - 1: start_line + 25]
            for off, raw in enumerate(block):
                if re.search(r"^\s*(self\.)?\w*(isLoading|error|items|state|text|"
                             r"progress|selected|show\w*)\s*=", raw):
                    if "await MainActor" in "\n".join(block[:off + 1]):
                        continue
                    findings.append(Finding(
                        check_id="apple.ui_update_off_main",
                        severity=Severity.WARNING,
                        message="Zustandszuweisung in einem detached/global-Kontext.",
                        file=sf.rel, line=start_line + off, evidence=snippet(raw),
                        fix="Die Zuweisung in 'await MainActor.run { }' legen oder "
                            "den umgebenden Typ @MainActor machen.",
                        guideline="guides/swift-concurrency.md",
                    ))
                    break
    return result_for("apple.ui_update_off_main", title, findings, len(swift),
                      "Swift-Dateien", PLATFORM)


@register(
    "apple.swiftdata_predicate_capture",
    "SwiftData-#Predicate greift auf eine nicht gebundene Variable zu",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="guides/swiftdata-predicate.md",
    self_tests=[
        SelfTestCase(
            name="self im Predicate",
            files={"App/Q.swift": "import SwiftData\nlet p = #Predicate<Item> { $0.owner == self.userId }\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="lokale Konstante",
            files={"App/Q.swift": "import SwiftData\nlet uid = userId\nlet p = #Predicate<Item> { $0.owner == uid }\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_predicate(ctx: Context) -> CheckResult:
    """#Predicate wird zu SQL übersetzt — ein direkter Zugriff auf eine
    Instanzeigenschaft oder ein Enum bricht zur Laufzeit, nicht beim Bauen."""
    title = "SwiftData-#Predicate greift auf eine nicht gebundene Variable zu"
    swift = ctx.files(".swift")
    if not swift:
        return unmeasured("apple.swiftdata_predicate_capture", title,
                          "Keine Swift-Dateien gefunden.", PLATFORM)
    measured = 0
    findings: list[Finding] = []
    for sf in swift:
        body = strip_comments(sf.text, sf.ext)
        for m in re.finditer(r"#Predicate\s*<[^>]*>\s*\{([^}]{0,600})\}", body):
            measured += 1
            block = m.group(1)
            line_no = body.count("\n", 0, m.start()) + 1
            if re.search(r"\bself\.\w+", block):
                findings.append(Finding(
                    check_id="apple.swiftdata_predicate_capture",
                    severity=Severity.WARNING,
                    message="#Predicate greift direkt auf 'self.…' zu.",
                    file=sf.rel, line=line_no, evidence=snippet(block),
                    fix="Wert vorher in eine lokale Konstante legen und die "
                        "verwenden — #Predicate wird zu SQL übersetzt.",
                    guideline="guides/swiftdata-predicate.md",
                ))
    if measured == 0:
        return unmeasured("apple.swiftdata_predicate_capture", title,
                          "Kein #Predicate im Projekt.", PLATFORM)
    return result_for("apple.swiftdata_predicate_capture", title, findings,
                      measured, "#Predicate-Blöcke", PLATFORM)
