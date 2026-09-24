"""Check-author API facade — everything a rule module imports.

Rule packs import from here (``from ruttla.core import register, ...``); the
legacy ``core`` module of a repository checkout is an alias of this module.
Responsibilities live in the dedicated modules (models, discovery, config,
platforms, git, context, registry); this module only re-exports them.
"""

from __future__ import annotations

import subprocess  # noqa: F401  (legacy: tests patch core.subprocess.run)

from .config import CONFIG_FILENAME, LEGACY_CONFIG_FILENAME, Config, find_profile
from .context import Context
from .discovery import (
    AGENT_INSTRUCTION_FILES,
    DEFAULT_EXCLUDE_DIRS,
    DEFAULT_EXCLUDE_FILES,
    RULE_DOCS_MARKER,
    Coverage,
    SkippedFile,
    SourceFile,
    inventory,
    is_rule_definition_file,
    strip_comments,
)
from .models import (
    SCHEMA_VERSION,
    ChangedFilesError,
    CheckResult,
    ConfigError,
    Finding,
    GateInputError,
    SelfTestCase,
    Severity,
    Status,
)
from .platforms import KNOWN_PLATFORMS, PACK_PLATFORMS, PLATFORMS_WITHOUT_PACK
from .registry import (
    REGISTRY,
    Check,
    failed,
    iter_matches,
    ok,
    register,
    result_for,
    snippet,
    unmeasured,
)

__all__ = [
    "AGENT_INSTRUCTION_FILES", "CONFIG_FILENAME", "DEFAULT_EXCLUDE_DIRS",
    "DEFAULT_EXCLUDE_FILES", "KNOWN_PLATFORMS", "LEGACY_CONFIG_FILENAME",
    "PACK_PLATFORMS", "PLATFORMS_WITHOUT_PACK", "REGISTRY", "RULE_DOCS_MARKER",
    "SCHEMA_VERSION", "ChangedFilesError", "Check", "CheckResult", "Config",
    "ConfigError", "Context", "Coverage", "Finding", "GateInputError",
    "SelfTestCase", "Severity", "SkippedFile", "SourceFile", "Status", "failed",
    "find_profile", "inventory", "is_rule_definition_file", "iter_matches", "ok",
    "register", "result_for", "snippet", "strip_comments", "unmeasured",
]
