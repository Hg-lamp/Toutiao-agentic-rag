"""Compatibility wrapper for tool definitions.

The real tool definitions are organized by responsibility under
`backend.services.tool_defs`, while this module keeps the older import path
working for the rest of the project.
"""

from backend.services.tool_defs import CHILD_TOOLS, PARENT_TOOLS, TOOL_SPECS

__all__ = ["PARENT_TOOLS", "CHILD_TOOLS", "TOOL_SPECS"]

# Import the concrete tool callables into module namespace so code such as
# `from backend.services.tools import calculator` still works without changing
# existing call sites.
from backend.services.tool_defs.general_tools import (
    analyze_numeric_data,
    calculator,
    generate_chart,
    get_current_time,
)
from backend.services.tool_defs.rag_tools import agent, get_memory, rag_search, save_memory
from backend.services.tool_defs.search_tools import sandbox_echo, sandbox_run_command, searxng_search_engine
