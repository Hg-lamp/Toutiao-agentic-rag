"""Backward-compatible alias for the canonical tool package.

This package intentionally wraps the real implementation in
`backend.services.tool_defs` so old imports keep working while the project uses a
single canonical tool layout.
"""

from backend.services.tool_defs import (
    CHILD_TOOLS,
    PARENT_TOOLS,
    TOOL_SPECS,
)
from backend.services.tool_defs import (
    GENERAL_TOOL_SPECS,
    RAG_TOOL_SPECS,
    SEARCH_TOOL_SPECS,
)

__all__ = [
    "PARENT_TOOLS",
    "CHILD_TOOLS",
    "TOOL_SPECS",
    "GENERAL_TOOL_SPECS",
    "RAG_TOOL_SPECS",
    "SEARCH_TOOL_SPECS",
]
