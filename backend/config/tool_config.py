import os


def _int_env(name: str, default: int, minimum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


TOOL_MAX_OUTPUT_BYTES = _int_env("TOOL_MAX_OUTPUT_BYTES", 64 * 1024, 1)
TOOL_MAX_PARALLEL_CALLS = _int_env("TOOL_MAX_PARALLEL_CALLS", 8, 1)
TOOL_DEFAULT_TIMEOUT_SECONDS = float(os.getenv("TOOL_DEFAULT_TIMEOUT_SECONDS", "30"))
TOOL_MCP_HANDSHAKE_TIMEOUT_SECONDS = float(
    os.getenv("TOOL_MCP_HANDSHAKE_TIMEOUT_SECONDS", "5")
)
TOOL_MCP_MAX_MESSAGE_BYTES = _int_env("TOOL_MCP_MAX_MESSAGE_BYTES", 1024 * 1024, 1)
SANDBOX_RUNTIME = os.getenv("SANDBOX_RUNTIME", "docker")
SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "toutiao-agentic-rag-sandbox:dev")
SANDBOX_TTL_SECONDS = float(os.getenv("SANDBOX_TTL_SECONDS", "60"))
SANDBOX_CREATE_TIMEOUT_SECONDS = float(os.getenv("SANDBOX_CREATE_TIMEOUT_SECONDS", "10"))
SANDBOX_DESTROY_GRACE_SECONDS = float(os.getenv("SANDBOX_DESTROY_GRACE_SECONDS", "5"))
