"""Official rule pack: web — booking, payment and SMS rules (deposits, GSM-7, no-show clauses)."""
from __future__ import annotations

import re

from ruttla.core import (
    Context, CheckResult, Finding, Severity, Status, SelfTestCase, register, unmeasured, result_for, snippet, strip_comments,
)
from ruttla.checks.web.rules import PLATFORM, WEB_CODE


@register(
    "web.stripe_deposit_immediate_capture",
    "Stripe-Kaution/Pfand mit Sofortabbuchung statt Vorautorisierung (0,55 € Verlust bei Erstattung)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 2",
    self_tests=[
        SelfTestCase(
            name="Kaution mit automatic capture",
            files={
                "src/payment.ts": (
                    "export async function createDeposit(stripe, amount) {\n"
                    "  return await stripe.paymentIntents.create({\n"
                    "    amount,\n"
                    "    currency: 'eur',\n"
                    "    capture_method: 'automatic',\n"
                    "  });\n"
                    "}\n"
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="capture_method",
        ),
        SelfTestCase(
            name="Kaution mit manuellem Hold (0,00 EUR Kosten)",
            files={
                "src/payment.ts": (
                    "export async function createDeposit(stripe, amount) {\n"
                    "  return await stripe.paymentIntents.create({\n"
                    "    amount,\n"
                    "    currency: 'eur',\n"
                    "    capture_method: 'manual',\n"
                    "  });\n"
                    "}\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_stripe_deposit_capture(ctx: Context) -> CheckResult:
    """Kautionen und No-Show-Pfand dürfen im Vorfeld nicht sofort eingezogen werden,
    weil Stripe bei einer späteren Erstattung nach ordnungsgemäßem Erscheinen die
    Transaktionsgebühren (~0,55 EUR) einbehält. Stattdessen ist zwingend ein manueller
    Hold (capture_method: 'manual') zu nutzen, dessen Storno 0,00 EUR kostet."""
    title = "Stripe-Kaution mit Sofortabbuchung statt Vorautorisierung"
    code = ctx.files(*WEB_CODE)
    findings: list[Finding] = []
    measured = 0

    deposit_ctx_pattern = re.compile(
        r"(deposit|kaution|no_?show|ausfallgebuehr|ausfallpauschale|pfand|preauth|hold)",
        re.IGNORECASE,
    )
    pi_create_pattern = re.compile(
        r"paymentIntents\.create\s*\(\s*\{([^}]+)\}",
        re.DOTALL,
    )

    for sf in code:
        if not deposit_ctx_pattern.search(sf.text):
            continue
        body = strip_comments(sf.text, sf.ext)
        for m in pi_create_pattern.finditer(body):
            measured += 1
            args = m.group(1)
            if "capture_method" not in args or "manual" not in args:
                line_no = body.count("\n", 0, m.start()) + 1
                raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else m.group(0)
                findings.append(Finding(
                    check_id="web.stripe_deposit_immediate_capture",
                    severity=Severity.WARNING,
                    message="Stripe PaymentIntent im Kautions-/No-Show-Kontext ohne 'capture_method: manual'.",
                    file=sf.rel,
                    line=line_no,
                    evidence=snippet(raw),
                    fix="capture_method: 'manual' setzen. Die Stornierung eines nicht beanspruchten Holds "
                        "kostet bei Stripe 0,00 EUR, während Sofortabbuchung bei Erstattung ~0,55 EUR verbrennt.",
                    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 2",
                ))

    if measured == 0:
        return unmeasured("web.stripe_deposit_immediate_capture", title,
                          "Keine Stripe-PaymentIntents in Kautions- oder No-Show-Pfaden gefunden.", PLATFORM)
    return result_for("web.stripe_deposit_immediate_capture", title, findings, measured,
                      "Stripe Kautions-Intents", PLATFORM)


@register(
    "web.sms_gsm7_unicode_overflow",
    "Emoji oder Sonderzeichen in SMS-Nachricht (halbiert GSM-7-Limit von 160 auf 70 Zeichen)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 3",
    self_tests=[
        SelfTestCase(
            name="SMS-Text mit Scheren-Emoji",
            files={
                "src/sms.ts": (
                    "export function notifyCustomer(phone) {\n"
                    "  return sendSms({ to: phone, text: 'Termin frei ✂️ jetzt buchen' });\n"
                    "}\n"
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="UCS-2",
        ),
        SelfTestCase(
            name="SMS-Text sauber in GSM-7",
            files={
                "src/sms.ts": (
                    "export function notifyCustomer(phone) {\n"
                    "  return sendSms({ to: phone, text: 'Termin frei jetzt buchen' });\n"
                    "}\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_sms_gsm7_overflow(ctx: Context) -> CheckResult:
    """Transaktionale SMS werden nach 160 Zeichen (GSM-7) abgerechnet. Ein einziges Emoji
    oder Sonderzeichen außerhalb von GSM-7 zwingt SMS-Gateways (Seven.io, Twilio) in die
    UCS-2-Kodierung (Unicode), wodurch das Segmentlimit auf 70 Zeichen schrumpft und
    die SMS-Kosten sofort verdoppelt werden."""
    title = "Emoji oder Sonderzeichen in SMS-Nachricht"
    code = ctx.files(*WEB_CODE)
    findings: list[Finding] = []
    measured = 0

    sms_call_pattern = re.compile(
        r"(?:sendSms|gateway\.seven\.io|twilio.*?messages\.create)\s*\(\s*\{([^}]+)\}",
        re.DOTALL | re.IGNORECASE,
    )
    emoji_pattern = re.compile(r"[\U00010000-\U0010ffff\u2702\u2704\u2708\u2709\u270A-\u270F]")

    for sf in code:
        if "sms" not in sf.text.lower() and "seven.io" not in sf.text.lower():
            continue
        body = strip_comments(sf.text, sf.ext)
        for m in sms_call_pattern.finditer(body):
            measured += 1
            call_body = m.group(1)
            if emoji_pattern.search(call_body):
                line_no = body.count("\n", 0, m.start()) + 1
                raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else m.group(0)
                findings.append(Finding(
                    check_id="web.sms_gsm7_unicode_overflow",
                    severity=Severity.WARNING,
                    message="SMS-Aufruf enthält Emoji oder 4-Byte-Unicode (schaltet Gateway auf UCS-2 mit 70-Zeichen-Limit).",
                    file=sf.rel,
                    line=line_no,
                    evidence=snippet(raw),
                    fix="Emojis entfernen und reinen GSM-7-Zeichensatz nutzen (z. B. '20 EUR' statt '20 €'), "
                        "um das 160-Zeichen-Limit pro SMS-Segment einzuhalten.",
                    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 3",
                ))

    if measured == 0:
        return unmeasured("web.sms_gsm7_unicode_overflow", title,
                          "Keine transaktionalen SMS-Aufrufe gefunden.", PLATFORM)
    return result_for("web.sms_gsm7_unicode_overflow", title, findings, measured,
                      "SMS-Aufrufe", PLATFORM)


@register(
    "web.no_show_bgb_309_clause",
    "No-Show-Pauschale ohne Pflichthinweis auf Schadensnachweis (§ 309 Nr. 5b BGB)",
    platform=PLATFORM,
    severity=Severity.WARNING,
    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 2",
    self_tests=[
        SelfTestCase(
            name="Ausfallgebühr ohne Schadensnachweis-Klausel",
            files={
                "src/Terms.vue": (
                    "<template>\n"
                    "  <p>Bei Nichterscheinen wird eine Ausfallpauschale von 20 EUR fällig.</p>\n"
                    "</template>\n"
                ),
            },
            expect=Status.FAIL,
            expect_finding_contains="§ 309 Nr. 5b BGB",
        ),
        SelfTestCase(
            name="Ausfallgebühr mit BGB-Schadensnachweis-Klausel",
            files={
                "src/Terms.vue": (
                    "<template>\n"
                    "  <p>Bei Nichterscheinen wird eine Ausfallpauschale von 20 EUR fällig. "
                    "Dem Kunden bleibt der Nachweis gestattet, dass kein Schaden entstanden ist.</p>\n"
                    "</template>\n"
                ),
            },
            expect=Status.PASS,
        ),
    ],
)
def check_no_show_bgb_clause(ctx: Context) -> CheckResult:
    """Nach deutschem AGB-Recht (§ 309 Nr. 5b BGB) ist eine pauschalierte Entschädigung oder
    No-Show-Ausfallgebühr gegenüber Verbrauchern nur wirksam, wenn dem Kunden ausdrücklich der
    Nachweis gestattet wird, dass dem Betrieb kein oder ein wesentlich geringerer Schaden entstanden ist."""
    title = "No-Show-Pauschale ohne Pflichthinweis nach § 309 Nr. 5b BGB"
    files = ctx.files(*WEB_CODE, ".html")
    findings: list[Finding] = []
    measured = 0

    no_show_pattern = re.compile(
        r"(?:ausfallpauschale|ausfallgeb[üu]hr|no-?show-?(?:geb[üu]hr|pauschale)|stornopauschale)",
        re.IGNORECASE,
    )
    bgb_defense_pattern = re.compile(
        r"(?:nachweis\s+gestattet|geringeren?\s+schaden)",
        re.IGNORECASE,
    )

    for sf in files:
        if not no_show_pattern.search(sf.text):
            continue
        body = strip_comments(sf.text, sf.ext)
        for m in no_show_pattern.finditer(body):
            measured += 1
            line_no = body.count("\n", 0, m.start()) + 1
            start_line = max(0, line_no - 15)
            end_line = min(len(sf.lines), line_no + 15)
            context_window = " ".join(sf.lines[start_line:end_line])
            if not bgb_defense_pattern.search(context_window):
                raw = sf.lines[line_no - 1] if line_no <= len(sf.lines) else m.group(0)
                findings.append(Finding(
                    check_id="web.no_show_bgb_309_clause",
                    severity=Severity.WARNING,
                    message="Ausfallpauschale ohne gesetzlichen Pflichthinweis auf Schadensnachweis (§ 309 Nr. 5b BGB).",
                    file=sf.rel,
                    line=line_no,
                    evidence=snippet(raw),
                    fix="Pflichthinweis ergänzen: 'Dem Kunden bleibt der Nachweis gestattet, dass dem Betrieb "
                        "kein oder ein wesentlich geringerer Schaden entstanden ist.' (Schützt vor Abmahnung).",
                    guideline="CODE_QUALITY_GUIDELINES_WEB.md § 2",
                ))

    if measured == 0:
        return unmeasured("web.no_show_bgb_309_clause", title,
                          "Keine No-Show- oder Ausfallpauschalen in Texten gefunden.", PLATFORM)
    return result_for("web.no_show_bgb_309_clause", title, findings, measured,
                      "No-Show Klauseln", PLATFORM)
