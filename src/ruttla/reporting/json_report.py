"""JSON reporter: the canonical report, serialised deterministically."""

from __future__ import annotations

import json


def dumps_report(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
