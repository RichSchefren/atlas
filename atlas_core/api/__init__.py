"""Atlas API surfaces — MCP (Atlas-original tools), HTTP (FastAPI), gRPC
(Kumiho-compat scaffold).

Spec: 05 - Atlas Architecture & Schema § 2 (API Layer)
"""

from atlas_core.api.http_server import DEFAULT_HTTP_PORT, create_http_app
from atlas_core.api.mcp_server import (
    ATLAS_MCP_TOOLS,
    AtlasMCPServer,
    MCPTool,
    MCPToolResult,
)

__all__ = [
    "AtlasMCPServer",
    "ATLAS_MCP_TOOLS",
    "MCPTool",
    "MCPToolResult",
    "create_http_app",
    "DEFAULT_HTTP_PORT",
]
