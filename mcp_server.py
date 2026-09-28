"""Small read-only stdio MCP bridge for local Cults catalogue and sales queries."""

from __future__ import annotations

import json
import sys

from mercator import catalog_query, sales_query


def schema(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "additionalProperties": False}


STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
INTEGER = {"type": "integer"}
TOOLS = [
    {"name": "mercator_catalog", "description": "Buscar fichas locales de Cults por nombre y revisar cuáles carecen de etiquetas o ficha. Solo lectura; sinónimos: catálogo, modelos, productos, tags.",
     "inputSchema": schema({"query": STRING, "untagged": BOOLEAN, "missing": BOOLEAN, "offset": INTEGER, "limit": INTEGER}),
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "mercator_sales", "description": "Consultar ventas de Cults importadas por producto, con totales separados por moneda. Solo lectura; sinónimos: ventas, ingresos, qué vende.",
     "inputSchema": schema({"product": STRING, "limit": INTEGER}),
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
]


def handle(request: dict) -> dict | None:
    if "id" not in request:
        return None
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-03-26"),
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "mercator-hoard", "version": "1.0.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if not isinstance(args, dict):
                raise ValueError("Argumentos no válidos")
            if name == "mercator_catalog":
                value = catalog_query(**args)
            elif name == "mercator_sales":
                value = sales_query(**args)
            else:
                raise ValueError("Herramienta desconocida")
            result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
        except (ValueError, TypeError, OSError) as error:
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
