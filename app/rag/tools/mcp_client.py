"""
MCP (Model Context Protocol) client for external tool integration.

Provides a client for connecting to MCP servers and
dynamically loading tools for use in RAG workflows.

Usage:
    from app.rag.tools.mcp_client import MCPClient

    client = MCPClient("http://localhost:8080")
    tools = await client.list_tools()
    result = await client.call_tool("search", {"query": "example"})
"""


import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.tools.mcp_client")


# Configuration
MCP_ENABLED = getattr(settings, "MCP_ENABLED", False)
MCP_SERVER_URL = getattr(settings, "MCP_SERVER_URL", "")
MCP_TIMEOUT = getattr(settings, "MCP_TIMEOUT", 30)
MCP_MAX_RETRIES = getattr(settings, "MCP_MAX_RETRIES", 3)


class MCPError(Exception):
    """Base exception for MCP errors."""
    pass


class MCPConnectionError(MCPError):
    """Connection error to MCP server."""
    pass


class MCPToolError(MCPError):
    """Error executing MCP tool."""
    pass


class ToolType(str, Enum):
    """Types of MCP tools."""
    FUNCTION = "function"
    RESOURCE = "resource"
    PROMPT = "prompt"


@dataclass
class ToolParameter:
    """Tool parameter definition."""
    name: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    enum: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolParameter":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "string"),
            description=data.get("description", ""),
            required=data.get("required", False),
            default=data.get("default"),
            enum=data.get("enum"),
        )


@dataclass
class MCPTool:
    """MCP tool definition."""
    name: str
    description: str
    type: ToolType = ToolType.FUNCTION
    parameters: list[ToolParameter] = field(default_factory=list)
    returns: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPTool":
        params = [
            ToolParameter.from_dict(p)
            for p in data.get("parameters", [])
        ]
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            type=ToolType(data.get("type", "function")),
            parameters=params,
            returns=data.get("returns"),
            metadata=data.get("metadata", {}),
        )

    def to_langchain_schema(self) -> dict[str, Any]:
        """Convert to LangChain tool schema format."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {"type": param.type, "description": param.description}
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


@dataclass
class ToolResult:
    """Result from MCP tool execution."""
    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """
    Client for MCP (Model Context Protocol) servers.

    Provides methods for discovering and executing tools
    from MCP-compatible servers.
    """

    def __init__(
        self,
        server_url: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
    ):
        """
        Initialize the MCP client.

        Args:
            server_url: MCP server URL
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            headers: Additional HTTP headers
        """
        self.server_url = server_url or MCP_SERVER_URL
        self.timeout = timeout
        self.max_retries = max_retries
        self.headers = headers or {}
        self._tools_cache: list[MCPTool] | None = None
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make HTTP request to MCP server."""
        if not self.server_url:
            raise MCPConnectionError("MCP server URL not configured")

        client = self._get_client()
        url = urljoin(self.server_url, endpoint)

        for attempt in range(self.max_retries):
            try:
                if method.upper() == "GET":
                    response = await client.get(url, params=data)
                else:
                    response = await client.post(url, json=data)

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.error("MCP HTTP error: %s", e)
                if attempt == self.max_retries - 1:
                    raise MCPError(f"HTTP error: {e}") from e
            except httpx.RequestError as e:
                logger.error("MCP request error: %s", e)
                if attempt == self.max_retries - 1:
                    raise MCPConnectionError(f"Connection error: {e}") from e

            # Wait before retry
            await asyncio.sleep(2 ** attempt)

        raise MCPError("Max retries exceeded")

    async def list_tools(
        self,
        refresh: bool = False,
    ) -> list[MCPTool]:
        """
        List available tools from MCP server.

        Args:
            refresh: Force refresh cache

        Returns:
            List of available tools
        """
        if self._tools_cache is not None and not refresh:
            return self._tools_cache

        try:
            response = await self._request("GET", "/tools")
            tools = [MCPTool.from_dict(t) for t in response.get("tools", [])]
            self._tools_cache = tools
            logger.info("Loaded %d tools from MCP server", len(tools))
            return tools
        except Exception as e:
            logger.error("Failed to list MCP tools: %s", e)
            return []

    async def get_tool(self, name: str) -> MCPTool | None:
        """
        Get a specific tool by name.

        Args:
            name: Tool name

        Returns:
            Tool definition or None
        """
        tools = await self.list_tools()
        for tool in tools:
            if tool.name == name:
                return tool
        return None

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolResult:
        """
        Execute a tool on the MCP server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        try:
            response = await self._request(
                "POST",
                "/tools/execute",
                data={
                    "name": name,
                    "arguments": arguments or {},
                },
            )

            return ToolResult(
                success=response.get("success", True),
                data=response.get("data"),
                error=response.get("error"),
                metadata=response.get("metadata", {}),
            )

        except MCPError as e:
            return ToolResult(
                success=False,
                error=str(e),
            )

    async def list_resources(self) -> list[dict[str, Any]]:
        """List available resources from MCP server."""
        try:
            response = await self._request("GET", "/resources")
            return response.get("resources", [])
        except Exception as e:
            logger.error("Failed to list MCP resources: %s", e)
            return []

    async def read_resource(
        self,
        uri: str,
    ) -> dict[str, Any] | None:
        """
        Read a resource from MCP server.

        Args:
            uri: Resource URI

        Returns:
            Resource content
        """
        try:
            response = await self._request(
                "GET",
                "/resources/read",
                data={"uri": uri},
            )
            return response
        except Exception as e:
            logger.error("Failed to read MCP resource: %s", e)
            return None

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List available prompts from MCP server."""
        try:
            response = await self._request("GET", "/prompts")
            return response.get("prompts", [])
        except Exception as e:
            logger.error("Failed to list MCP prompts: %s", e)
            return []

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Get a prompt from MCP server.

        Args:
            name: Prompt name
            arguments: Prompt arguments

        Returns:
            Rendered prompt text
        """
        try:
            response = await self._request(
                "POST",
                "/prompts/get",
                data={
                    "name": name,
                    "arguments": arguments or {},
                },
            )
            return response.get("text")
        except Exception as e:
            logger.error("Failed to get MCP prompt: %s", e)
            return None

    def to_langchain_tools(self, tools: list[MCPTool]) -> list[dict[str, Any]]:
        """
        Convert MCP tools to LangChain tool format.

        Args:
            tools: MCP tools

        Returns:
            LangChain tool schemas
        """
        return [tool.to_langchain_schema() for tool in tools]


# ============================================================================
# Tool Registry
# ============================================================================


class MCPToolRegistry:
    """
    Registry for MCP tools with local fallback support.

    Manages both remote MCP tools and local tool implementations.
    """

    def __init__(self, mcp_client: MCPClient | None = None):
        """
        Initialize the registry.

        Args:
            mcp_client: MCP client instance
        """
        self.mcp_client = mcp_client
        self._local_tools: dict[str, Callable] = {}
        self._tool_schemas: dict[str, MCPTool] = {}

    def register(
        self,
        name: str,
        func: Callable,
        description: str = "",
        parameters: list[ToolParameter] | None = None,
    ) -> "MCPToolRegistry":
        """
        Register a local tool.

        Args:
            name: Tool name
            func: Tool function
            description: Tool description
            parameters: Tool parameters

        Returns:
            Self for chaining
        """
        self._local_tools[name] = func
        self._tool_schemas[name] = MCPTool(
            name=name,
            description=description,
            parameters=parameters or [],
        )
        return self

    def unregister(self, name: str) -> bool:
        """Unregister a local tool."""
        if name in self._local_tools:
            del self._local_tools[name]
            del self._tool_schemas[name]
            return True
        return False

    async def list_tools(self) -> list[MCPTool]:
        """List all available tools (local + remote)."""
        tools = list(self._tool_schemas.values())

        if self.mcp_client:
            try:
                remote_tools = await self.mcp_client.list_tools()
                tools.extend(remote_tools)
            except Exception as e:
                logger.warning("Failed to list remote tools: %s", e)

        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolResult:
        """
        Call a tool by name.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        arguments = arguments or {}

        chain = None
        if bool(getattr(settings, "MIDDLEWARE_ENABLED", True)):
            from app.rag.middleware import ToolMiddlewareChain

            chain = ToolMiddlewareChain()
        tool_state: dict[str, Any] = {
            "tool_name": name,
            "arguments": arguments,
            "result": None,
            "error": None,
            "success": None,
            "metadata": {},
        }

        if chain:
            tool_state = chain.run_before(tool_state)

        async def _execute(state: dict[str, Any]) -> dict[str, Any]:
            tool_name = str(state.get("tool_name") or "")
            tool_args = state.get("arguments") or {}

            # Try local first
            if tool_name in self._local_tools:
                state["metadata"] = {**(state.get("metadata") or {}), "backend": "local"}
                func = self._local_tools[tool_name]
                result = await func(**tool_args) if asyncio.iscoroutinefunction(func) else func(**tool_args)
                state["success"] = True
                state["result"] = result
                return state

            # Fall back to remote
            if self.mcp_client:
                state["metadata"] = {**(state.get("metadata") or {}), "backend": "remote"}
                res = await self.mcp_client.call_tool(tool_name, tool_args)
                state["success"] = bool(res.success)
                state["result"] = res.data
                state["error"] = res.error
                state["metadata"] = {**(state.get("metadata") or {}), **(res.metadata or {})}
                return state

            state["success"] = False
            state["error"] = f"Tool not found: {tool_name}"
            return state

        try:
            if chain:
                wrapped = chain.wrap_call(_execute)
                tool_state = await wrapped(tool_state) if asyncio.iscoroutinefunction(wrapped) else wrapped(tool_state)
            else:
                tool_state = await _execute(tool_state)
        except Exception as exc:  # noqa: BLE001
            tool_state["success"] = False
            tool_state["error"] = str(exc)[:500]

        if chain:
            tool_state = chain.run_after(tool_state)

        return ToolResult(
            success=bool(tool_state.get("success")),
            data=tool_state.get("result"),
            error=tool_state.get("error"),
            metadata=tool_state.get("metadata") or {},
        )


# ============================================================================
# Convenience Functions
# ============================================================================


_default_client: MCPClient | None = None
_default_registry: MCPToolRegistry | None = None


def get_mcp_client() -> MCPClient:
    """Get or create the default MCP client."""
    global _default_client
    if _default_client is None:
        _default_client = MCPClient()
    return _default_client


def get_mcp_registry() -> MCPToolRegistry:
    """Get or create the default MCP registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = MCPToolRegistry(get_mcp_client())
    return _default_registry


async def call_mcp_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
) -> ToolResult:
    """Call an MCP tool using the default registry."""
    registry = get_mcp_registry()
    return await registry.call_tool(name, arguments)
