"""Statische Checks für langlaufende Python-Dienste (Bots, Scheduler, Datenabrufe).

Belegte Fehlerbilder aus einem Live-Trading-Bot (23.09.2026),
alle code-technisch vermeidbar:

* APScheduler verwirft jeden Job, der mehr als ``misfire_grace_time``
  (Default **1 s**) zu spät dran ist. Ein async-Job, der synchron Minuten
  scannt, blockiert den Event-Loop — Stop-Loss-Check 255× verfallen, bis
  5:42 min. Dasselbe in zwei Schwesterprojekten (177× / 119×).
* Yahoo ``v8/finance/chart`` liefert die letzte XETRA-Tageskerze mit
  ``close=None``. ``dropna`` warf sie weg; EU-Signale rechneten mit dem
  Schluss von vorgestern (Signal 135,18 → Fill 151,54).
* Eine Retry-Schleife wiederholte auch ``POST /orders`` nach einem Timeout —
  eine mögliche Doppelorder.
* ``ecb_eurusd()`` fiel stillschweigend auf ``return 1.05`` zurück; die
  Quelle hatte das Feld umbenannt, der Notwert griff monatelang (echt 1,146).
* ``httpx`` loggt auf INFO die komplette Request-URL — bei Telegram steht
  der Bot-Token darin (1,37 Mio. Zeilen Klartext-Token im Log).

Quellen:
* https://apscheduler.readthedocs.io/en/3.x/userguide.html#missed-job-executions-and-coalescing
* https://www.python-httpx.org/logging/
"""

from __future__ import annotations

import os
import re

from ruttla.core import (
    CheckResult,
    Context,
    Finding,
    SelfTestCase,
    Severity,
    Status,
    register,
    result_for,
    snippet,
    strip_comments,
    unmeasured,
)

PLATFORM = "python"
GUIDELINE = "GUIDELINES.md § Python services"


def _body(source) -> str:
    return strip_comments(source.text, source.ext)


def _line_of(source, body: str, offset: int) -> tuple[int, str]:
    number = body.count("\n", 0, offset) + 1
    raw = source.lines[number - 1] if number <= len(source.lines) else ""
    return number, raw


def _call_args(body: str, open_paren: int) -> str:
    """Text zwischen der öffnenden Klammer und ihrer schließenden."""
    depth = 0
    for i in range(open_paren, len(body)):
        ch = body[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return body[open_paren + 1:i]
    return body[open_paren + 1:]


def _functions(body: str):
    """(name, start_offset, text) je def — Block bis zur ersten Zeile mit
    gleicher oder kleinerer Einrückung."""
    lines = body.split("\n")
    offsets = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1
    head = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(")
    for i, ln in enumerate(lines):
        m = head.match(ln)
        if not m:
            continue
        indent = len(m.group(1))
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                # Fortsetzung der Signatur (schließende Klammer) gehört noch dazu
                if not nxt.lstrip().startswith((")", "]")):
                    break
            j += 1
        yield m.group(2), offsets[i], "\n".join(lines[i:j])


# ---------------------------------------------------------------------------
# APScheduler ohne misfire_grace_time
# ---------------------------------------------------------------------------

_SCHEDULER = re.compile(
    r"\b(?:AsyncIO|Background|Blocking|Tornado|Twisted|Gevent|Qt)Scheduler\s*\(")
_ADD_JOB = re.compile(r"\.add_job\s*\(")


@register(
    "python.apscheduler_misfire_default",
    "APScheduler verwirft verspätete Jobs nach 1 s (misfire_grace_time fehlt)",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Scheduler mit Default-Kulanz",
            files={"bot/sched.py": (
                "from apscheduler.schedulers.asyncio import AsyncIOScheduler\n"
                "s = AsyncIOScheduler(timezone='Europe/Berlin')\n"
                "s.add_job(check, 'cron', minute='*/30')\n"
            )},
            expect=Status.FAIL,
            expect_finding_contains="misfire_grace_time",
        ),
        SelfTestCase(
            name="Scheduler mit job_defaults",
            files={"bot/sched.py": (
                "from apscheduler.schedulers.asyncio import AsyncIOScheduler\n"
                "s = AsyncIOScheduler(timezone='Europe/Berlin', job_defaults={\n"
                "    'misfire_grace_time': 600, 'coalesce': True, 'max_instances': 1})\n"
                "s.add_job(check, 'cron', minute='*/30')\n"
            )},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Kulanz an jedem add_job",
            files={"bot/sched.py": (
                "s = BackgroundScheduler()\n"
                "s.add_job(a, 'interval', minutes=1, misfire_grace_time=60)\n"
                "s.add_job(b, 'interval', minutes=5, misfire_grace_time=60)\n"
            )},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Kulanz nur an einem von zwei add_job",
            files={"bot/sched.py": (
                "s = BackgroundScheduler()\n"
                "s.add_job(a, 'interval', minutes=1, misfire_grace_time=60)\n"
                "s.add_job(b, 'interval', minutes=5)\n"
            )},
            expect=Status.FAIL,
        ),
    ],
)
def check_apscheduler_misfire(ctx: Context) -> CheckResult:
    check_id = "python.apscheduler_misfire_default"
    title = "APScheduler verwirft verspätete Jobs nach 1 s (misfire_grace_time fehlt)"
    findings: list[Finding] = []
    units = 0
    for source in ctx.files(".py"):
        body = _body(source)
        ctors = list(_SCHEDULER.finditer(body))
        if not ctors:
            continue
        configured = re.search(r"\.configure\s*\([^)]*misfire_grace_time", body, re.S)
        add_jobs = [_call_args(body, m.end() - 1) for m in _ADD_JOB.finditer(body)]
        every_job = bool(add_jobs) and all("misfire_grace_time" in a for a in add_jobs)
        for m in ctors:
            units += 1
            args = _call_args(body, m.end() - 1)
            if "misfire_grace_time" in args or configured or every_job:
                continue
            if "job_defaults" in args and "misfire_grace_time" in body:
                continue
            line, raw = _line_of(source, body, m.start())
            findings.append(Finding(
                check_id=check_id, severity=Severity.ERROR,
                message=(
                    "Scheduler ohne misfire_grace_time: ein Job, der mehr als 1 s "
                    "zu spät dran ist (anderer Job blockiert den Loop, Last), wird "
                    "übersprungen — nicht nachgeholt."
                ),
                file=source.rel, line=line, evidence=snippet(raw),
                fix=(
                    "job_defaults={'misfire_grace_time': 600, 'coalesce': True, "
                    "'max_instances': 1} im Konstruktor; lange synchrone Arbeit in "
                    "async-Jobs per asyncio.to_thread auslagern."
                ),
                guideline=GUIDELINE,
            ))
    if units == 0:
        return unmeasured(check_id, title, "Kein APScheduler-Konstruktor gefunden.", PLATFORM)
    return result_for(check_id, title, findings, units, "Scheduler", PLATFORM)


# ---------------------------------------------------------------------------
# Telegram-Token über httpx/urllib3-Logs
# ---------------------------------------------------------------------------

_PTB_OR_HTTPX = re.compile(r"^[ \t]*(?:from|import)\s+(?:telegram|httpx)\b", re.M)
_TELEGRAM_RAW = re.compile(r"api\.telegram\.org")
_BASIC_CONFIG = re.compile(r"\blogging\.basicConfig\s*\(")
_ROOT_LEVEL = re.compile(r"level\s*=\s*(?:logging\.)?[\"']?(INFO|DEBUG)\b")
_PROJECT_MARKERS = ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg")


def _silenced(text: str, logger_name: str) -> bool:
    """Name und setLevel(WARNING+) innerhalb weniger Zeilen — deckt auch
    ``for name in ("httpx", ...): getLogger(name).setLevel(...)`` ab."""
    return bool(re.search(
        r"[\"']" + logger_name + r"[\"'](?:[^\n]*\n){0,3}?[^\n]*setLevel\(\s*"
        r"(?:logging\.)?[\"']?(?:WARNING|ERROR|CRITICAL|WARN)",
        text))


def _project_of(ctx: Context, rel: str) -> str:
    parts = rel.split("/")[:-1]
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i])
        if any(os.path.exists(os.path.join(ctx.root, cand, m)) for m in _PROJECT_MARKERS):
            return cand
    return ""


@register(
    "python.telegram_token_log_leak",
    "Bot-Token landet über httpx/urllib3-Request-Logs im Klartext im Log",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="PTB-Bot mit INFO-Logging, httpx ungedrosselt",
            files={"main.py": (
                "import logging\n"
                "from telegram.ext import Application\n"
                "logging.basicConfig(level=logging.INFO)\n"
            )},
            expect=Status.FAIL,
            expect_finding_contains="httpx",
        ),
        SelfTestCase(
            name="PTB-Bot mit gedrosseltem httpx (Schleifenform)",
            files={"main.py": (
                "import logging\n"
                "from telegram.ext import Application\n"
                "logging.basicConfig(level=logging.INFO)\n"
                "for name in ('httpx', 'httpcore'):\n"
                "    logging.getLogger(name).setLevel(logging.WARNING)\n"
            )},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="requests an Telegram, INFO: urllib3 loggt URLs erst auf DEBUG",
            files={"bot.py": (
                "import logging, requests\n"
                "URL = 'https://api.telegram.org/bot' + TOKEN\n"
                "logging.basicConfig(level=logging.INFO)\n"
            )},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="requests an Telegram, DEBUG ohne urllib3-Drossel",
            files={"bot.py": (
                "import logging, requests\n"
                "URL = 'https://api.telegram.org/bot' + TOKEN\n"
                "logging.basicConfig(level=logging.DEBUG)\n"
            )},
            expect=Status.FAIL,
            expect_finding_contains="urllib3",
        ),
    ],
)
def check_telegram_token_log_leak(ctx: Context) -> CheckResult:
    check_id = "python.telegram_token_log_leak"
    title = "Bot-Token landet über httpx/urllib3-Request-Logs im Klartext im Log"
    sources = ctx.files(".py")
    bodies = {s.rel: _body(s) for s in sources}
    by_project: dict[str, list[str]] = {}
    for rel in bodies:
        by_project.setdefault(_project_of(ctx, rel), []).append(rel)
    project_text = {p: "\n".join(bodies[r] for r in rels) for p, rels in by_project.items()}
    findings: list[Finding] = []
    units = 0
    for source in sources:
        body = bodies[source.rel]
        uses_httpx = bool(_PTB_OR_HTTPX.search(body))
        uses_raw = bool(_TELEGRAM_RAW.search(body))
        if not (uses_httpx or uses_raw):
            continue  # Prüfbereich ist der Prozess, der Telegram tatsächlich ruft
        scope = project_text[_project_of(ctx, source.rel)]
        for m in _BASIC_CONFIG.finditer(body):
            units += 1
            level = _ROOT_LEVEL.search(_call_args(body, m.end() - 1))
            if not level:
                continue  # Default WARNING loggt keine Request-URLs
            missing = []
            if uses_httpx and not _silenced(scope, "httpx"):
                missing.append("httpx")
            if level.group(1) == "DEBUG" and not _silenced(scope, "urllib3") and (
                    uses_raw or "requests" in body):
                missing.append("urllib3")
            if not missing:
                continue
            line, raw = _line_of(source, body, m.start())
            findings.append(Finding(
                check_id=check_id, severity=Severity.ERROR,
                message=(
                    f"Root-Logger auf {level.group(1)} bei Telegram-Client: "
                    f"{', '.join(missing)} loggt die Request-URL samt /bot<TOKEN>/."
                ),
                file=source.rel, line=line, evidence=snippet(raw),
                fix=("logging.getLogger('httpx').setLevel(logging.WARNING) "
                     "(bei DEBUG zusätzlich 'urllib3') direkt nach basicConfig; "
                     "bestehende Logs auf den Token prüfen und ihn rotieren."),
                guideline=GUIDELINE,
            ))
    if units == 0:
        return unmeasured(check_id, title,
                          "Kein logging.basicConfig in einer Datei mit Telegram-Client.", PLATFORM)
    return result_for(check_id, title, findings, units, "Logging-Setups", PLATFORM)


# ---------------------------------------------------------------------------
# Yahoo-Chart: letzte Kerze mit close=None
# ---------------------------------------------------------------------------

_YAHOO_CHART = re.compile(r"v8/finance/chart")
_DROPS_NONE = re.compile(
    r"(?:dropna\s*\(|is\s+not\s+None\s*\]|if\s+\w+\s+is\s+not\s+None|\bfilter\s*\(\s*None)")


@register(
    "python.yahoo_chart_last_bar_dropped",
    "Yahoo-Chart: letzte Tageskerze (close=None) fällt weg — Kurs von vorgestern",
    platform=PLATFORM,
    severity=Severity.ERROR,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="close=None per dropna verworfen",
            files={"market/data.py": (
                "def chart(t):\n"
                "    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{t}')\n"
                "    q = r.json()['chart']['result'][0]['indicators']['quote'][0]\n"
                "    return pd.DataFrame({'Close': q['close']}).dropna(subset=['Close'])\n"
            )},
            expect=Status.FAIL,
            expect_finding_contains="regularMarketPrice",
        ),
        SelfTestCase(
            name="Listenfilter is not None",
            files={"market/src.py": (
                "def price(t):\n"
                "    d = requests.get(URL + '/v8/finance/chart/' + t).json()\n"
                "    close = [c for c in d['close'] if c is not None]\n"
                "    return close[-1]\n"
            )},
            expect=Status.FAIL,
        ),
        SelfTestCase(
            name="Letzte Kerze aus meta aufgefüllt",
            files={"market/data.py": (
                "def chart(t):\n"
                "    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{t}')\n"
                "    res = r.json()['chart']['result'][0]\n"
                "    df = frame(res)\n"
                "    df.iloc[-1, 0] = res['meta']['regularMarketPrice']\n"
                "    return df.dropna(subset=['Close'])\n"
            )},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Delegiert an Funktion, die meta nutzt",
            files={
                "market/data.py": (
                    "def chart_to_frame(res):\n"
                    "    price = res['meta']['regularMarketPrice']\n"
                    "    return fill(res, price).dropna()\n"
                ),
                "market/src.py": (
                    "def price(t):\n"
                    "    r = requests.get(URL + '/v8/finance/chart/' + t)\n"
                    "    return chart_to_frame(r.json()['chart']['result'][0])['Close'].dropna()\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_yahoo_last_bar(ctx: Context) -> CheckResult:
    check_id = "python.yahoo_chart_last_bar_dropped"
    title = "Yahoo-Chart: letzte Tageskerze (close=None) fällt weg — Kurs von vorgestern"
    sources = ctx.files(".py")
    bodies = {s.rel: _body(s) for s in sources}
    # Funktionen, die meta.regularMarketPrice verarbeiten — Aufrufer gelten als abgedeckt
    fillers = set()
    for body in bodies.values():
        for name, _, text in _functions(body):
            if "regularMarketPrice" in text:
                fillers.add(name)
    findings: list[Finding] = []
    units = 0
    for source in sources:
        body = bodies[source.rel]
        m = _YAHOO_CHART.search(body)
        if not m:
            continue
        units += 1
        if "regularMarketPrice" in body:
            continue
        if any(re.search(r"\b" + re.escape(f) + r"\s*\(", body) for f in fillers):
            continue
        drop = _DROPS_NONE.search(body)
        if not drop:
            continue
        line, raw = _line_of(source, body, drop.start())
        findings.append(Finding(
            check_id=check_id, severity=Severity.ERROR,
            message=(
                "Yahoo liefert die letzte Tageskerze (XETRA u. a.) mit close=None; "
                "hier wird sie verworfen, ohne meta.regularMarketPrice zu nutzen — "
                "Signale rechnen dann mit dem Schluss von vorgestern."
            ),
            file=source.rel, line=line, evidence=snippet(raw),
            fix=("Kerze des Handelstags von meta.regularMarketTime mit "
                 "meta.regularMarketPrice auffüllen bzw. anhängen, erst dann dropna; "
                 "vor Orders den Signalpreis gegen einen Live-Kurs halten."),
            guideline=GUIDELINE,
        ))
    if units == 0:
        return unmeasured(check_id, title, "Kein Yahoo-Chart-Abruf gefunden.", PLATFORM)
    return result_for(check_id, title, findings, units, "Yahoo-Abrufe", PLATFORM)


# ---------------------------------------------------------------------------
# Retry-Schleife wiederholt nicht-idempotente Requests
# ---------------------------------------------------------------------------

_RETRY_LOOP = re.compile(r"\bfor\s+\w+\s+in\s+range\s*\(|\bwhile\b[^\n]*(?:retr|attempt|versuch)",
                         re.IGNORECASE)
_WRITE_CALL = re.compile(
    r"(?:\.request\s*\(\s*(?:method\b|[\"'](?:POST|PUT|PATCH)[\"'])|"
    r"\.(?:post|put|patch)\s*\()")
_ANY_HTTP = re.compile(r"(?:\brequests\.\w+\s*\(|\.request\s*\(|\bsession\.\w+\s*\(|\bclient\.(?:get|post|put|patch|delete)\s*\()")
_IDEMPOTENCY_GUARD = re.compile(
    r"(?:idempoten|Idempotency-Key|method(?:\.upper\(\))?\s*(?:in|not\s+in|==|!=)\s*[\(\[\"'])",
    re.IGNORECASE)


@register(
    "python.http_retry_non_idempotent",
    "Retry-Schleife wiederholt POST/PUT nach Timeout — mögliche Doppelausführung",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Generischer Request mit Retry über alle Methoden",
            files={"broker/api.py": (
                "def _request(self, method, path, retries=3, **kw):\n"
                "    for attempt in range(retries):\n"
                "        try:\n"
                "            r = self.session.request(method, self.base + path, timeout=15, **kw)\n"
                "            return r.json()\n"
                "        except Exception:\n"
                "            time.sleep(2)\n"
            )},
            expect=Status.FAIL,
            expect_finding_contains="POST",
        ),
        SelfTestCase(
            name="Retry nur für idempotente Methoden",
            files={"broker/api.py": (
                "def _request(self, method, path, retries=3, **kw):\n"
                "    idempotent = method.upper() in ('GET', 'DELETE')\n"
                "    for attempt in range(retries):\n"
                "        try:\n"
                "            r = self.session.request(method, self.base + path, timeout=15, **kw)\n"
                "            return r.json()\n"
                "        except Exception:\n"
                "            if not idempotent:\n"
                "                raise\n"
                "            time.sleep(2)\n"
            )},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Reiner GET-Retry",
            files={"broker/api.py": (
                "def fetch(url):\n"
                "    for attempt in range(3):\n"
                "        r = requests.get(url, timeout=10)\n"
                "        if r.ok:\n"
                "            return r.json()\n"
                "def send(url, data):\n"
                "    return requests.post(url, json=data, timeout=10)\n"
            )},
            expect=Status.PASS,
        ),
    ],
)
def check_http_retry_non_idempotent(ctx: Context) -> CheckResult:
    check_id = "python.http_retry_non_idempotent"
    title = "Retry-Schleife wiederholt POST/PUT nach Timeout — mögliche Doppelausführung"
    findings: list[Finding] = []
    units = 0
    for source in ctx.files(".py"):
        body = _body(source)
        for name, start, text in _functions(body):
            loop = _RETRY_LOOP.search(text)
            if not loop:
                continue
            if not _ANY_HTTP.search(text, loop.end()):
                continue
            units += 1  # jede Retry-Schleife mit HTTP ist Kandidat, nicht nur Verstöße
            call = _WRITE_CALL.search(text, loop.end())
            if not call or _IDEMPOTENCY_GUARD.search(text):
                continue
            line, raw = _line_of(source, body, start + call.start())
            findings.append(Finding(
                check_id=check_id, severity=Severity.WARNING,
                message=(
                    f"'{name}' wiederholt einen schreibenden Request (POST/PUT/PATCH "
                    "oder beliebige Methode) in einer Schleife. Nach einem Timeout ist "
                    "offen, ob der Server ihn schon ausgeführt hat — Doppelorder/-buchung."
                ),
                file=source.rel, line=line, evidence=snippet(raw),
                fix=("Nur GET/DELETE bzw. sicher abgewiesene Antworten (429) wiederholen; "
                     "bei POST ohne Idempotency-Key nach Netzwerkfehler abbrechen und "
                     "den Zustand beim Server nachfragen."),
                guideline=GUIDELINE,
            ))
    if units == 0:
        return unmeasured(check_id, title, "Keine Retry-Schleife mit HTTP-Aufruf.", PLATFORM)
    return result_for(check_id, title, findings, units, "Retry-Schleifen", PLATFORM)


# ---------------------------------------------------------------------------
# Fester Notwert für Wechselkurse
# ---------------------------------------------------------------------------

# Auf den Kurs zielen, nicht auf die Währung im Namen: `_bot_value_eur()`
# liefert einen Betrag, keinen Kurs (Fehlalarm in einem Schwesterprojekt, 23.09.26).
_FX_FUNC = re.compile(
    r"(?i)(?:eur_?usd|usd_?eur|eur_?chf|chf_?eur|eur_?gbp|gbp_?eur|\bfx|_fx|forex|"
    r"exchange_?rate|conversion_?rate|wechselkurs)")
_FLOAT_FALLBACK = re.compile(
    r"(?:\breturn\s+(\d+\.\d+)\b|\.get\s*\(\s*[\"'][^\"']+[\"']\s*,\s*(\d+\.\d+)\s*\))")


@register(
    "python.hardcoded_fx_fallback",
    "Wechselkurs fällt still auf einen festen Zahlenwert zurück",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Notwert 1.05 bei Quellenfehler",
            files={"market/fx.py": (
                "def ecb_eurusd():\n"
                "    try:\n"
                "        return float(fetch()[-1].get('value', 1.05))\n"
                "    except Exception:\n"
                "        pass\n"
                "    return 1.05\n"
            )},
            expect=Status.FAIL,
            expect_finding_contains="1.05",
        ),
        SelfTestCase(
            name="Betrag in EUR ist kein Kurs",
            files={"risk/guard.py": (
                "def _bot_value_eur():\n"
                "    return 0.0\n"
                "def get_fx_rate(pair):\n"
                "    return fetch(pair)\n"
            )},
            expect=Status.PASS,
        ),
        SelfTestCase(
            name="Ohne Kurs wird geworfen",
            files={"market/fx.py": (
                "def ecb_eurusd():\n"
                "    rate = float(fetch()['OBS_VALUE'])\n"
                "    if currency == 'EUR':\n"
                "        return 1.0\n"
                "    if 0.5 < rate < 2.0:\n"
                "        return rate\n"
                "    raise RuntimeError('kein Kurs')\n"
            )},
            expect=Status.PASS,
        ),
    ],
)
def check_hardcoded_fx_fallback(ctx: Context) -> CheckResult:
    check_id = "python.hardcoded_fx_fallback"
    title = "Wechselkurs fällt still auf einen festen Zahlenwert zurück"
    findings: list[Finding] = []
    units = 0
    for source in ctx.files(".py"):
        body = _body(source)
        for name, start, text in _functions(body):
            if not _FX_FUNC.search(name):
                continue
            units += 1
            for m in _FLOAT_FALLBACK.finditer(text):
                value = m.group(1) or m.group(2)
                if float(value) == 1.0:
                    continue  # Gleichwährung ist kein Notwert
                line, raw = _line_of(source, body, start + m.start())
                findings.append(Finding(
                    check_id=check_id, severity=Severity.WARNING,
                    message=(
                        f"'{name}' liefert bei Quellenfehler den festen Wert {value}. "
                        "Ändert die Quelle ihr Format, greift der Notwert unbemerkt "
                        "dauerhaft und jede Umrechnung ist falsch."
                    ),
                    file=source.rel, line=line, evidence=snippet(raw),
                    fix=("Zweite echte Quelle als Fallback, Plausibilitätsband prüfen, "
                         "sonst werfen — der Verbraucher bricht dann sichtbar ab."),
                    guideline=GUIDELINE,
                ))
    if units == 0:
        return unmeasured(check_id, title, "Keine Wechselkurs-Funktion gefunden.", PLATFORM)
    return result_for(check_id, title, findings, units, "Wechselkurs-Funktionen", PLATFORM)
