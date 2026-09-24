"""Agent format: one tab-separated line per item, stable and parseable.

Contract (docs/CONTRACTS.md): new fields are only ever APPENDED — to the
header as ``KEY=value`` and to finding lines as a trailing tab field — so
positional parsers keep working.
"""

from __future__ import annotations


def agent_field(value: object) -> str:
    """Ein Agent-Feld bleibt genau eine tabgetrennte Zeile."""
    return " ".join(str(value).replace("\t", " ").splitlines())


def print_agent(report: dict) -> None:
    """Kompaktformat für eine CLI/KI: eine Zeile je Befund, stabil geparst."""
    coverage = report.get("coverage", {})
    print(f"VERDICT={report['verdict']} EXIT={report['exit_code']} "
          f"PASS={report['checks']['pass']} FAIL={report['checks']['fail']} "
          f"UNMEASURED={report['checks']['unmeasured']} "
          f"ERRORS={report['findings_by_severity']['error']} "
          f"WARNINGS={report['findings_by_severity']['warning']} "
          f"TRUNCATED={report['findings_truncated']} "
          f"SCHEMA={report.get('schema_version', '1.0')} "
          f"BLOCKING={report.get('blocking_findings', 0)} "
          f"ADVISORY={report.get('advisory_findings', 0)} "
          f"SKIPPED={coverage.get('files_skipped_total', 0)}")
    for res in report["results"]:
        if res["status"] == "unmeasured":
            print(f"UNMEASURED\t{res['check_id']}\t{agent_field(res['reason'])}")
        elif res["status"] == "error":
            print(f"CRASH\t{res['check_id']}\t{agent_field(res['reason'])}")
        for f in res["findings"]:
            loc = f"{f.get('file') or '-'}:{f.get('line') or 0}"
            blocking = "true" if f.get("blocking") else "false"
            print(f"{f['severity'].upper()}\t{f['check_id']}\t{agent_field(loc)}\t"
                  f"{agent_field(f['message'])}\tFIX: {agent_field(f.get('fix') or '-')}"
                  f"\tBLOCKING={blocking}")
        if res["findings_truncated"]:
            print(f"TRUNCATED\t{res['check_id']}\t{res['findings_truncated']}")
    for skipped in coverage.get("files_skipped", []):
        print(f"SKIPPED\t{agent_field(skipped['file'])}\t{skipped['reason']}\t{skipped['bytes']}")
    for platform in report.get("platforms_without_pack", []):
        print(f"NO_PACK\t{platform}\terkannt, aber kein Regelpaket — nicht gemessen")
    print(f"NEXT_ACTION\t{agent_field(report['next_action'])}")
