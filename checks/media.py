#!/usr/bin/env python3
"""Statische Checks für lokale Audio-/Video-Pipelines.

Belegte Fehlerbilder aus einer realen Offline-Synchronpipeline:

* FFmpegs ``alimiter`` normalisiert mit Standard-``level=true`` wieder bis
  0 dB, obwohl ``limit`` scheinbar Headroom verspricht.
* Ein generatives TTS-Modell lieferte für 6,96 s Zielzeit 655,28 s Audio.
  Ohne Dauerschranke wäre der Ausreißer in Timeline und Mix gelangt.
* Nach einem Mux war der vorhandene englische Untertitel als Deutsch markiert,
  weil ``s:s:0`` fälschlich für den neu angehängten Track gehalten wurde.
* Windows PowerShell ``Start-Process -ArgumentList`` fügt die Elemente zu einer
  Zeichenkette zusammen; dynamischer Text mit Leerzeichen braucht eigene
  Anführungszeichen oder einen argumenttreuen Prozessaufruf.

Quellen:
* https://ffmpeg.org/ffmpeg-filters.html#alimiter
* https://learn.microsoft.com/powershell/module/microsoft.powershell.management/start-process
"""

from __future__ import annotations

import re

from core import (
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

MEDIA_SOURCE_EXTS = (
    ".py", ".ps1", ".sh", ".bash", ".zsh", ".ts", ".tsx", ".js", ".mjs",
)
GUIDELINE = "qualitygate/README.md § Medien-Pipelines"


def _sources(ctx: Context):
    return ctx.files(*MEDIA_SOURCE_EXTS)


def _body(source) -> str:
    return strip_comments(source.text, source.ext)


def _line(source, body: str, offset: int) -> tuple[int, str]:
    number = body.count("\n", 0, offset) + 1
    raw = source.lines[number - 1] if number <= len(source.lines) else ""
    return number, raw


# ---------------------------------------------------------------------------
# FFmpeg-Limiter
# ---------------------------------------------------------------------------

_LIMITER = re.compile(r"\balimiter\b(?:\s*=\s*[^;\]\n\"']*)?", re.IGNORECASE)
_LIMITER_HEADROOM = re.compile(r"\blevel\s*=\s*(?:false|0|off|no)\b", re.IGNORECASE)


@register(
    "media.ffmpeg_limiter_auto_level",
    "FFmpeg-Limiter hebt den Mix trotz Limit wieder bis 0 dB an",
    severity=Severity.WARNING,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Limiter mit aktivem Auto-Level",
            files={
                "mix.py": (
                    'FILTER = "[a][b]amix=inputs=2:normalize=0,'
                    'alimiter=limit=0.85[out]"\n'
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="level=false",
        ),
        SelfTestCase(
            name="Limiter mit echtem Headroom",
            files={
                "mix.py": (
                    'FILTER = "[a][b]amix=inputs=2:normalize=0,'
                    'alimiter=limit=0.85:level=false[out]"\n'
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_ffmpeg_limiter_auto_level(ctx: Context) -> CheckResult:
    """``limit`` begrenzt nur vor dem standardmäßigen Auto-Level.

    Der Check zählt jeden Limiter als Kandidat, nicht nur Verstöße. Absichtliche
    Vollaussteuerung bleibt möglich, wird aber als reviewpflichtige Warnung
    sichtbar; deshalb ist der Check nicht ``safe_by_default``.
    """

    check_id = "media.ffmpeg_limiter_auto_level"
    title = "FFmpeg-Limiter hebt den Mix trotz Limit wieder bis 0 dB an"
    findings: list[Finding] = []
    units = 0
    for source in _sources(ctx):
        body = _body(source)
        for match in _LIMITER.finditer(body):
            units += 1
            if _LIMITER_HEADROOM.search(match.group(0)):
                continue
            line_number, raw = _line(source, body, match.start())
            findings.append(Finding(
                check_id=check_id,
                severity=Severity.WARNING,
                message=(
                    "'alimiter' nutzt das standardmäßige Auto-Level; ohne "
                    "level=false garantiert ein kleineres limit keinen Headroom."
                ),
                file=source.rel,
                line=line_number,
                evidence=snippet(raw),
                fix=(
                    "Wenn Headroom beabsichtigt ist, `level=false` setzen und "
                    "den fertigen Mix mit volumedetect/Peak-Messung prüfen."
                ),
                guideline=GUIDELINE,
            ))
    if units == 0:
        return unmeasured(check_id, title, "Kein FFmpeg-alimiter gefunden.")
    return result_for(check_id, title, findings, units, "Limiter-Aufrufe")


# ---------------------------------------------------------------------------
# Generative TTS-Dauer
# ---------------------------------------------------------------------------

_TTS = re.compile(
    r"(?:audiocpp_cli|qwen[\w.-]*tts|--task[\s\"',]+tts\b|"
    r"\btext[_-]?to[_-]?speech\b|\btts[_-]?(?:output|generate|synthesi[sz]e))",
    re.IGNORECASE,
)
_MEDIA_SINK = re.compile(
    r"(?:\bamix\b|filter_complex|\bmux\w*\b|ffmpeg[^\n]{0,160}-map|"
    r"timeline|dialogue[_-]?mix)",
    re.IGNORECASE,
)
_DURATION_MEASUREMENT = re.compile(
    r"(?:ffprobe|\b(?:get_)?duration\s*\(|\b\w*duration\w*\s*=|"
    r"getnframes\s*\(|\.duration\b)",
    re.IGNORECASE,
)
_DURATION_CONDITION = re.compile(
    r"\bif\b[^\n]{0,240}\b\w*(?:duration|seconds)\w*[^\n]{0,160}"
    r"(?:<=?|>=?|-(?:lt|le|gt|ge)\b)|"
    r"\bif\b[^\n]{0,240}(?:<=?|>=?|-(?:lt|le|gt|ge)\b)"
    r"[^\n]{0,160}\b\w*(?:duration|seconds)\w*",
    re.IGNORECASE,
)
_ABORT = re.compile(r"\b(?:raise|throw|exit|return|sys\.exit)\b", re.IGNORECASE)


def _has_duration_guard(body: str) -> bool:
    if not _DURATION_MEASUREMENT.search(body):
        return False
    for condition in _DURATION_CONDITION.finditer(body):
        if _ABORT.search(body[condition.start(): condition.end() + 320]):
            return True
    return bool(re.search(
        r"(?:validate|assert|check)[_\w]*(?:duration|audio_length)",
        body,
        re.IGNORECASE,
    ))


@register(
    "media.tts_without_duration_guard",
    "Generierte TTS-Ausgabe gelangt ohne Dauerplausibilisierung in den Mix",
    severity=Severity.WARNING,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Max-Tokens allein schützt den Mix nicht",
            files={
                "pipeline.py": (
                    "import subprocess\n"
                    "subprocess.run(['audiocpp_cli', '--task', 'tts', "
                    "'--max-tokens', '256', '--out', 'voice.wav'])\n"
                    "subprocess.run(['ffmpeg', '-i', 'voice.wav', "
                    "'-filter_complex', 'amix=inputs=2', 'mix.wav'])\n"
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="Dauerschranke",
        ),
        SelfTestCase(
            name="TTS-Dauer wird vor dem Mix hart geprüft",
            files={
                "pipeline.py": (
                    "import subprocess\n"
                    "subprocess.run(['audiocpp_cli', '--task', 'tts', "
                    "'--out', 'voice.wav'])\n"
                    "raw_duration = duration('voice.wav')\n"
                    "if raw_duration < 0.2 or raw_duration > 30.0:\n"
                    "    raise RuntimeError('TTS duration invalid')\n"
                    "subprocess.run(['ffmpeg', '-i', 'voice.wav', "
                    "'-filter_complex', 'amix=inputs=2', 'mix.wav'])\n"
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_tts_duration_guard(ctx: Context) -> CheckResult:
    """Ein Generationslimit beweist keine plausible Audiodauer.

    Gemessen werden Dateien, die sowohl TTS anstoßen als auch das Ergebnis in
    einen Medienpfad geben. Eine reine Provider-Implementierung ohne Mix ist
    kein Kandidat.
    """

    check_id = "media.tts_without_duration_guard"
    title = "Generierte TTS-Ausgabe gelangt ohne Dauerplausibilisierung in den Mix"
    candidates = []
    for source in _sources(ctx):
        body = _body(source)
        tts = _TTS.search(body)
        if tts and _MEDIA_SINK.search(body):
            candidates.append((source, body, tts))
    if not candidates:
        return unmeasured(
            check_id,
            title,
            "Keine Datei koppelt generative TTS mit Mix, Timeline oder Mux.",
        )

    findings: list[Finding] = []
    for source, body, tts in candidates:
        if _has_duration_guard(body):
            continue
        line_number, raw = _line(source, body, tts.start())
        findings.append(Finding(
            check_id=check_id,
            severity=Severity.WARNING,
            message=(
                "TTS gelangt in die Medienpipeline, ohne dass die erzeugte "
                "Audiodauer vor dem Mix durch eine harte Dauerschranke läuft."
            ),
            file=source.rel,
            line=line_number,
            evidence=snippet(raw),
            fix=(
                "Ausgabedauer messen und unplausible Werte vor Timing/Mix "
                "abbrechen; Tokenlimits sind nur eine zusätzliche Schranke."
            ),
            guideline=GUIDELINE,
        ))
    return result_for(check_id, title, findings, len(candidates), "TTS-Pipelines")


# ---------------------------------------------------------------------------
# Mux-Verifikation
# ---------------------------------------------------------------------------

_FFMPEG = re.compile(r"\bffmpeg(?:\.exe)?\b|\bFFMPEG\b")
_MAP = re.compile(r"(?:['\"]-map['\"]|\s-map\s)")
_MUX_TARGET = re.compile(r"(?:\.mkv\b|matroska|metadata:s:[as]|language=)", re.IGNORECASE)


def _has_stream_probe(sources) -> bool:
    for source in sources:
        body = _body(source)
        if not re.search(r"\bffprobe(?:\.exe)?\b|\bFFPROBE\b", body):
            continue
        describes_streams = (
            re.search(r"show_entries[^\n]{0,240}stream", body, re.IGNORECASE)
            and re.search(r"\b(?:language|stream_tags|tags\.language)\b", body, re.IGNORECASE)
            and re.search(r"\b(?:index|streams?)\b", body, re.IGNORECASE)
        )
        verifies_result = (
            re.search(r"\b(?:if|assert)\b[^\n]{0,240}(?:language|streams?|deu|eng)", body, re.IGNORECASE)
            or re.search(r"(?:validate|verify|check)[_\w]*stream[_\w]*(?:metadata|language)", body, re.IGNORECASE)
        )
        if describes_streams and verifies_result and _ABORT.search(body):
            return True
    return False


@register(
    "media.mux_without_stream_probe",
    "Mux-Ausgabe wird nicht auf Streamreihenfolge und Sprachmetadaten geprüft",
    severity=Severity.WARNING,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Neue Untertitelspur ohne Nachprüfung",
            files={
                "mux.py": (
                    "import subprocess\n"
                    "subprocess.run(['ffmpeg', '-i', 'in.mkv', '-i', 'de.srt', "
                    "'-map', '0:v', '-map', '0:s?', '-map', '1:s:0', "
                    "'-metadata:s:s:0', 'language=deu', 'out.mkv'])\n"
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="ffprobe",
        ),
        SelfTestCase(
            name="Output-Streams werden nach dem Mux validiert",
            files={
                "mux.py": (
                    "import subprocess\n"
                    "subprocess.run(['ffmpeg', '-i', 'in.mkv', '-i', 'de.srt', "
                    "'-map', '0:v', '-map', '0:s?', '-map', '1:s:0', 'out.mkv'])\n"
                ),
                "verify.py": (
                    "import subprocess\n"
                    "probe = subprocess.run(['ffprobe', '-show_entries', "
                    "'stream=index:stream_tags=language,title', 'out.mkv'], "
                    "capture_output=True, text=True)\n"
                    "if 'language=deu' not in probe.stdout:\n"
                    "    raise RuntimeError('stream language mismatch')\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_mux_stream_probe(ctx: Context) -> CheckResult:
    """Die Sprache des neuen Tracks hängt von der Output-Reihenfolge ab.

    Verifikation darf in einem eigenen QC-Modul liegen; deshalb wird
    projektweit gesucht statt dieselbe Bauform in der Mux-Datei zu erzwingen.
    """

    check_id = "media.mux_without_stream_probe"
    title = "Mux-Ausgabe wird nicht auf Streamreihenfolge und Sprachmetadaten geprüft"
    sources = _sources(ctx)
    candidates = []
    for source in sources:
        body = _body(source)
        mapping = _MAP.search(body)
        if _FFMPEG.search(body) and mapping and _MUX_TARGET.search(body):
            candidates.append((source, body, mapping))
    if not candidates:
        return unmeasured(check_id, title, "Kein FFmpeg-Mux mit neuen Streams gefunden.")
    if _has_stream_probe(sources):
        return result_for(check_id, title, [], len(candidates), "Mux-Pipelines")

    findings: list[Finding] = []
    for source, body, mapping in candidates:
        line_number, raw = _line(source, body, mapping.start())
        findings.append(Finding(
            check_id=check_id,
            severity=Severity.WARNING,
            message=(
                "Nach dem Mux fehlt eine wirkungsprüfende ffprobe-Kontrolle "
                "von Output-Index und Sprachmetadaten."
            ),
            file=source.rel,
            line=line_number,
            evidence=snippet(raw),
            fix=(
                "Fertige Datei mit ffprobe lesen und erwartete Streamreihenfolge, "
                "Sprache und Titel bei Abweichung hart ablehnen."
            ),
            guideline=GUIDELINE,
        ))
    return result_for(check_id, title, findings, len(candidates), "Mux-Pipelines")


# ---------------------------------------------------------------------------
# PowerShell-Argumente
# ---------------------------------------------------------------------------

_TEXT_ARGUMENT = re.compile(
    r"['\"]--(?:text|reference-text|target-text|prompt|instruct|style-ref-text)"
    r"['\"]\s*,?\s*(\$[A-Za-z_]\w*|['\"][^\n]*?['\"])",
    re.IGNORECASE,
)
_START_PROCESS_ARGUMENTS = re.compile(
    r"\bStart-Process\b[\s\S]{0,500}?-ArgumentList\b|"
    r"-ArgumentList\b[\s\S]{0,500}?\bStart-Process\b",
    re.IGNORECASE,
)


def _powershell_argument_is_quoted(body: str, token: str) -> bool:
    if "ProcessStartInfo" in body and re.search(r"\.ArgumentList\.Add\s*\(", body):
        return True
    if token.startswith("$"):
        name = token[1:]
        if "quot" in name.lower() or "escap" in name.lower():
            return True
        assignment = re.search(
            rf"\${re.escape(name)}\s*=([^\n]+)",
            body,
            re.IGNORECASE,
        )
        if assignment and "'\"'" in assignment.group(1):
            return True
        return False
    # Ein normales PowerShell-Literal verliert seine äußeren Quotes beim Join.
    # Sicher ist nur ein Wert, der die Quotes als Daten enthält.
    return token.startswith("'\"") or token.startswith("\"'\"")


@register(
    "media.powershell_text_argument_split",
    "Start-Process zerlegt dynamischen TTS-Text an Leerzeichen",
    severity=Severity.ERROR,
    guideline=GUIDELINE,
    self_tests=[
        SelfTestCase(
            name="Dynamischer Text unquoted in ArgumentList",
            files={
                "run.ps1": (
                    "$text = 'Das sind mehrere Wörter.'\n"
                    "$arguments = @('--text', $text, '--out', 'voice.wav')\n"
                    "Start-Process -FilePath $exe -ArgumentList $arguments -Wait\n"
                )
            },
            expect=Status.FAIL,
            expect_finding_contains="Leerzeichen",
        ),
        SelfTestCase(
            name="Dynamischer Text explizit gequotet",
            files={
                "run.ps1": (
                    "# Start-Process $exe -ArgumentList @('--text', $text)\n"
                    "$text = 'Das sind mehrere Wörter.'\n"
                    "$quotedText = '\"' + $text.Replace('\"', '\\\"') + '\"'\n"
                    "$arguments = @('--text', $quotedText, '--out', 'voice.wav')\n"
                    "Start-Process -FilePath $exe -ArgumentList $arguments -Wait\n"
                )
            },
            expect=Status.PASS,
        ),
    ],
)
def check_powershell_text_argument_split(ctx: Context) -> CheckResult:
    """Microsoft dokumentiert, dass ``ArgumentList`` zu einer Zeichenkette
    verbunden und äußere Anführungszeichen entfernt werden. Für freie Texte ist
    ein Arrayelement deshalb nicht automatisch ein Prozessargument.
    """

    check_id = "media.powershell_text_argument_split"
    title = "Start-Process zerlegt dynamischen TTS-Text an Leerzeichen"
    findings: list[Finding] = []
    units = 0
    for source in ctx.files(".ps1"):
        body = _body(source)
        if not _START_PROCESS_ARGUMENTS.search(body):
            continue
        for match in _TEXT_ARGUMENT.finditer(body):
            units += 1
            token = match.group(1)
            if _powershell_argument_is_quoted(body, token):
                continue
            line_number, raw = _line(source, body, match.start())
            findings.append(Finding(
                check_id=check_id,
                severity=Severity.ERROR,
                message=(
                    f"{match.group(0).split(',')[0]} erhält {token} ohne "
                    "prozesswirksame Quotes; Text nach dem ersten Leerzeichen "
                    "kann als separates Argument ankommen."
                ),
                file=source.rel,
                line=line_number,
                evidence=snippet(raw),
                fix=(
                    "Freitext inklusive eigener doppelter Quotes übergeben oder "
                    "einen argumenttreuen Aufruf wie ProcessStartInfo.ArgumentList "
                    "beziehungsweise den PowerShell-Call-Operator verwenden."
                ),
                guideline=GUIDELINE,
            ))
    if units == 0:
        return unmeasured(
            check_id,
            title,
            "Kein Start-Process-Aufruf mit dynamischem Freitext gefunden.",
        )
    return result_for(check_id, title, findings, units, "Freitextargumente")
