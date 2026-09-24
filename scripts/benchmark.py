#!/usr/bin/env python3
"""Maintainer benchmark (P03-T006): synthetic corpus, per-phase and per-rule timing.

    python scripts/benchmark.py --files 1000 10000 [--pad-kb 10] [--json out.json] [--top 10]

Generates a deterministic corpus (mix of Python, TypeScript, Swift, GDScript,
Markdown, JSON; a few planted findings) in a temp directory, then runs the
real engine in-process and reports wall time for inventory, platform
detection and every rule, plus peak RSS where the OS exposes it.
Numbers are only comparable on the same machine class.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ruttla.config import Config  # noqa: E402
from ruttla.context import Context  # noqa: E402
from ruttla.engine import load_checks, validate_result  # noqa: E402
from ruttla.registry import REGISTRY  # noqa: E402

TEMPLATES = {
    ".py": "import os\n\n\ndef handler_{i}(value: int) -> int:\n    # module {i}\n"
           "    return value * {i}\n" + "\n# filler line\n" * 40,
    ".ts": "export const item{i} = (x: number): number => x + {i};\n"
           "export function load{i}() {{ return fetch('/api/items/{i}'); }}\n"
           + "// filler\n" * 40,
    ".swift": "import SwiftUI\n\nstruct View{i}: View {{\n    var body: some View {{\n"
              "        Text(\"Item {i}\").font(.body)\n    }}\n}}\n" + "// filler\n" * 40,
    ".gd": "extends Node\n\nvar speed_{i}: float = 1.0\n\nfunc _ready() -> void:\n"
           "    pass\n" + "# filler\n" * 40,
    ".md": "# Doc {i}\n\nSome text for document {i}.\n\n```bash\n./run --id \"<ID>\"\n```\n",
    ".json": '{{"id": {i}, "name": "entry-{i}", "tags": ["a", "b"]}}\n',
}
PLANTED = {
    "src/secret_leak.ts": 'const token = "ghp_' + "c" * 36 + '";\n',
    "src/anchor.ts": 'const pos = src.indexOf("Speichern und weiter");\n',
}


def build_corpus(root: Path, n_files: int, pad_kb: int = 0, seed: int = 7) -> int:
    rng = random.Random(seed)
    exts = list(TEMPLATES)
    total = 0
    for i in range(n_files):
        ext = rng.choice(exts)
        rel = Path(f"pkg{i % 50:02d}", f"sub{i % 7}", f"file_{i}{ext}")
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = TEMPLATES[ext].format(i=i)
        if pad_kb and ext not in (".json", ".md"):
            marker = "#" if ext in (".py", ".gd") else "//"
            filler = f"{marker} padding line for size benchmark\n"
            data += filler * max(0, (pad_kb * 1024 - len(data)) // len(filler))
        path.write_text(data, encoding="utf-8", newline="\n")
        total += len(data.encode("utf-8"))
    for rel, data in PLANTED.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8", newline="\n")
        total += len(data)
    return total


def peak_rss_mb() -> float | None:
    try:
        import resource
    except ImportError:  # Windows
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def measure(n_files: int, pad_kb: int = 0) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="ruttla-bench-"))
    try:
        size = build_corpus(tmp, n_files, pad_kb)
        start = time.perf_counter()
        ctx = Context(str(tmp), Config())
        files = ctx.all_files()
        t_inventory = time.perf_counter() - start
        t0 = time.perf_counter()
        platforms = ctx.platforms()
        t_detect = time.perf_counter() - t0
        per_rule = {}
        for check in REGISTRY.values():
            if check.platform not in platforms:
                continue
            t0 = time.perf_counter()
            validate_result(check, check.fn(ctx))
            per_rule[check.id] = time.perf_counter() - t0
        total = time.perf_counter() - start
        return {
            "files": len(files), "bytes": size, "platforms": sorted(platforms),
            "inventory_s": round(t_inventory, 3), "detection_s": round(t_detect, 3),
            "rules_run": len(per_rule), "rules_s": round(sum(per_rule.values()), 3),
            "total_s": round(total, 3), "peak_rss_mb": peak_rss_mb(),
            "per_rule_s": {k: round(v, 4) for k, v in
                           sorted(per_rule.items(), key=lambda kv: -kv[1])},
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", type=int, nargs="+", default=[1000])
    ap.add_argument("--pad-kb", type=int, default=0,
                    help="pad source files to about this size (budget run: 10)")
    ap.add_argument("--json", help="write full results to this file")
    ap.add_argument("--top", type=int, default=8, help="slowest rules to print")
    args = ap.parse_args()
    load_checks()
    t0 = time.perf_counter()
    results = []
    for n in args.files:
        res = measure(n, args.pad_kb)
        results.append(res)
        mb = res["bytes"] / 1e6
        rss = f"{res['peak_rss_mb']:.0f} MB" if res["peak_rss_mb"] else "n/a"
        print(f"{res['files']:>6} files / {mb:6.1f} MB: total {res['total_s']:7.2f} s "
              f"(inventory {res['inventory_s']:.2f} s, detection {res['detection_s']:.2f} s, "
              f"{res['rules_run']} rules {res['rules_s']:.2f} s), peak RSS {rss}")
        for rule, secs in list(res["per_rule_s"].items())[:args.top]:
            print(f"         {secs:8.3f} s  {rule}")
    print(f"python {sys.version.split()[0]} on {sys.platform}, cpu_count={os.cpu_count()}, "
          f"harness {time.perf_counter() - t0:.1f} s")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
