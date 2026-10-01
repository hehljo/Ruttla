#!/usr/bin/env python3
"""Explicit read-only Linux host capture; the normal Ruttla scan stays offline.

Run on the host being inspected. Emits no keys, IPs, hostnames or credentials.
This collector is not executed automatically by Ruttla.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess


def probe(*args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=20,
                           env={**os.environ, "LC_ALL": "C.UTF-8"})
        return {"returncode": p.returncode, "output": p.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired):
        return None


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def main():
    release = read("/etc/os-release") or ""
    os_id = re.search(r'^ID=["\']?([^"\'\n]+)', release, re.M)
    templates = read("/var/lib/dpkg/info/tzdata.templates")
    try:
        localtime = os.readlink("/etc/localtime")
        localtime = os.path.normpath(os.path.join("/etc", localtime))
    except OSError:
        localtime = None
    try:
        tun = stat.S_ISCHR(Path("/dev/net/tun").stat().st_mode)
    except OSError:
        tun = False
    data = {
        "ruttla_host_snapshot": 1,
        "os_id": os_id.group(1) if os_id else None,
        "localtime_target": localtime,
        "timezone_file": (read("/etc/timezone") or "").strip(),
        "tzdata_config_present": Path("/var/lib/dpkg/info/tzdata.config").is_file(),
        "tzdata_zone_templates": re.findall(r"^Template: tzdata/Zones/(\S+)$", templates, re.M) if templates else None,
        "virtualization": probe("systemd-detect-virt"),
        "tun_character_device": tun,
        "curl_present": shutil.which("curl") is not None,
        "dpkg_audit": probe("dpkg", "--audit"),
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
