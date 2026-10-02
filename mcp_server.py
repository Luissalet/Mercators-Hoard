"""Small stdio MCP bridge: the publishing plan, Cults catalogue and sales tools of agent_tools.py."""

from __future__ import annotations

import json
import sqlite3
import sys

from agent_tools import call_tool, tool_catalog


def handle(request: dict) -> dict | None:
    if "id" not in request:
        return None
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-03-26"),
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "mercator-hoard", "version": "1.1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_catalog()}
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            value = call_tool(name, args)
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
        except (ValueError, TypeError, OSError, KeyError, sqlite3.Error) as error:
            result = {"isError": True, "content": [{"type": "text", "text": str(error)}]}
    else:
        return {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "Método desconocido"}}
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def main() -> None:
    # MCP stdio is UTF-8 even when a Windows console defaults to cp1252.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        try:
            answer = handle(json.loads(line))
        except (ValueError, TypeError) as error:
            answer = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(error)}}
        if answer is not None:
            print(json.dumps(answer, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
