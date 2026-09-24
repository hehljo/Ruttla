"""Human-readable text report (wording is not a contract; IDs are)."""

from __future__ import annotations

RED, GREEN, YELLOW, BLUE, GREY, BOLD, RESET = (
    "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[90m", "\033[1m", "\033[0m"
)


def palette(enabled: bool) -> tuple[str, ...]:
    if enabled:
        return RED, GREEN, YELLOW, BLUE, GREY, BOLD, RESET
    return ("",) * 7


def print_text(report: dict, use_color: bool, verbose: bool) -> None:
    red, green, yellow, blue, grey, bold, reset = palette(use_color)
    v = report["verdict"]
    head = {"green": (green, "GRÜN"), "failed": (red, "DURCHGEFALLEN"),
            "unmeasured": (yellow, "NICHT GEMESSEN"), "crash": (red, "ABSTURZ")}[v]

    print(f"\n{bold}RUTTLA{reset}  ·  {report['root']}")
    print(f"{grey}Plattformen: {', '.join(report['platforms_detected'])}"
          f"  ·  {report['files_scanned']} Dateien"
          f"  ·  Profil: {report['profile'] or 'keins'}"
          f"{'  ·  strict' if report.get('strict') else ''}{reset}")
    print()

    icon = {"fail": f"{red}✗{reset}", "pass": f"{green}✓{reset}",
            "unmeasured": f"{yellow}?{reset}", "error": f"{red}!{reset}"}
    for res in report["results"]:
        st = res["status"]
        if st == "pass" and not verbose:
            continue
        print(f"{icon[st]} {bold}{res['check_id']}{reset} — {res['title']}")
        if st == "unmeasured":
            print(f"   {yellow}nicht gemessen:{reset} {res['reason']}")
        elif st == "error":
            print(f"   {red}{res['reason'].splitlines()[0]}{reset}")
        for f in res["findings"]:
            loc = f"{f['file']}:{f['line']}" if f.get("file") and f.get("line") \
                else (f.get("file") or "—")
            sev_col = {"error": red, "warning": yellow, "info": grey}[f["severity"]]
            mark = f" {red}[blockiert]{reset}" if f.get("blocking") else ""
            print(f"   {sev_col}{f['severity'][:4].upper()}{reset} {loc}{mark}")
            print(f"        {f['message']}")
            if f.get("evidence"):
                print(f"        {grey}› {f['evidence']}{reset}")
            if f.get("fix"):
                print(f"        {blue}→ {f['fix']}{reset}")
        if res.get("findings_truncated"):
            print(f"   {grey}… und {res['findings_truncated']} weitere{reset}")
        print()

    coverage = report.get("coverage", {})
    skipped = coverage.get("files_skipped", [])
    if skipped:
        print(f"{yellow}Nicht geprüft (größer als gate.max_file_bytes = "
              f"{coverage.get('max_file_bytes')} Bytes):{reset}")
        for item in skipped:
            print(f"   {yellow}?{reset} {item['file']} ({item['bytes']} Bytes)")
        print()
    for platform in report.get("platforms_without_pack", []):
        print(f"{yellow}? Plattform '{platform}' erkannt, aber es gibt noch kein "
              f"Regelpaket — nicht gemessen.{reset}\n")

    c = report["checks"]
    s = report["findings_by_severity"]
    print("─" * 70)
    print(f"{head[0]}{bold}{head[1]}{reset}  ·  "
          f"{green}{c['pass']} bestanden{reset}, "
          f"{red}{c['fail']} durchgefallen{reset}, "
          f"{yellow}{c['unmeasured']} nicht gemessen{reset}"
          + (f", {red}{c['error']} abgestürzt{reset}" if c["error"] else ""))
    print(f"Befunde: {s['error']} Fehler · {s['warning']} Warnungen · {s['info']} Hinweise"
          f"  ·  {report.get('blocking_findings', 0)} blockierend, "
          f"{report.get('advisory_findings', 0)} nicht blockierend")
    print(f"{grey}{report['next_action']}{reset}")
