"""
RAG Tools module.

Provides MCP (Model Context Protocol) integration and
common tools for RAG workflows.
"""

from app.rag.tools.mcp_client import (
    MCPClient,
    MCPConnectionError,
    MCPError,
    MCPTool,
    MCPToolError,
    MCPToolRegistry,
    ToolParameter,
    ToolResult,
    call_mcp_tool,
    get_mcp_client,
    get_mcp_registry,
)
from app.rag.tools.mcp_tools import (
    calculate,
    convert_units,
    count_text,
    extract_keywords,
    format_number,
    get_current_time,
    get_document,
    get_document_content,
    get_document_structure,
    get_page_content,
    register_default_tools,
    search_documents,
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
    "get_document",
    "get_document_content",
    "get_document_structure",
    "get_page_content",
    "get_current_time",
    "calculate",
    "format_number",
    "convert_units",
    "count_text",
    "extract_keywords",
    "register_default_tools",
]
