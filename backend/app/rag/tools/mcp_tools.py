"""
MCP tools for RAG workflows.

Provides common tools that can be used with MCP
or directly in RAG pipelines.

Usage:
    from app.rag.tools.mcp_tools import (
        search_documents,
        get_document_content,
        calculate,
        get_current_time,
    )
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.rag.tools.mcp_client import (
    MCPTool,
    MCPToolRegistry,
    ToolParameter,
    ToolResult,
    get_mcp_registry,
)

logger = logging.getLogger(__name__)

# Configuration
MCP_ENABLED = getattr(settings, "MCP_ENABLED", False)


# ============================================================================
# Document Tools
# ============================================================================


async def search_documents(
    query: str,
    top_k: int = 5,
    dataset_id: Optional[str] = None,
    filter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Search documents in the knowledge base.

    Args:
        query: Search query
        top_k: Number of results
        dataset_id: Filter by dataset
        filter: Additional metadata filters

    Returns:
        Search results
    """
    try:
        from app.rag.retriever import hybrid_retriever

        retriever = hybrid_retriever.model_copy(
            update={
                "k": int(top_k or 5),
                "metadata_filter": filter,
            }
        )
        documents = await retriever.ainvoke(query)

        results = []
        for doc in documents:
            content = doc.page_content if hasattr(doc, "page_content") else doc.get("content", "")
            metadata = doc.metadata if hasattr(doc, "metadata") else doc.get("metadata", {})
            results.append({
                "content": content[:500] + "..." if len(content) > 500 else content,
                "source": metadata.get("source", "unknown"),
                "score": metadata.get("score", 0),
            })

        return {
            "query": query,
            "count": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error("Document search failed: %s", e)
        return {
            "query": query,
            "count": 0,
            "results": [],
            "error": str(e),
        }


async def get_document_content(
    document_id: str,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get full content of a document.

    Args:
        document_id: Document ID
        page: Optional page number

    Returns:
        Document content
    """
    try:
        from app.storage.vector.factory import get_vector_store

        store = get_vector_store()
        # This is a placeholder - actual implementation depends on storage
        return {
            "document_id": document_id,
            "content": "Document content retrieval not implemented",
            "page": page,
        }
    except Exception as e:
        logger.error("Failed to get document: %s", e)
        return {
            "document_id": document_id,
            "error": str(e),
        }


# ============================================================================
# Utility Tools
# ============================================================================


def get_current_time(
    format: str = "%Y-%m-%d %H:%M:%S",
    timezone: Optional[str] = None,
) -> Dict[str, str]:
    """
    Get current date and time.

    Args:
        format: DateTime format string
        timezone: Optional timezone name

    Returns:
        Formatted time information
    """
    now = datetime.now()

    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekdays_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    return {
        "datetime": now.strftime(format),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekdays[now.weekday()],
        "weekday_cn": weekdays_cn[now.weekday()],
        "timestamp": str(int(now.timestamp())),
    }


def calculate(expression: str) -> Dict[str, Any]:
    """
    Safely evaluate a mathematical expression.

    Args:
        expression: Mathematical expression

    Returns:
        Calculation result
    """
    # Only allow safe operations
    allowed_names = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "pi": math.pi,
        "e": math.e,
    }

    # Remove dangerous characters
    safe_expr = re.sub(r"[^0-9+\-*/().,%^a-z ]", "", expression.lower())

    try:
        # Replace ^ with **
        safe_expr = safe_expr.replace("^", "**")

        result = eval(safe_expr, {"__builtins__": {}}, allowed_names)

        return {
            "expression": expression,
            "result": result,
            "success": True,
        }
    except Exception as e:
        return {
            "expression": expression,
            "result": None,
            "success": False,
            "error": str(e),
        }


def format_number(
    number: float,
    decimals: int = 2,
    thousands_separator: bool = True,
) -> Dict[str, str]:
    """
    Format a number for display.

    Args:
        number: Number to format
        decimals: Decimal places
        thousands_separator: Use thousands separator

    Returns:
        Formatted number
    """
    try:
        if thousands_separator:
            formatted = f"{number:,.{decimals}f}"
        else:
            formatted = f"{number:.{decimals}f}"

        return {
            "original": str(number),
            "formatted": formatted,
            "success": True,
        }
    except Exception as e:
        return {
            "original": str(number),
            "formatted": str(number),
            "success": False,
            "error": str(e),
        }


def convert_units(
    value: float,
    from_unit: str,
    to_unit: str,
) -> Dict[str, Any]:
    """
    Convert between units.

    Args:
        value: Value to convert
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Conversion result
    """
    # Unit conversion factors (to base unit)
    conversions = {
        # Length (to meters)
        "m": 1,
        "km": 1000,
        "cm": 0.01,
        "mm": 0.001,
        "mi": 1609.34,
        "ft": 0.3048,
        "in": 0.0254,
        # Weight (to kilograms)
        "kg": 1,
        "g": 0.001,
        "mg": 0.000001,
        "lb": 0.453592,
        "oz": 0.0283495,
        # Temperature (special handling)
        "c": "celsius",
        "f": "fahrenheit",
        "k": "kelvin",
    }

    from_unit = from_unit.lower()
    to_unit = to_unit.lower()

    # Handle temperature separately
    if from_unit in ("c", "f", "k") or to_unit in ("c", "f", "k"):
        try:
            result = _convert_temperature(value, from_unit, to_unit)
            return {
                "value": value,
                "from_unit": from_unit,
                "to_unit": to_unit,
                "result": result,
                "success": True,
            }
        except Exception as e:
            return {
                "value": value,
                "from_unit": from_unit,
                "to_unit": to_unit,
                "success": False,
                "error": str(e),
            }

    if from_unit not in conversions or to_unit not in conversions:
        return {
            "value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "success": False,
            "error": "Unknown unit",
        }

    # Convert through base unit
    base_value = value * conversions[from_unit]
    result = base_value / conversions[to_unit]

    return {
        "value": value,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "result": result,
        "success": True,
    }


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """Convert temperature between units."""
    # Convert to Celsius first
    if from_unit == "c":
        celsius = value
    elif from_unit == "f":
        celsius = (value - 32) * 5 / 9
    elif from_unit == "k":
        celsius = value - 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")

    # Convert from Celsius to target
    if to_unit == "c":
        return celsius
    elif to_unit == "f":
        return celsius * 9 / 5 + 32
    elif to_unit == "k":
        return celsius + 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {to_unit}")


# ============================================================================
# Text Tools
# ============================================================================


def count_text(text: str) -> Dict[str, int]:
    """
    Count characters, words, and lines in text.

    Args:
        text: Text to analyze

    Returns:
        Count statistics
    """
    lines = text.split("\n")
    words = text.split()

    return {
        "characters": len(text),
        "characters_no_spaces": len(text.replace(" ", "").replace("\n", "")),
        "words": len(words),
        "lines": len(lines),
        "paragraphs": len([p for p in text.split("\n\n") if p.strip()]),
    }


def extract_keywords(
    text: str,
    max_keywords: int = 10,
) -> Dict[str, Any]:
    """
    Extract keywords from text (simple frequency-based).

    Args:
        text: Text to analyze
        max_keywords: Maximum keywords to return

    Returns:
        Extracted keywords
    """
    # Simple word frequency
    words = re.findall(r"\b[a-zA-Z\u4e00-\u9fa5]+\b", text.lower())

    # Filter stop words (basic)
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "must", "shall",
        "can", "need", "dare", "ought", "used", "to", "of", "in",
        "for", "on", "with", "at", "by", "from", "as", "into", "through",
        "during", "before", "after", "above", "below", "between", "under",
        "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "few", "more", "most",
        "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "and", "but",
        "if", "or", "because", "until", "while", "although", "though",
        "的", "是", "在", "有", "和", "与", "了", "不", "人", "我",
        "他", "她", "它", "们", "这", "那", "就", "也", "都", "而",
        "及", "着", "或", "把", "被", "让", "给", "到", "从", "向",
    }

    filtered = [w for w in words if w not in stop_words and len(w) > 1]

    # Count frequencies
    freq = {}
    for word in filtered:
        freq[word] = freq.get(word, 0) + 1

    # Sort by frequency
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    keywords = sorted_words[:max_keywords]

    return {
        "keywords": [{"word": w, "count": c} for w, c in keywords],
        "total_words": len(words),
        "unique_words": len(set(words)),
    }


# ============================================================================
# Tool Registration
# ============================================================================


def register_default_tools(registry: Optional[MCPToolRegistry] = None) -> MCPToolRegistry:
    """
    Register default tools with the registry.

    Args:
        registry: Optional registry instance

    Returns:
        Registry with tools registered
    """
    if registry is None:
        registry = get_mcp_registry()

    # Document tools
    registry.register(
        name="search_documents",
        func=search_documents,
        description="Search documents in the knowledge base",
        parameters=[
            ToolParameter(name="query", type="string", description="Search query", required=True),
            ToolParameter(name="top_k", type="integer", description="Number of results", default=5),
        ],
    )

    # Utility tools
    registry.register(
        name="get_current_time",
        func=get_current_time,
        description="Get current date and time",
        parameters=[
            ToolParameter(name="format", type="string", description="DateTime format", default="%Y-%m-%d %H:%M:%S"),
        ],
    )

    registry.register(
        name="calculate",
        func=calculate,
        description="Evaluate a mathematical expression",
        parameters=[
            ToolParameter(name="expression", type="string", description="Math expression", required=True),
        ],
    )

    registry.register(
        name="convert_units",
        func=convert_units,
        description="Convert between units",
        parameters=[
            ToolParameter(name="value", type="number", description="Value to convert", required=True),
            ToolParameter(name="from_unit", type="string", description="Source unit", required=True),
            ToolParameter(name="to_unit", type="string", description="Target unit", required=True),
        ],
    )

    # Text tools
    registry.register(
        name="count_text",
        func=count_text,
        description="Count characters, words, and lines in text",
        parameters=[
            ToolParameter(name="text", type="string", description="Text to analyze", required=True),
        ],
    )

    registry.register(
        name="extract_keywords",
        func=extract_keywords,
        description="Extract keywords from text",
        parameters=[
            ToolParameter(name="text", type="string", description="Text to analyze", required=True),
            ToolParameter(name="max_keywords", type="integer", description="Max keywords", default=10),
        ],
    )

    logger.info("Registered %d default tools", 6)
    return registry


# Initialize default tools on import if MCP is enabled
if MCP_ENABLED:
    try:
        register_default_tools()
    except Exception as e:
        logger.warning("Failed to register default tools: %s", e)
