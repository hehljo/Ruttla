#!/usr/bin/env python3
"""Legacy entry point — thin shim onto ``ruttla.cli`` (ADR-0001, ADR-0003).

    python3 master_gate.py [VERZEICHNIS] [Optionen]   ≡   ruttla [VERZEICHNIS] [Optionen]

Behaviour, flags, output and exit codes are identical to the ``ruttla``
command. Importing this module yields ``ruttla.cli`` (legacy API for scripts
and tests). Kept at least until 1.0; see CHANGELOG.md for the deprecation.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import ruttla.cli as _cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(_cli.run(sys.argv[1:], prog="master_gate.py"))
else:
    sys.modules[__name__] = _cli
