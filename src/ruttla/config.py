"""Project profile: `.ruttla.toml` (legacy alias `.qualitygate.toml`).

The profile is validated completely before the scan; unknown tables, keys or
value types are errors, never silently ignored (FR-006).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .models import ConfigError, Severity
from .platforms import PACK_PLATFORMS, PLATFORMS_WITHOUT_PACK

CONFIG_FILENAME = ".ruttla.toml"
LEGACY_CONFIG_FILENAME = ".qualitygate.toml"
SUPPORTED_CONFIG_VERSIONS = {1}


def find_profile(root: str) -> str | None:
    """The profile that applies to ``root``; both names at once is ambiguous."""
    current = os.path.join(root, CONFIG_FILENAME)
    legacy = os.path.join(root, LEGACY_CONFIG_FILENAME)
    has_current, has_legacy = os.path.isfile(current), os.path.isfile(legacy)
    if has_current and has_legacy:
        raise ConfigError(
            f"Zwei Profile gefunden: {CONFIG_FILENAME} und {LEGACY_CONFIG_FILENAME}. "
            f"Nur eines behalten ({CONFIG_FILENAME} ist der aktuelle Name)."
        )
    if has_current:
        return current
    if has_legacy:
        return legacy
    return None


@dataclass
class Config:
    # check_id (oder Präfix mit '*') -> "error" | "warning" | "info" | "off"
    severity_overrides: dict[str, str] = field(default_factory=dict)
    exclude_dirs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)
    brand_names: list[str] = field(default_factory=list)
    brand_source_globs: list[str] = field(default_factory=list)
    max_file_bytes: int = 2_000_000
    # Ohne Profil laufen nur die universell sicheren Checks hart.
    strict: bool = False
    profile_path: str | None = None
    # project.platform: forces a rule pack on in ADDITION to detection
    # (ADR-0010). Additive, so a profile can never shrink coverage silently.
    project_platform: str | None = None
    config_version: int | None = None

    def severity_for(self, check_id: str, default: Severity) -> Severity | None:
        """None = Check ist abgeschaltet."""
        best: str | None = None
        best_len = -1
        for pattern, value in self.severity_overrides.items():
            if pattern == check_id or (
                pattern.endswith("*") and check_id.startswith(pattern[:-1])
            ):
                if len(pattern) > best_len:
                    best, best_len = value, len(pattern)
        if best is None:
            return default
        if best == "off":
            return None
        return Severity(best)

    def disabled_by_profile(self, check_ids: list[str]) -> list[str]:
        return [cid for cid in check_ids if self.severity_for(cid, Severity.WARNING) is None]

    @classmethod
    def load(cls, root: str, explicit: str | None = None) -> "Config":
        if explicit is not None:
            path = explicit
            if not os.path.isfile(path):
                raise ConfigError(f"Konfigurationsdatei fehlt: {path}")
        else:
            found = find_profile(root)
            if found is None:
                return cls()
            path = found
        try:
            import tomllib
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"Konfiguration nicht lesbar: {path}: {exc}") from exc
        return cls.from_mapping(data, profile_path=os.path.abspath(path))

    @classmethod
    def from_mapping(cls, data: dict, profile_path: str | None = None) -> "Config":
        allowed_top = {"gate", "project", "brand", "severity", "config_version"}
        unknown_tables = sorted(set(data) - allowed_top)
        if unknown_tables:
            raise ConfigError(
                "Unbekannte Konfigurationstabellen: " + ", ".join(unknown_tables)
            )

        def table(name: str, allowed_keys: set[str] | None = None) -> dict:
            value = data.get(name, {})
            if not isinstance(value, dict):
                raise ConfigError(f"[{name}] muss eine TOML-Tabelle sein.")
            if allowed_keys is not None:
                unknown = sorted(set(value) - allowed_keys)
                if unknown:
                    raise ConfigError(
                        f"[{name}] enthält unbekannte Schlüssel: " + ", ".join(unknown)
                    )
            return value

        def string_list(owner: str, key: str, value: object) -> list[str]:
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item for item in value
            ):
                raise ConfigError(
                    f"{owner}.{key} muss eine Liste nichtleerer Strings sein."
                )
            return list(value)

        cfg = cls(profile_path=profile_path)
        version = data.get("config_version")
        if version is not None:
            if isinstance(version, bool) or version not in SUPPORTED_CONFIG_VERSIONS:
                supported = ", ".join(str(v) for v in sorted(SUPPORTED_CONFIG_VERSIONS))
                raise ConfigError(
                    f"config_version muss eine unterstützte Version sein ({supported})."
                )
            cfg.config_version = version

        gate = table("gate", {"strict", "exclude_dirs", "exclude", "max_file_bytes"})
        strict = gate.get("strict", False)
        if not isinstance(strict, bool):
            raise ConfigError("gate.strict muss true oder false sein.")
        cfg.strict = strict
        cfg.exclude_dirs = string_list(
            "gate", "exclude_dirs", gate.get("exclude_dirs", [])
        )
        cfg.exclude_globs = string_list(
            "gate", "exclude", gate.get("exclude", [])
        )
        max_bytes = gate.get("max_file_bytes", cfg.max_file_bytes)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ConfigError("gate.max_file_bytes muss eine positive Ganzzahl sein.")
        cfg.max_file_bytes = max_bytes

        project = table("project", {"name", "platform"})
        project_name = project.get("name")
        project_platform = project.get("platform")
        if project_name is not None and (not isinstance(project_name, str) or not project_name):
            raise ConfigError("project.name muss ein nichtleerer String sein.")
        if project_platform is not None:
            if project_platform in PLATFORMS_WITHOUT_PACK:
                raise ConfigError(
                    f"project.platform = {project_platform!r} wird erkannt, hat aber "
                    "noch kein Regelpaket — der Wert hätte keine Wirkung."
                )
            if project_platform not in PACK_PLATFORMS:
                known = ", ".join(PACK_PLATFORMS)
                raise ConfigError(f"project.platform ist unbekannt (bekannt: {known}).")
            cfg.project_platform = project_platform

        brand = table("brand", {"name", "names", "source", "sources"})
        cfg.brand_names = string_list("brand", "names", brand.get("names", []))
        singular_name = brand.get("name")
        if singular_name is not None:
            if not isinstance(singular_name, str) or not singular_name:
                raise ConfigError("brand.name muss ein nichtleerer String sein.")
            cfg.brand_names.append(singular_name)
        if not cfg.brand_names and project_name:
            cfg.brand_names.append(project_name)
        cfg.brand_names = list(dict.fromkeys(cfg.brand_names))

        cfg.brand_source_globs = string_list(
            "brand", "sources", brand.get("sources", [])
        )
        singular_source = brand.get("source")
        if singular_source is not None:
            if not isinstance(singular_source, str) or not singular_source:
                raise ConfigError("brand.source muss ein nichtleerer String sein.")
            source_path = singular_source.rsplit(":", 1)[0]
            if not source_path:
                raise ConfigError("brand.source muss einen Dateipfad enthalten.")
            cfg.brand_source_globs.append(source_path)
        cfg.brand_source_globs = list(dict.fromkeys(cfg.brand_source_globs))

        severity = table("severity")
        allowed = {member.value for member in Severity} | {"off"}
        for key, value in severity.items():
            if not isinstance(key, str) or not key:
                raise ConfigError("severity-Schlüssel müssen nichtleere Strings sein.")
            if not isinstance(value, str) or value not in allowed:
                choices = ", ".join(sorted(allowed))
                raise ConfigError(
                    f"severity.{key} muss einer von {choices} sein."
                )
            cfg.severity_overrides[key] = value
        return cfg
