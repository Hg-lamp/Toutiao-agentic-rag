"""Backward-compatible wrapper around the canonical search tool module."""

from backend.services.tool_defs.search_tools import (
    CHILD_TOOLS,
    PARENT_TOOLS,
    TOOL_SPECS,
    sandbox_echo,
    sandbox_run_command,
    searxng_search_engine,
)

__all__ = [
    "searxng_search_engine",
    "sandbox_echo",
    "sandbox_run_command",
    "PARENT_TOOLS",
    "CHILD_TOOLS",
    "TOOL_SPECS",
]
