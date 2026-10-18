"""On-demand stdio entry point for the read-only Tracky MCP server."""

from __future__ import annotations

from tracky_mcp.storage import SQLiteMeasurementStore

from . import create_server


def main() -> None:
    """Run one on-demand history server using the XDG SQLite database."""

    with SQLiteMeasurementStore(read_only=True) as store:
        create_server(store).run(transport="stdio")


if __name__ == "__main__":
    main()
