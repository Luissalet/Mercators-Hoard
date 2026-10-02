"""Test helpers: the real stdio bridge (``mcp_server.py``) talking to a Mercator server running in this process."""
from __future__ import annotations

import asyncio
import os
import sys
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import mercator

ROOT = Path(mercator.__file__).resolve().parent

try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


@contextmanager
def running_server() -> Iterator[int]:
    """The dashboard's HTTP server on a free port (uses whatever ``mercator.DATA`` / ``mercator.DB`` are patched to)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), mercator.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def bridge_calls(port: int, data_dir: Path | str, calls: list[tuple[str, dict]], extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    """Start ``mcp_server.py`` as a child process, list the tools and run ``calls`` through it. Returns ``{"tools": [...], "results": [...]}``
    where every result is the CallToolResult of the call, in order. Autostart is off: the bridge only talks to ``port``."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "MERCATOR_URL": f"http://127.0.0.1:{port}", "MERCATOR_DATA_DIR": str(data_dir),
           "MERCATOR_BRIDGE_AUTOSTART": "0", "HOARD_EVENTS": "0", **(extra_env or {})}
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")], env=env, cwd=str(ROOT))

    async def run() -> dict[str, Any]:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                results = [await session.call_tool(name, arguments) for name, arguments in calls]
                return {"tools": tools, "results": results, "server": session}

    return asyncio.run(asyncio.wait_for(run(), timeout=60))


def dump(model: Any) -> dict[str, Any]:
    """An mcp model as the wire's camelCase dict (mcp 1.x and 2.x name the attributes differently)."""
    return model.model_dump(by_alias=True)
