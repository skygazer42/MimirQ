"""
RAG Tools module.

Provides MCP (Model Context Protocol) integration and
common tools for RAG workflows.
"""

from app.rag.tools.mcp_client import (
    MCPClient,
    MCPTool,
    MCPToolRegistry,
    ToolParameter,
    ToolResult,
    MCPError,
    MCPConnectionError,
    MCPToolError,
    get_mcp_client,
    get_mcp_registry,
    call_mcp_tool,
)
from app.rag.tools.mcp_tools import (
    search_documents,
    get_document_content,
    get_current_time,
    calculate,
    format_number,
    convert_units,
    count_text,
    extract_keywords,
    register_default_tools,
)

__all__ = [
    # Client
    "MCPClient",
    "MCPTool",
    "MCPToolRegistry",
    "ToolParameter",
    "ToolResult",
    "MCPError",
    "MCPConnectionError",
    "MCPToolError",
    "get_mcp_client",
    "get_mcp_registry",
    "call_mcp_tool",
    # Tools
    "search_documents",
    "get_document_content",
    "get_current_time",
    "calculate",
    "format_number",
    "convert_units",
    "count_text",
    "extract_keywords",
    "register_default_tools",
]
