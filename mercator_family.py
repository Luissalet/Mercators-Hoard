"""Mercator's side of the Hoard family contract (events, calls through the hub, agenda, references).

The shared library is vendored in ``hoard_link/``. Its package ``__init__`` needs ``httpx`` (the model
backend), which Mercator does not otherwise use; the modules this file needs (``family``, ``fam_agenda``,
``fam_refs``) are standard library only. They are loaded under a private package name whose ``__path__``
is the vendored folder, so the ``__init__`` never runs and Mercator keeps running on the standard library.
Everything degrades quietly when the hub is not there.
"""

from __future__ import annotations

import importlib
import secrets
import sys
import threading
import types
from pathlib import Path
from typing import Any, Callable

APP_ID = "mercator"
_PKG = "_mercator_hoard_link"
_HERE = Path(__file__).resolve().parent

family: Any = None
fam_agenda: Any = None
fam_refs: Any = None


def _load() -> None:
    global family, fam_agenda, fam_refs
    if family is not None:
        return
    folder = _HERE / "hoard_link"
    if not folder.is_dir():
        return
    if _PKG not in sys.modules:
        stub = types.ModuleType(_PKG)
        stub.__path__ = [str(folder)]  # type: ignore[attr-defined]
        sys.modules[_PKG] = stub
    try:
        family = importlib.import_module(_PKG + ".family")
        fam_agenda = importlib.import_module(_PKG + ".fam_agenda")
        fam_refs = importlib.import_module(_PKG + ".fam_refs")
    except Exception:  # noqa: BLE001 - a broken vendored copy must not stop the dashboard
        family = fam_agenda = fam_refs = None


_load()


def available() -> bool:
    return family is not None


def configure(data_dir: Path | str) -> str:
    """Tell the library who this app is and where its token lives; create the token when missing. Returns the token file."""
    if family is None:
        return ""
    token_file = Path(data_dir) / "mcp-token"
    try:
        if not token_file.is_file() or not token_file.read_text(encoding="utf-8-sig").strip():
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            try:
                token_file.chmod(0o600)
            except OSError:
                pass
    except OSError:
        pass
    family.configure(APP_ID, str(data_dir), token_file=str(token_file))
    return str(token_file)


def emit(event_type: str, data: dict | None = None) -> bool:
    """Fire-and-forget event on the family bus (ids and short titles only)."""
    if family is None:
        return False
    try:
        return bool(family.emit(event_type, data or {}))
    except Exception:  # noqa: BLE001
        return False


def call(app: str, tool: str, arguments: dict | None = None, timeout: float = 60.0) -> dict:
    """Call a tool of another app through the hub: ``{ok, result|error, ...}``; never raises."""
    if family is None:
        return {"ok": False, "app": app, "tool": tool, "error": "family library not available"}
    try:
        return family.call(app, tool, arguments or {}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "app": app, "tool": tool, "error": f"{type(exc).__name__}: {exc}"}


def link_ref(from_uri: str, to_uri: str, rel: str = "related", from_label: str = "", to_label: str = "") -> None:
    """Record a cross-app reference in a daemon thread (a slow hub never holds a request)."""
    if fam_refs is None or not (from_uri.startswith("hoard://") and to_uri.startswith("hoard://")):
        return

    def run() -> None:
        try:
            fam_refs.link(from_uri, to_uri, rel, from_label=from_label, to_label=to_label)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=run, name="mercator-ref", daemon=True).start()


def record_call(tool: str, ok: bool, ms: int, caller: str = "", error: str = "") -> None:
    if family is not None:
        try:
            family.record_call(tool, ok, ms, caller=caller, error=error)
        except Exception:  # noqa: BLE001
            pass


def health_block() -> dict:
    return family.health_block() if family is not None else {}


def bearer_ok(authorization: str) -> bool:
    """True when the ``Authorization`` header carries this app's own token (read from the file at call time)."""
    if family is None or fam_agenda is None:
        return False
    header = authorization or ""
    given = header[7:].strip() if header.lower().startswith("bearer ") else ""
    return bool(fam_agenda.token_ok(given))


def agenda(provider: Callable[..., Any], date_from: str | None, date_to: str | None, sphere: str = "") -> dict:
    if fam_agenda is None:
        return {"ok": False, "error": "family library not available", "items": []}
    return fam_agenda.answer(provider, date_from, date_to, sphere)
