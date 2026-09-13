from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Awaitable, Callable


# MCP 沙箱服务端通过标准输入输出承载换行分隔的 JSON-RPC 请求。
# 只暴露白名单工具，并把协议错误、工具参数错误和执行异常转换为明确响应。
ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]
ToolDefinition = dict[str, Any]
MAX_MESSAGE_BYTES = 1024 * 1024


# MCP 请求错误携带 JSON-RPC 错误码，供服务端统一生成错误响应。
class McpRequestError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# 管理 MCP 工具注册、JSON-RPC 分发和 stdio 生命周期。
# 该服务运行在受限沙箱中，不能替代宿主侧的权限和资源校验。
class McpServer:
    def __init__(
        self,
        *,
        tools: dict[str, ToolDefinition],
        handlers: dict[str, ToolHandler],
        server_name: str = "toutiao-sandbox",
        server_version: str = "0.1.0",
    ) -> None:
        self.tools = tools
        self.handlers = handlers
        self.server_name = server_name
        self.server_version = server_version

    # 执行已注册工具，并在名称或参数不合法时返回协议级错误。
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.handlers:
            raise McpRequestError(-32602, "unknown tool")
        if not isinstance(arguments, dict):
            raise McpRequestError(-32602, "tool arguments must be an object")
        return await self.handlers[name](arguments)

    # 处理 initialize、tools/list 和 tools/call 请求。
    # notifications/initialized 不返回响应；未知方法和异常不会泄露内部错误细节。
    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._error_response(request_id, -32600, "invalid request")

        if method == "notifications/initialized":
            return None

        try:
            if method == "initialize":
                requested_version = params.get("protocolVersion", "2024-11-05")
                result = {
                    "protocolVersion": requested_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.server_version,
                    },
                }
            elif method == "tools/list":
                result = {"tools": list(self.tools.values())}
            elif method == "tools/call":
                tool_name = params.get("name")
                if not isinstance(tool_name, str):
                    raise McpRequestError(-32602, "tool name is required")
                tool_result = await self.call_tool(
                    tool_name,
                    params.get("arguments") or {},
                )
                text = (
                    tool_result
                    if isinstance(tool_result, str)
                    else json.dumps(tool_result, ensure_ascii=False)
                )
                result = {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                }
            else:
                raise McpRequestError(-32601, "unsupported method")
        except McpRequestError as exc:
            return self._error_response(request_id, exc.code, exc.message)
        except Exception:
            return self._error_response(request_id, -32000, "tool execution failed")

        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    # 持续读取 stdio 请求并逐行写回 JSON-RPC 响应，单条消息有大小上限。
    async def serve_stdio(self) -> None:
        while True:
            line = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not line:
                return
            if len(line) > MAX_MESSAGE_BYTES:
                response = self._error_response(None, -32600, "request too large")
            else:
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("request must be an object")
                    response = await self.handle_request(request)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    response = self._error_response(None, -32700, "parse error")

            if response is None:
                continue
            encoded = json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            sys.stdout.buffer.write(encoded + b"\n")
            sys.stdout.buffer.flush()

    # 构造统一 JSON-RPC 错误对象，保证错误响应仍带有原请求 ID。
    @staticmethod
    def _error_response(
        request_id: Any,
        code: int,
        message: str,
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


# 沙箱回显工具，仅用于验证 MCP 通道和参数校验是否正常。
async def _sandbox_echo(arguments: dict[str, Any]) -> dict[str, Any]:
    text = arguments.get("text")
    if not isinstance(text, str):
        raise McpRequestError(-32602, "text must be a string")
    if len(text) > 4096:
        raise McpRequestError(-32602, "text is too long")
    return {"echo": text}


# 在固定命令白名单内执行沙箱诊断命令，并限制执行时长和输出大小。
async def _sandbox_run_command(arguments: dict[str, Any]) -> dict[str, Any]:
    commands = {
        "pwd": ("pwd",),
        "id": ("id",),
        "python_version": ("python", "--version"),
    }
    command_name = arguments.get("command")
    if command_name not in commands:
        raise McpRequestError(-32602, "unsupported command")

    process = await asyncio.create_subprocess_exec(
        *commands[command_name],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise McpRequestError(-32000, "command timed out")

    return {
        "command": command_name,
        "exit_code": process.returncode,
        "stdout": stdout.decode(errors="replace")[:4096],
        "stderr": stderr.decode(errors="replace")[:4096],
    }


# 注册默认沙箱工具及其输入 schema，供 MCP Server 和 tools/list 使用。
def build_default_server() -> McpServer:
    tools = {
        "sandbox_echo": {
            "name": "sandbox_echo",
            "description": "Return text from inside the isolated sandbox.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string", "maxLength": 4096}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
        "sandbox_run_command": {
            "name": "sandbox_run_command",
            "description": "Run a fixed, allowlisted command inside the sandbox.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": ["pwd", "id", "python_version"],
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    }
    handlers: dict[str, ToolHandler] = {
        "sandbox_echo": _sandbox_echo,
        "sandbox_run_command": _sandbox_run_command,
    }
    return McpServer(tools=tools, handlers=handlers)


# 进程入口：创建默认服务并开始 stdio 事件循环。
def main() -> None:
    # 以 stdio 模式启动固定工具集合，供宿主侧 SandboxBroker 拉起。
    asyncio.run(build_default_server().serve_stdio())


if __name__ == "__main__":
    main()
