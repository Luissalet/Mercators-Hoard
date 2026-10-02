"""Mercator's side of the Hoard family contract (events, calls through the hub, agenda, references).

The shared library is vendored in ``hoard_link/`` (standard library only: importing it needs no ``httpx``). Everything degrades
quietly when the hub is not there."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from hoard_link import fam_agenda, fam_refs, family
from hoard_link.tokens import check_bearer, read_or_create_token, read_token

APP_ID = "mercator"


def configure(data_dir: Path | str) -> str:
    """Tell the library who this app is and where its token lives; create the token when missing (it is kept across restarts).
    Returns the token file."""
    token_file = Path(data_dir) / "mcp-token"
    try:
        read_or_create_token(token_file)
    except OSError:
        pass
    family.configure(APP_ID, str(data_dir), token_file=str(token_file))
    return str(token_file)


def emit(event_type: str, data: dict | None = None) -> bool:
    """Fire-and-forget event on the family bus (ids and short titles only)."""
    try:
        return bool(family.emit(event_type, data or {}))
    except Exception:  # noqa: BLE001
        return False


def call(app: str, tool: str, arguments: dict | None = None, timeout: float = 60.0) -> dict:
    """Call a tool of another app through the hub: ``{ok, result|error, ...}``; never raises."""
    try:
        return family.call(app, tool, arguments or {}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "app": app, "tool": tool, "error": f"{type(exc).__name__}: {exc}"}


def link_ref(from_uri: str, to_uri: str, rel: str = "related", from_label: str = "", to_label: str = "") -> None:
    """Record a cross-app reference in a daemon thread (a slow hub never holds a request)."""
    if not (from_uri.startswith("hoard://") and to_uri.startswith("hoard://")):
        return

    def run() -> None:
        try:
            fam_refs.link(from_uri, to_uri, rel, from_label=from_label, to_label=to_label)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=run, name="mercator-ref", daemon=True).start()


def record_call(tool: str, ok: bool, ms: int, caller: str = "", error: str = "") -> None:
    try:
        family.record_call(tool, ok, ms, caller=caller, error=error)
    except Exception:  # noqa: BLE001
        pass


def health_block() -> dict:
    return family.health_block()


def bearer_ok(authorization: str) -> bool:
    """True when the ``Authorization`` header carries this app's own token (read from the file at call time, so a rotated token works)."""
    path = str(family.status().get("token_file") or "")
    return bool(path) and check_bearer(authorization or "", read_token(path, min_len=16))


def agenda(provider: Callable[..., Any], date_from: str | None, date_to: str | None, sphere: str = "") -> dict:
    return fam_agenda.answer(provider, date_from, date_to, sphere)
