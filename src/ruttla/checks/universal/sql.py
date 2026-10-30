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
    Anweisung für Anweisung an den Server schickt. Lexik nach PostgreSQL
    (sql-syntax-lexical): /* */ verschachtelt, E'' mit Backslash-Escapes,
    "quoted identifiers" wie Zeichenketten.
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
            depth, stop = 1, i + 2
            while stop < n and depth:
                if text.startswith("/*", stop):
                    depth, stop = depth + 1, stop + 2
                elif text.startswith("*/", stop):
                    depth, stop = depth - 1, stop + 2
                else:
                    stop += 1
            blank(i, stop)
            i = stop
            continue
        if text[i] in "'\"":
            quote = text[i]
            escape = (quote == "'" and i > 0 and text[i - 1] in "Ee"
                      and (i < 2 or not (text[i - 2].isalnum() or text[i - 2] == "_")))
            j = i + 1
            while j < n:
                if escape and text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote and text.startswith(quote * 2, j):
                    j += 2
                    continue
                if text[j] == quote:
                    break
                j += 1
            blank(i, j + 1)
            i = j + 1
            continue
        m = _DOLLAR_TAG.match(text, i) if not (i and (text[i - 1].isalnum() or text[i - 1] == "_")) else None
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


# --- Supabase-CLI-Migrationen ------------------------------------------------
# Python statt TOML-Regel: die Transaktionspruefung braucht die SQL-Lexik
# (verschachtelte Kommentare, E-Strings, Dollar-Quotes) und Anweisungsgrenzen,
# die Namenspruefung Zustand ueber mehrere Dateien (doppelte Versionen).
_MIG_DIR = "supabase/migrations/"
_MIG_NAME = re.compile(r"^([0-9]+)_.+\.sql$")
_TX_ONE = {"BEGIN", "COMMIT", "END", "ROLLBACK", "ABORT", "SAVEPOINT", "RELEASE"}
_TX_TWO = {("START", "TRANSACTION"), ("PREPARE", "TRANSACTION")}


def _migration_files(ctx: Context):
    return [sf for sf in ctx.files(".sql") if _MIG_DIR in "/" + sf.rel.replace("\\", "/")]


@register(
    "sql.migration_transaction_control",
    "Supabase-Migration steuert die Transaktion selbst",
    severity=Severity.ERROR,
    safe_by_default=True,
    guideline="~/.claude/guides/supabase-deploy.md § Handgepflegte Kette auf die CLI umstellen",
    rationale=(
        "supabase db reset/push fasst jede Migrationsdatei in EINE Transaktion "
        "und schreibt danach den Historieneintrag. Ein eigenes COMMIT/ABORT "
        "beendet sie mittendrin: ein späterer Fehler hinterlässt einen halben "
        "Stand ohne Historieneintrag, ein ABORT rollt still zurück und die "
        "Version steht trotzdem als eingespielt in der Historie. Belegt am "
        "19.10.2026 (Vylea): 32 von 114 Migrationen trugen BEGIN/COMMIT aus der "
        "Zeit, als sie von Hand im SQL-Editor liefen. Gemessen wird nur auf "
        "oberster Ebene — BEGIN/END in $$-Rümpfen und DO-Blöcken sind PL/pgSQL."
    ),
    self_tests=[
        SelfTestCase(
            name="defekt: COMMIT mitten in der Migration",
            files={"supabase/migrations/001_a.sql": "create table a (i int);\ncommit;\nselect 1;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="defekt: ABORT nach verschachteltem Kommentar und E-String",
            files={"supabase/migrations/001_a.sql":
                   "/* a /* b */ c */ select E'it\\'s';\nABORT;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="defekt: START mit Kommentar vor TRANSACTION",
            files={"supabase/migrations/001_a.sql": "START/*x*/TRANSACTION;\nselect 1;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="gesund: BEGIN/END/COMMIT nur in Rümpfen, Strings, Bezeichnern",
            files={"supabase/migrations/001_a.sql":
                   "create function f() returns void language plpgsql as $body1$\n"
                   "begin perform 1; end;\n$body1$;\n"
                   "do $$ begin raise notice 'x'; end $$;\n"
                   "select 'commit;' as \"x;commit;y\";\n-- commit;\n"},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="gesund: Testskript ausserhalb der Migrationen darf begin/rollback",
            files={"supabase/tests/t.sql": "begin;\nselect 1;\nrollback;\n",
                   "supabase/migrations/001_a.sql": "select 1;\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_migration_transaction_control(ctx: Context) -> CheckResult:
    cid, title = "sql.migration_transaction_control", "Supabase-Migration steuert die Transaktion selbst"
    files = _migration_files(ctx)
    if not files:
        return unmeasured(cid, title, "Keine Datei unter supabase/migrations/ gefunden.")
    findings: list[Finding] = []
    for sf in files:
        masked = _mask_sql(sf.text)
        start = 0
        for stmt in re.finditer(r"[^;]*;?", masked):
            words = re.findall(r"[A-Za-z_]+", stmt.group(0).upper())[:2]
            cmd = words[0] if words and words[0] in _TX_ONE else (
                " ".join(words) if tuple(words) in _TX_TWO else None)
            if cmd:
                pos = stmt.start() + len(stmt.group(0)) - len(stmt.group(0).lstrip())
                line = sf.line_of(pos)
                findings.append(Finding(
                    check_id=cid, severity=Severity.ERROR,
                    message=f"{cmd} auf oberster Ebene — die CLI-Transaktion je Datei wird aufgeteilt.",
                    file=sf.rel, line=line, evidence=snippet(sf.lines[line - 1]),
                    fix="Anweisung entfernen; die Supabase-CLI fasst die Datei selbst in eine Transaktion.",
                    guideline="~/.claude/guides/supabase-deploy.md",
                ))
            start = stmt.end()
    return result_for(cid, title, findings, len(files), "Migrationsdateien")


@register(
    "sql.migration_name_not_cli",
    "Supabase-Migration wird von der CLI übersprungen oder kollidiert",
    severity=Severity.ERROR,
    safe_by_default=True,
    guideline="~/.claude/guides/supabase-deploy.md § Handgepflegte Kette auf die CLI umstellen",
    rationale=(
        "Die Supabase-CLI nimmt nur <ziffern>_name.sql; alles andere (048b_…, "
        "DIAG_…, VERIFY.sql) überspringt sie still — live fehlt die Änderung, "
        "lokal mit psql lief sie. Zwei Dateien mit derselben Version brechen "
        "die Migrationshistorie. Belegt am 19.10.2026 (Vylea): 008 und 045/048/095 "
        "doppelt, 048b/048c übersprungen, Diagnoseskripte im Migrationsordner."
    ),
    self_tests=[
        SelfTestCase(
            name="defekt: Buchstabe in der Version",
            files={"supabase/migrations/048b_x.sql": "select 1;\n",
                   "supabase/migrations/048_y.sql": "select 1;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="defekt: doppelte Version",
            files={"supabase/migrations/008_a.sql": "select 1;\n",
                   "supabase/migrations/008_b.sql": "select 1;\n"},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="gesund: eindeutige numerische Versionen",
            files={"supabase/migrations/001_a.sql": "select 1;\n",
                   "supabase/migrations/20261019000000_b.sql": "select 1;\n"},
            expect=Status.PASS,
        ),
    ],
)
def check_migration_name_not_cli(ctx: Context) -> CheckResult:
    cid, title = "sql.migration_name_not_cli", "Supabase-Migration wird von der CLI übersprungen oder kollidiert"
    files = _migration_files(ctx)
    if not files:
        return unmeasured(cid, title, "Keine Datei unter supabase/migrations/ gefunden.")
    findings: list[Finding] = []
    versions: dict[str, list] = {}
    for sf in files:
        name = sf.rel.replace("\\", "/").rsplit("/", 1)[-1]
        m = _MIG_NAME.match(name)
        if not m:
            findings.append(Finding(
                check_id=cid, severity=Severity.ERROR,
                message=f"{name}: kein CLI-Migrationsname — supabase db push/reset überspringt die Datei still.",
                file=sf.rel, line=1, evidence=name,
                fix="Eindeutige numerische Version vergeben oder (Diagnose/Prüfung) aus supabase/migrations/ verschieben.",
                guideline="~/.claude/guides/supabase-deploy.md",
            ))
            continue
        versions.setdefault(m.group(1), []).append(sf)
    for v, sfs in versions.items():
        for sf in sfs[1:]:
            findings.append(Finding(
                check_id=cid, severity=Severity.ERROR,
                message=f"Version {v} mehrfach ({len(sfs)} Dateien) — die CLI-Historie kennt jede Version nur einmal.",
                file=sf.rel, line=1, evidence=sf.rel.rsplit("/", 1)[-1],
                fix="Eine der Dateien umnummerieren oder zusammenführen.",
                guideline="~/.claude/guides/supabase-deploy.md",
            ))
    return result_for(cid, title, findings, len(files), "Migrationsdateien")
