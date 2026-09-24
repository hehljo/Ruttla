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
        r"^\s*(?:public\s+|internal\s+|final\s+|open\s+)*class\s+(\w+)\s*:\s*[^{]*\bObservableObject\b",
        re.MULTILINE,
    )
    observable_macro = re.compile(r"^\s*@Observable\s*$", re.MULTILINE)
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
