"""Backward-compatible wrapper around the canonical RAG tool module."""

from backend.services.tool_defs.rag_tools import (
    CHILD_TOOLS,
    PARENT_TOOLS,
    TOOL_SPECS,
    agent,
    get_memory,
    rag_search,
    save_memory,
)

__all__ = [
    "agent",
    "rag_search",
    "get_memory",
    "save_memory",
    "PARENT_TOOLS",
    "CHILD_TOOLS",
    "TOOL_SPECS",
]
