"""Public rule catalog: ``--list --format json``, ``--explain`` and docs/RULES.md.

Guideline strings in the rules name the maintainer's original guideline
documents (e.g. ``CLAUDE.md § Grundsatz C``), which are not public. Each
guideline family is mapped here to a public section of docs/GUIDELINES.md
(P01-T006), so every rule's rationale is reachable without private context.
"""

from __future__ import annotations

import json
import re

from .registry import REGISTRY, Check

GUIDELINES_DOC = "docs/GUIDELINES.md"

# (prefix of the guideline string, anchor in docs/GUIDELINES.md, one-line
# public summary). First match wins, so more specific prefixes come first.
GUIDELINE_FAMILIES: list[tuple[str, str, str]] = [
    ("Apple:", "apple-platform-documentation",
     "Apple developer documentation for the named key, entitlement or file format."),
    ("Apple Asset Catalog", "apple-platform-documentation",
     "Apple developer documentation for the named key, entitlement or file format."),
    ("CLAUDE.md § Architektur-Grundsatz A", "principle-a-single-source-of-truth",
     "Derived values are computed from one source, never copied by hand."),
    ("CLAUDE.md § Grundsatz A", "principle-a-single-source-of-truth",
     "Derived values are computed from one source, never copied by hand."),
    ("CLAUDE.md § Grundsatz B", "principle-b-lab-flags-are-compile-time-constants",
     "Experimental code is switched by statically evaluable flags."),
    ("CLAUDE.md § Grundsatz C", "principle-c-visible-text-lives-in-a-catalog",
     "Visible text lives in a catalog; no concatenation, no orphan keys."),
    ("CLAUDE.md § Grundsatz D", "principle-d-hardware-behind-an-interface",
     "Hardware access is isolated so logic is testable without the device."),
    ("CLAUDE.md § Grundsatz E", "principle-e-protocols-evolve-safely",
     "Published formats tolerate unknown values; names follow runtime meaning."),
    ("CLAUDE.md § Gates", "gates-must-not-lie",
     "A gate reports the real status: no swallowed exit codes, zero tests is red."),
    ("CLAUDE.md § 'Ein Gate, das aus einem Artefakt liest", "gates-must-not-lie",
     "A gate reports the real status: no swallowed exit codes, zero tests is red."),
    ("CLAUDE.md § 'Ein Anzeigetext ist nie ein Anker'", "anchor-on-identifiers-not-display-text",
     "Logic anchors on identifiers, never on user-visible wording."),
    ("CLAUDE.md § 'Die zweite Liste ist fast nie die letzte'", "one-list-not-two",
     "A value list maintained in two places drifts; derive the second one."),
    ("CLAUDE.md § 'Eine feste Wartezeit misst den Zufall'", "wait-for-state-not-time",
     "Waiting a fixed time measures chance; wait for the state instead."),
    ("CLAUDE.md § 'Frequenz mal Kardinalität'", "frequency-times-cardinality",
     "Per-frame work multiplies by entity count; hot paths stay allocation-free."),
    ("CLAUDE.md § Frequenz mal Kardinalität", "frequency-times-cardinality",
     "Per-frame work multiplies by entity count; hot paths stay allocation-free."),
    ("CLAUDE.md § Zustand, Zeit und Nebenläufigkeit", "wait-for-state-not-time",
     "Waiting a fixed time measures chance; wait for the state instead."),
    ("CLAUDE.md § Kommunikationsstil", "no-assistant-traces-in-code",
     "Source code and history carry no AI-assistant signatures."),
    ("CLAUDE.md § Supabase", "secrets-never-in-source",
     "Credentials are recognised by their form and never live in source."),
    ("CLAUDE.md § Konsistenz", "one-list-not-two",
     "A value list maintained in two places drifts; derive the second one."),
    ("CLAUDE.md § Anker", "anchor-on-identifiers-not-display-text",
     "Logic anchors on identifiers, never on user-visible wording."),
    ("CLAUDE.md § Rechtliche Blocker", "web-guidelines",
     "Web: layout, mobile, accessibility, secrets, error and legal requirements."),
    ("CODE_QUALITY_GUIDELINES_WEB.md", "web-guidelines",
     "Web: layout, mobile, accessibility, secrets, error and legal requirements."),
    ("CODE_QUALITY_GUIDELINES_GAMEDEV.md", "game-development-guidelines-godot",
     "Godot: lifecycle order, physics timing, signals, data-driven balance, multiplayer trust."),
    ("CODE_QUALITY_GUIDELINES_RASPBERRY.md", "raspberry-pi-field-device-guidelines",
     "Field devices: isolation, timeouts, validated config, immutable raw data, restarts."),
    ("CODE_QUALITY_GUIDELINES_UNREAL.md", "unreal-engine-guidelines",
     "Unreal: asset loading, callers, config readers, collision notify, authority."),
    ("IOS_DEBUGGING_GUIDELINES.md", "apple-build-and-debugging-guidelines",
     "Apple builds: identifiers, toolchain, logging, compiler and SwiftUI traps."),
    ("guides/", "apple-build-and-debugging-guidelines",
     "Apple builds: identifiers, toolchain, logging, compiler and SwiftUI traps."),
    ("swiftui_multiplatform_guideline.md", "apple-build-and-debugging-guidelines",
     "Apple builds: identifiers, toolchain, logging, compiler and SwiftUI traps."),
    ("GUIDELINES.md § Media pipelines", "media-pipelines",
     "Offline audio/video pipelines: limiter, TTS duration, mux verification, argument quoting."),
    ("GUIDELINES.md § Python services", "long-running-python-services",
     "Long-running Python services: scheduler misfires, token logging, data gaps, retries."),
    ("GUIDELINES.md § Python authentication", "python-authentication",
     "Password comparisons must handle non-ASCII Unicode without runtime errors."),
    ("GUIDELINES.md § Documentation", "documentation-that-can-be-executed",
     "Docs snippets must be copy-paste safe and diff-clean."),
]


def guideline_family(guideline: str) -> tuple[str, str] | None:
    """(anchor, public summary) for a guideline string, or None."""
    for prefix, anchor, summary in GUIDELINE_FAMILIES:
        if guideline.startswith(prefix):
            return anchor, summary
    return None


def rule_record(check: Check) -> dict:
    record = check.metadata()
    family = guideline_family(check.guideline)
    record["guideline_public"] = (
        {"doc": f"{GUIDELINES_DOC}#{family[0]}", "summary": family[1]} if family else None
    )
    return record


def catalog() -> list[dict]:
    return [rule_record(check) for check in sorted(REGISTRY.values(), key=lambda c: c.id)]


def catalog_json() -> str:
    from . import __version__
    return json.dumps({"tool_name": "ruttla", "tool_version": __version__,
                       "rules": catalog()}, ensure_ascii=False, indent=2)


def _probe_block(files: dict[str, str], limit: int = 40) -> list[str]:
    out = []
    for rel, content in files.items():
        lines = content.splitlines()
        shown = lines[:limit]
        # A fence longer than any backtick run inside the probe (Markdown
        # probes contain their own ``` blocks).
        longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
        fence = "`" * max(3, longest + 1)
        out.append(f"`{rel}`")
        out.append("")
        out.append(f"{fence}text")
        out.extend(shown)
        if len(lines) > limit:
            out.append(f"… ({len(lines) - limit} more lines)")
        out.append(fence)
        out.append("")
    return out


def explain(check_id: str) -> str:
    check = REGISTRY[check_id]
    record = rule_record(check)
    lines = [
        f"{check.id} — {check.title}",
        "",
        f"pack:              {record['pack']}",
        f"default severity:  {record['default_severity']}",
        f"blocking without a profile: {'yes (safe_by_default)' if check.safe_by_default else 'no'}",
        f"lifecycle:         {record['lifecycle']} (introduced in {record['introduced_in']})",
        f"tags:              {', '.join(record['tags'])}",
    ]
    if check.guideline:
        lines.append(f"guideline:         {check.guideline}")
    if record["guideline_public"]:
        lines.append(f"public rationale:  {record['guideline_public']['doc']}")
        lines.append(f"                   {record['guideline_public']['summary']}")
    for ref in record["references"]:
        lines.append(f"reference:         {ref}")
    rationale = record["rationale"]
    lines += ["", "Why it exists:", rationale or "(see the guideline section above)", ""]
    for case in check.self_tests:
        lines.append(f"Probe [{case.expect.value}] {case.name}")
    return "\n".join(lines).rstrip() + "\n"


def rules_markdown() -> str:
    """docs/RULES.md — generated, never edited by hand (P05-T007)."""
    from . import __version__  # noqa: F401  (kept out of the text: stable output)
    rules = catalog()
    by_pack: dict[str, list[dict]] = {}
    for rule in rules:
        by_pack.setdefault(rule["pack"], []).append(rule)
    out = [
        "<!-- ruttla:rule-docs -->",
        "<!-- GENERATED by `python scripts/gen_rule_docs.py` — do not edit. -->",
        "",
        "# Rule catalog",
        "",
        f"{len(rules)} rules in {len(by_pack)} packs. Every rule ships at least one "
        "broken probe (must FAIL) and one healthy probe (must PASS); both are shown "
        "below as the rule's evidence. Rule messages are currently German.",
        "",
        "| Pack | Rules | Blocking without profile |",
        "|---|---:|---:|",
    ]
    for pack in sorted(by_pack):
        items = by_pack[pack]
        out.append(f"| {pack} | {len(items)} | {sum(r['safe_by_default'] for r in items)} |")
    out.append("")
    for pack in sorted(by_pack):
        out += [f"## Pack `{pack}`", ""]
        for rule in by_pack[pack]:
            check = REGISTRY[rule["id"]]
            out += [f"### `{rule['id']}`", "", f"**{rule['title']}**", ""]
            out.append(f"- Default severity: `{rule['default_severity']}`"
                       + (" — blocking without a profile (`safe_by_default`)"
                          if rule["safe_by_default"] else ""))
            out.append(f"- Lifecycle: {rule['lifecycle']}, introduced in {rule['introduced_in']}")
            if rule["guideline"]:
                out.append(f"- Guideline: {rule['guideline']}")
            if rule["guideline_public"]:
                anchor = rule["guideline_public"]["doc"].split("#", 1)[1]
                out.append(f"- Public rationale: [GUIDELINES.md › {anchor}](GUIDELINES.md#{anchor})")
            for ref in rule["references"]:
                out.append(f"- Reference: <{ref}>")
            out.append("")
            if rule["rationale"]:
                out += ["<details><summary>Why it exists</summary>", "", "```text",
                        rule["rationale"], "```", "", "</details>", ""]
            broken = next((c for c in check.self_tests if c.expect.value == "fail"), None)
            healthy = next((c for c in check.self_tests if c.expect.value == "pass"), None)
            for label, case in (("Broken probe (must FAIL)", broken),
                                ("Healthy probe (must PASS)", healthy)):
                if case is None:
                    continue
                out += [f"<details><summary>{label}: {case.name}</summary>", ""]
                out += _probe_block(case.files)
                out += ["</details>", ""]
    return "\n".join(out).rstrip() + "\n"
