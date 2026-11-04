from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.rag.tools.mcp_client import MCPToolRegistry
from app.rag.tools.mcp_tools import register_default_tools


class ExecuteToolRequest(BaseModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


def create_mcp_registry() -> MCPToolRegistry:
    registry = MCPToolRegistry(mcp_client=None)
    register_default_tools(registry)
    return registry


def create_mcp_app() -> FastAPI:
    app = FastAPI(title="MimirQ MCP Server")
    registry = create_mcp_registry()

    @app.get("/tools")
    async def list_tools() -> dict[str, Any]:
        tools = await registry.list_tools()
        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "type": str(tool.type.value),
                    "parameters": [
                        {
                            "name": param.name,
                            "type": param.type,
                            "description": param.description,
                            "required": bool(param.required),
                            "default": param.default,
                            "enum": param.enum,
                        }
                        for param in tool.parameters
                    ],
                }
                for tool in tools
            ]
        }

    @app.post("/tools/execute")
    async def execute_tool(body: ExecuteToolRequest) -> dict[str, Any]:
        result = await registry.call_tool(body.name, body.arguments)
        return {
            "success": bool(result.success),
            "data": result.data,
            "error": result.error,
            "metadata": dict(result.metadata or {}),
        }

    return app


__all__ = ["create_mcp_app", "create_mcp_registry"]
