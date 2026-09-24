"""Compatibility alias (repository checkout only): ``import core`` → ``ruttla.core``.

Rule packs and third-party code should import ``ruttla.core`` directly. This
alias exists so that pre-0.1 scripts keep working (ADR-0001, ADR-0003) and is
removed together with the ``master_gate.py`` shim.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import ruttla.core as _core  # noqa: E402

sys.modules[__name__] = _core
