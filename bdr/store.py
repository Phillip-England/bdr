"""Managed storage for reusable .bdr scripts."""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
import re


_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ScriptNameError(ValueError):
    """Raised when a managed script name is invalid."""


@dataclass(frozen=True)
class ManagedScript:
    """Metadata for a script stored in the managed library."""

    name: str
    path: pathlib.Path
    size: int
    updated_at: str


def data_root() -> pathlib.Path:
    """Return the OS-appropriate data root for bdr-managed assets."""
    override = os.environ.get("BDR_DATA_HOME")
    if override:
        return pathlib.Path(override).expanduser().resolve()

    home = pathlib.Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "bdr"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return pathlib.Path(base) / "bdr"
        return home / "AppData" / "Roaming" / "bdr"

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return pathlib.Path(xdg) / "bdr"
    return home / ".local" / "share" / "bdr"


def script_library_dir() -> pathlib.Path:
    """Return the directory that stores managed .bdr scripts."""
    return data_root() / "scripts"


def ensure_script_library_dir() -> pathlib.Path:
    """Create the managed script library if needed and return it."""
    target = script_library_dir()
    target.mkdir(parents=True, exist_ok=True)
    return target


def normalize_script_name(name: str) -> str:
    """Normalize a user-provided name to a managed script key."""
    cleaned = name.strip()
    if not cleaned:
        raise ScriptNameError("Script name cannot be empty.")
    if "/" in cleaned or "\\" in cleaned:
        raise ScriptNameError("Script name must not contain path separators.")
    if cleaned.lower().endswith(".bdr"):
        cleaned = cleaned[:-4]
    if not cleaned:
        raise ScriptNameError("Script name cannot be only '.bdr'.")
    if not _VALID_NAME.fullmatch(cleaned):
        raise ScriptNameError(
            "Script name may contain only letters, numbers, dots, dashes, and underscores,"
            " and it must start with a letter or number."
        )
    return cleaned


def script_path(name: str) -> pathlib.Path:
    """Resolve a managed script name to its library path."""
    normalized = normalize_script_name(name)
    return ensure_script_library_dir() / f"{normalized}.bdr"


def list_scripts() -> list[ManagedScript]:
    """List scripts currently stored in the managed library."""
    root = ensure_script_library_dir()
    results: list[ManagedScript] = []
    for path in sorted(root.glob("*.bdr")):
        stat = path.stat()
        updated = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        results.append(
            ManagedScript(
                name=path.stem,
                path=path,
                size=stat.st_size,
                updated_at=updated,
            )
        )
    return sorted(results, key=lambda item: item.name.lower())


def read_script(name: str) -> str:
    """Read a managed script by name."""
    return script_path(name).read_text(encoding="utf-8")


def write_script(name: str, content: str) -> pathlib.Path:
    """Write a managed script and return the path."""
    target = script_path(name)
    target.write_text(content, encoding="utf-8")
    return target


def import_script(source: pathlib.Path, name: str) -> pathlib.Path:
    """Copy an external script into the managed library under *name*."""
    target = script_path(name)
    shutil.copy2(source, target)
    return target
