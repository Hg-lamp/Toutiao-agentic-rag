"""Backward-compatible wrapper around the canonical general tool module."""

from backend.services.tool_defs.general_tools import (
    CHILD_TOOLS,
    PARENT_TOOLS,
    TOOL_SPECS,
    analyze_numeric_data,
    calculator,
    generate_chart,
    get_current_time,
)

__all__ = [
    "calculator",
    "get_current_time",
    "analyze_numeric_data",
    "generate_chart",
    "PARENT_TOOLS",
    "CHILD_TOOLS",
    "TOOL_SPECS",
]
