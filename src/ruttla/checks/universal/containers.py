"""Universal: Wegwerf-Container räumen ihre anonymen Volumes mit weg.

Belegt am 01.10.2026: auf dem VPS lagen 306 verwaiste anonyme Docker-Volumes
(je 40,9 MB, eine frisch initialisierte Postgres-Datenbank), 302 davon aus dem
September. Ursache: Test-Skripte starteten `postgres` per `docker run -d`
ohne `--rm` und räumten mit `docker rm -f` auf — ohne `-v`. Das Postgres-Image
deklariert `VOLUME /var/lib/postgresql/data`; ohne `-v` bleibt das anonyme
Volume bei jedem Lauf liegen.
"""

from __future__ import annotations

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
    snippet,
    Status,
    unmeasured,
)

CHECK_ID = "gate.container_leaks_anonymous_volume"
GUIDELINE = "CLAUDE.md § Gates"

# Images, deren Dockerfile ein VOLUME deklariert. Nur für die entsteht beim
# Start ein anonymes Volume — bei allen anderen ist `docker rm` ohne `-v`
# harmlos und darf nicht rot werden.
_VOLUME_IMAGE = re.compile(
    r"(?:^|\s)(?:[\w.-]+(?::\d+)?/)*"
    r"(postgres|postgis|mysql|mariadb|mongo|redis|elasticsearch|clickhouse-server)"
    r"(?::[\w.-]+)?(?=\s|$)"
)
_RUN = re.compile(r"\bdocker\s+(?:container\s+)?(?:run|create)\b")
_RM = re.compile(r"\bdocker\s+(?:container\s+)?rm\b([^;|&\n'\")]*)")
_RM_WITH_VOLUMES = re.compile(r"(?:^|\s)(?:-[a-zA-Z]*v[a-zA-Z]*|--volumes)(?=\s|$)")
_VOLUME_CLEANUP = re.compile(r"\bdocker\s+volume\s+(?:rm|prune)\b")


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Fortsetzungszeilen (`\\` am Ende) zusammenfügen, Kommentare entfernen."""
    out: list[tuple[int, str]] = []
    buf, start = "", 0
    for idx, raw in enumerate(text.splitlines(), start=1):
        code = raw.split("#", 1)[0] if not raw.lstrip().startswith("#!") else ""
        if not buf:
            start = idx
        if code.rstrip().endswith("\\"):
            buf += code.rstrip()[:-1] + " "
            continue
        out.append((start, buf + code))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


_PG = "docker run -d --name $C -e POSTGRES_PASSWORD=test postgres:17 >/dev/null\n"


@register(
    CHECK_ID,
    "Wegwerf-Container hinterlässt sein anonymes Volume",
    severity=Severity.ERROR,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(name="gesund: --rm", files={
            "t.sh": "docker run --rm -d --name $C postgres:17\n"}, expect=Status.PASS),
        SelfTestCase(name="gesund: rm -fv im trap", files={
            "t.sh": "trap 'docker rm -fv $C >/dev/null 2>&1' EXIT\n" + _PG}, expect=Status.PASS),
        SelfTestCase(name="gesund: rm --volumes", files={
            "t.sh": _PG + "docker rm -f --volumes \"$C\"\n"}, expect=Status.PASS),
        SelfTestCase(name="gesund: volume prune", files={
            "t.sh": _PG + "docker rm -f $C\ndocker volume prune -f\n"}, expect=Status.PASS),
        SelfTestCase(name="gesund: Image ohne VOLUME neben sauberem Postgres", files={
            "a.sh": "docker run -d --name web nginx:1.27\ndocker rm -f web\n",
            "b.sh": "docker run --rm postgres:15\n"}, expect=Status.PASS),
        SelfTestCase(name="defekt: Originalfall test-migrations.sh", files={
            "t.sh": "trap 'docker rm -f $C >/dev/null 2>&1' EXIT\n" + _PG}, expect=Status.FAIL),
        SelfTestCase(name="defekt: mehrzeiliger run mit Registry-Pfad", files={
            "t.sh": "docker run -d \\\n  --name db \\\n  public.ecr.aws/supabase/postgres:17.6\n"
                    "docker rm -f db\n"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: gar kein Aufräumen", files={
            "t.sh": "docker run -d --name db mysql:8\n"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: -v nur im Kommentar", files={
            "t.sh": _PG + "docker rm -f $C  # TODO docker rm -v\n"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: -v nur im Containernamen", files={
            "t.sh": "docker run -d --name my-v postgres:17\ndocker rm -f my-v\n"}, expect=Status.FAIL),
        SelfTestCase(name="defekt: --rm nur in einem anderen Aufruf", files={
            "t.sh": "docker run --rm alpine true\n" + _PG}, expect=Status.FAIL),
        SelfTestCase(name="nicht gemessen: kein docker run", files={
            "t.sh": "echo hallo\n"}, expect=Status.UNMEASURED),
        SelfTestCase(name="nicht gemessen: nur Images ohne VOLUME", files={
            "t.sh": "docker run -d --name web nginx\ndocker rm -f web\n"}, expect=Status.UNMEASURED),
    ],
)
def check_container_volume_leak(ctx: Context) -> CheckResult:
    """Prüfgegenstand ist jeder Start eines Images mit VOLUME ohne `--rm`.

    Er ist sauber, wenn dieselbe Datei die Volumes wieder entfernt
    (`docker rm -v`/`--volumes`, `docker volume rm|prune`). Compose-Stacks
    (`docker compose down -v`) sind hier nicht gemessen.
    """
    title = "Wegwerf-Container hinterlässt sein anonymes Volume"
    findings: list[Finding] = []
    units = 0
    for sf in ctx.all_files():
        base = os.path.basename(sf.rel)
        if sf.ext not in (".sh", ".bash", ".zsh") and not base.endswith(("Makefile", "makefile")):
            continue
        lines = _logical_lines(sf.text)
        cleans = any(
            _VOLUME_CLEANUP.search(code)
            or any(_RM_WITH_VOLUMES.search(m.group(1)) for m in _RM.finditer(code))
            for _, code in lines
        )
        for line_no, code in lines:
            m = _RUN.search(code)
            if not m:
                continue
            args = code[m.end():]
            if not _VOLUME_IMAGE.search(args):
                continue
            if re.search(r"(?:^|\s)--rm(?=\s|$)", args):
                units += 1
                continue
            units += 1
            if cleans:
                continue
            image = _VOLUME_IMAGE.search(args).group(1)
            findings.append(Finding(
                check_id=CHECK_ID,
                severity=Severity.ERROR,
                message=f"'{image}' deklariert ein VOLUME; ohne --rm und ohne "
                        "`docker rm -v` bleibt bei jedem Lauf ein anonymes Volume liegen.",
                file=sf.rel, line=line_no, evidence=snippet(sf.lines[line_no - 1]),
                fix="`docker run --rm …` verwenden oder beim Aufräumen "
                    "`docker rm -fv …` statt `docker rm -f …`.",
                guideline=GUIDELINE,
            ))
    if units == 0:
        return unmeasured(CHECK_ID, title,
                          "Kein Start eines Images mit VOLUME in Shell-Skripten gefunden.")
    return result_for(CHECK_ID, title, findings, units)
