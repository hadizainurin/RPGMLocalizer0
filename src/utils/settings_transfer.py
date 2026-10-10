"""Export / import of the user's settings, with version compatibility rules.

An exported file looks like:

    {
      "format": "rpgmlocalizer-settings",
      "settings_schema": 1,
      "app_version": "1.1.3.12",
      "exported_at": "2026-10-11 03:20:00",
      "settings": { ... }
    }

API keys are never exported: the file is meant to be shareable, and keys on
the importing machine are left untouched.

DEVELOPERS - compatibility is configured here:
- SETTINGS_SCHEMA: bump when the meaning or shape of settings changes.
- MIN_IMPORT_SCHEMA: files with an older schema are refused.
- MIGRATIONS: {old_schema: function(settings) -> settings} upgrades an older
  file one schema step at a time instead of refusing it.
- INCOMPATIBLE_APP_VERSIONS: (first, last) inclusive ranges of app versions
  whose exports must be refused, e.g. a release that wrote bad values:
      INCOMPATIBLE_APP_VERSIONS = [("1.1.2.0", "1.1.2.9")]
- Files written by a NEWER app version are imported, but unknown keys are
  skipped and reported.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

FORMAT = "rpgmlocalizer-settings"
SETTINGS_SCHEMA = 1
MIN_IMPORT_SCHEMA = 1
MIGRATIONS: Dict[int, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
INCOMPATIBLE_APP_VERSIONS: List[Tuple[str, str]] = []

SECRET_SUFFIXES = ("_api_key", "_password", "_secret")


def _version_tuple(text: str) -> Tuple[int, ...]:
    parts = []
    for piece in str(text or "").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _is_secret(key: str) -> bool:
    return key.endswith(SECRET_SUFFIXES) or key == "api_key"


def build_export(settings: Dict[str, Any], app_version: str) -> Dict[str, Any]:
    return {
        "format": FORMAT,
        "settings_schema": SETTINGS_SCHEMA,
        "app_version": str(app_version),
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "settings": {k: v for k, v in settings.items() if not _is_secret(k)},
    }


def export_to(path: str | Path, settings: Dict[str, Any], app_version: str) -> None:
    Path(path).write_text(
        json.dumps(build_export(settings, app_version), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class ImportRefused(ValueError):
    """The file cannot be imported; the message says why, for the user."""


def check_compatibility(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an export and return its settings, migrated to SETTINGS_SCHEMA."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ImportRefused("This is not an RPGM Localizer settings file.")
    schema = doc.get("settings_schema")
    if not isinstance(schema, int):
        raise ImportRefused("The settings file has no schema version.")
    version = str(doc.get("app_version", ""))
    vt = _version_tuple(version)
    for first, last in INCOMPATIBLE_APP_VERSIONS:
        if _version_tuple(first) <= vt <= _version_tuple(last):
            raise ImportRefused(
                f"Settings exported by version {version} are not compatible with this version.")
    if schema < MIN_IMPORT_SCHEMA:
        raise ImportRefused(
            f"Settings from version {version} are too old to import (schema {schema}).")
    settings = doc.get("settings")
    if not isinstance(settings, dict):
        raise ImportRefused("The settings file has no settings in it.")
    while schema < SETTINGS_SCHEMA:
        step = MIGRATIONS.get(schema)
        if step is None:
            raise ImportRefused(f"No upgrade path from settings schema {schema}.")
        settings = step(dict(settings))
        schema += 1
    return settings


def merge_into(current: Dict[str, Any], incoming: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Apply known, type-compatible keys. Returns (merged, applied, skipped)."""
    merged = dict(current)
    applied: List[str] = []
    skipped: List[str] = []
    for key, value in incoming.items():
        if _is_secret(key):
            continue                               # never imported
        if key not in current:
            skipped.append(key)                    # unknown here (newer app?)
            continue
        old = current[key]
        ok = (
            old is None
            or isinstance(value, type(old))
            or (isinstance(old, (int, float)) and not isinstance(old, bool)
                and isinstance(value, (int, float)) and not isinstance(value, bool))
            or (isinstance(old, str) and isinstance(value, list))  # regex_blacklist
        )
        if not ok:
            skipped.append(key)
            continue
        if isinstance(old, int) and not isinstance(old, bool) and isinstance(value, float):
            value = int(value)
        merged[key] = value
        applied.append(key)
    return merged, applied, skipped


def import_from(path: str | Path, current: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], List[str], str]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ImportRefused(f"Could not read the file: {exc}") from exc
    settings = check_compatibility(doc)
    merged, applied, skipped = merge_into(current, settings)
    return merged, applied, skipped, str(doc.get("app_version", ""))
