"""
LangGraph Store utilities (long-term memory scaffold).

The LangGraph "store" is a persistent key/value interface that can be accessed
from `runtime.store` inside LangGraph nodes. We keep it disabled by default and
only provide a minimal factory for future memory work.
"""

from app.rag.store.factory import get_langgraph_store

__all__ = ["get_langgraph_store"]

