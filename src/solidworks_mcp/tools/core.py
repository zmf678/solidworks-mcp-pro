"""Lifecycle and connection tools.

Thin MCP wrappers: validate arguments, delegate to the session and
normalise failures through :func:`solidworks_mcp.app._call`.
"""

from ..app import _call, _session, mcp


@mcp.tool()
async def get_status() -> dict:
    """Report whether SolidWorks is reachable, its revision, this server's version, and the active/current part."""
    return await _call(_session.get_status)


@mcp.tool()
async def new_part() -> dict:
    """Create a new empty part document; it becomes the current part."""
    return await _call(_session.new_part)
