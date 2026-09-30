"""SQL-Skripte: PL/pgSQL-Syntax außerhalb eines Blocks."""
from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase,
    register, result_for, snippet, unmeasured,
)

_DOLLAR_TAG = re.compile(r"\$([A-Za-z_]\w*)?\$")
_EXCEPTION = re.compile(r"\bexception\s+when\b", re.IGNORECASE)


def _mask_sql(text: str) -> str:
    """Ersetzt Kommentare, Zeichenketten und $$-Rümpfe durch Leerzeichen.

    Zeilenumbrüche bleiben stehen, damit Offsets auf dieselbe Zeile zeigen.
    Was danach übrig bleibt, ist nacktes SQL — genau der Teil, den psql
    Anweisung für Anweisung an den Server schickt.
    """
    out = list(text)
    i, n = 0, len(text)

    def blank(start: int, stop: int) -> None:
        for k in range(start, min(stop, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        if text.startswith("--", i):
            stop = text.find("\n", i)
            stop = n if stop == -1 else stop
            blank(i, stop)
            i = stop
            continue
        if text.startswith("/*", i):
            stop = text.find("*/", i + 2)
            stop = n if stop == -1 else stop + 2
            blank(i, stop)
            i = stop
            continue
        if text[i] == "'":
            j = i + 1
            while j < n:
                if text[j] == "'" and text.startswith("''", j):
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            blank(i, j + 1)
            i = j + 1
            continue
        m = _DOLLAR_TAG.match(text, i)
        if m:
            tag = m.group(0)
            stop = text.find(tag, m.end())
            stop = n if stop == -1 else stop + len(tag)
            blank(i, stop)
            i = stop
            continue
        i += 1
    return "".join(out)


@register(
    "sql.plpgsql_outside_block",
    "PL/pgSQL-Fehlerbehandlung als nacktes SQL",
    severity=Severity.ERROR,
    safe_by_default=True,
    guideline="CLAUDE.md § Gates — 'Ein Prüfstand, dessen Testfall den Fall gar nicht herstellt'",
    rationale=(
        "begin … exception when … end gibt es nur innerhalb von PL/pgSQL "
        "(DO-Block oder Funktionsrumpf). Als nacktes SQL ist es ein "
        "Syntaxfehler: psql meldet ERROR und läuft weiter. In einem Testskript "
        "sieht das aus wie ein erwarteter Fehler — der Umgehungsversuch darin "
        "wurde aber nie ausgeführt. Belegt am 30.09.2026: ein Test, der ein "
        "Ergebnisfoto zum Produktfoto umschreiben wollte, lief nie; repariert "
        "wurde er sofort rot und deckte eine echte Lücke auf. Gemessen wird "
        "nur in PostgreSQL-Projekten: in Oracle-PL/SQL ist derselbe Text "
        "außerhalb von $$ gültig."
    ),
    self_tests=[
        SelfTestCase(
            name="defekt: exception-Block als nacktes SQL",
            files={"supabase/tests/umgehung.sql":
                   "begin;\n  begin\n    update t set a = 1;\n"
                   "  exception when others then\n    null;\n  end;\nrollback;\n",
                   "supabase/migrations/001.sql":
                   "create function f() returns void language plpgsql as $$ begin end $$;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Oracle-PL/SQL ohne PostgreSQL-Merkmal bleibt ungemessen",
            files={"db/proc.sql":
                   "BEGIN\n  UPDATE t SET a = 1;\nEXCEPTION WHEN OTHERS THEN\n  NULL;\nEND;\n/\n"},
            expect=Status.UNMEASURED,
        ),
        SelfTestCase(
            name="gesund: derselbe Versuch im DO-Block",
            files={"tests/umgehung.sql":
                   "begin;\n  do $$\n  begin\n    update t set a = 1;\n"
                   "  exception when others then\n    null;\n  end $$;\nrollback;\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: Funktionsrumpf mit eigenem Tag",
            files={"migrations/001.sql":
                   "create function f() returns void language plpgsql as $body$\n"
                   "begin perform 1; exception when others then null; end;\n$body$;\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: Erwähnung in Kommentar und Zeichenkette",
            files={"tests/a.sql":
                   "-- exception when others gibt es nur in PL/pgSQL\n"
                   "select 'exception when' as text;\n"
                   "do $$ begin perform 1; end $$;\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_plpgsql_outside_block(ctx: Context) -> CheckResult:
    title = "PL/pgSQL-Fehlerbehandlung als nacktes SQL"
    files = ctx.files(".sql")
    if not files:
        return unmeasured("sql.plpgsql_outside_block", title,
                          "Keine SQL-Dateien gefunden.")
    # PostgreSQL erkennt man an seiner eigenen Syntax, nicht am Ordner.
    if not any(re.search(r"\$\w*\$|\bplpgsql\b", sf.text, re.I) for sf in files):
        return unmeasured("sql.plpgsql_outside_block", title,
                          "Kein PostgreSQL erkannt ($$-Rumpf oder plpgsql) — in "
                          "anderen Dialekten ist 'exception when' gültig.")
    findings: list[Finding] = []
    for sf in files:
        masked = _mask_sql(sf.text)
        for m in _EXCEPTION.finditer(masked):
            line = sf.line_of(m.start())
            findings.append(Finding(
                check_id="sql.plpgsql_outside_block", severity=Severity.ERROR,
                message="'exception when' außerhalb eines DO-Blocks oder "
                        "Funktionsrumpfs — Syntaxfehler, der Block läuft nie.",
                file=sf.rel, line=line, evidence=snippet(sf.lines[line - 1]),
                fix="In `do $$ begin … exception when … then … end $$;` "
                    "einschließen und danach den Zustand prüfen, den der "
                    "Versuch herstellen wollte.",
                guideline="CLAUDE.md § Gates",
            ))
    return result_for("sql.plpgsql_outside_block", title, findings, len(files),
                      "SQL-Dateien")
