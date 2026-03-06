"""bdr status tracking — writes a live JSON status file during script execution.

The status file lets external agents (LLMs, CI tools, etc.) observe what a
bdr test run is doing in real time.  By default it is written to
``~/.bdr/status.json`` and deleted automatically when the run finishes.

Opt-out in a script:
    no_status = true

Change the path in a script:
    status_file("./my-run.json")

Kill a stuck run from the CLI:
    bdr kill
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime

DEFAULT_STATUS_FILE = pathlib.Path.home() / ".bdr" / "status.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class StatusTracker:
    """Writes and maintains a JSON status file during a bdr script run."""

    def __init__(
        self,
        script_name: str,
        status_file: pathlib.Path | None = None,
        enabled: bool = True,
    ) -> None:
        self._path: pathlib.Path = (status_file or DEFAULT_STATUS_FILE).resolve()
        self._script = script_name
        self._pid = os.getpid()
        self._started: str = _now()
        self._actions: list[dict] = []
        self._enabled = enabled

    # ------------------------------------------------------------------
    # Configuration (called from interpreter when settings are parsed)
    # ------------------------------------------------------------------

    def disable(self) -> None:
        """Opt out of status file writing and remove any existing file."""
        self._enabled = False
        try:
            self._path.unlink(missing_ok=True)
        except Exception:
            pass

    def set_path(self, new_path: pathlib.Path) -> None:
        """Change the output path. Cleans up the old file if already written."""
        if not self._enabled:
            return
        old_path = self._path
        self._path = new_path.resolve()
        try:
            old_path.unlink(missing_ok=True)
        except Exception:
            pass
        self._write()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Write the initial status file (called before interpreter.run)."""
        if not self._enabled:
            return
        self._write()

    def log_action(self, line_number: int, raw: str) -> None:
        """Append a completed action to the status file."""
        if not self._enabled:
            return
        self._actions.append({
            "time": _now(),
            "line": line_number,
            "action": raw.strip(),
        })
        self._write()

    def finish(self) -> None:
        """Remove the status file — run completed (success or error)."""
        if not self._enabled:
            return
        try:
            self._path.unlink(missing_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "pid": self._pid,
                "script": self._script,
                "started": self._started,
                "status": "running",
                "actions": self._actions,
            }
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass  # never crash the script because of status tracking
