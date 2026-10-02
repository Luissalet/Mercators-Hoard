"""Stdio MCP bridge for Mercator's Hoard: the family's ``CatalogBridge`` pointed at this app.

The tool list comes from ``GET /api/agent/tools`` and every call is proxied to the running server (``POST /api/agent/call``) with the
Bearer token from ``<data>/mcp-token``. When nothing answers it starts the server (``python -m mercator``, detached);
MERCATOR_BRIDGE_AUTOSTART=0 turns that off. MERCATOR_URL, MERCATOR_PORT, MERCATOR_DATA_DIR, MERCATOR_TOKEN and MERCATOR_TOKEN_FILE
tell it where the server and its token are. Needs the ``mcp`` package (``pip install -r requirements.txt``).
"""

from __future__ import annotations

from hoard_link.bridge import CatalogBridge


def make_bridge() -> CatalogBridge:
    return CatalogBridge(app="mercator", service="mercator-hoard", package="mercator", default_port=5195, data_dir_env="MERCATOR_DATA_DIR",
                         title="Mercator's Hoard", root=__file__)


def main() -> None:
    make_bridge().run_bridge()


if __name__ == "__main__":
    main()
