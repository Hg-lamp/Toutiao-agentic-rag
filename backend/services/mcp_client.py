from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.config.tool_config import TOOL_MCP_MAX_MESSAGE_BYTES
from backend.services.sandbox_broker import SandboxLease


# MCP 客户端协议异常；调用方可据此区分协议、进程和超时失败。
class McpProtocolError(RuntimeError):
    pass


# 宿主侧的最小 MCP stdio 客户端。沙箱生命周期由 SandboxBroker 管理，
# 客户端只负责串行请求、响应校验、大小限制和超时控制。
class McpClient:
    # 发送 tools/call 请求并严格校验 endpoint、进程状态、响应 ID、JSON 结构和大小。
    # request_lock 保证同一 stdio 进程不会发生请求与响应错配。
    async def call_tool(
        self,
        lease: SandboxLease,
        execution_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if not lease.endpoint.startswith("stdio://"):
            raise McpProtocolError("unsupported MCP endpoint")
        if timeout_seconds <= 0:
            raise McpProtocolError("MCP call deadline exceeded")
        if lease.process.stdin is None or lease.process.stdout is None:
            raise McpProtocolError("sandbox stdio pipes are unavailable")
        if lease.process.poll() is not None:
            raise McpProtocolError("sandbox process is not running")

        request = {
            "jsonrpc": "2.0",
            "id": execution_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        encoded = json.dumps(request, ensure_ascii=False).encode("utf-8")
        if len(encoded) > TOOL_MCP_MAX_MESSAGE_BYTES:
            raise McpProtocolError("MCP request exceeds maximum message size")

        async with lease.request_lock:
            try:
                await asyncio.to_thread(
                    self._write_request,
                    lease.process.stdin,
                    encoded + b"\n",
                )
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                detail = self._process_error(lease.process)
                raise McpProtocolError(detail or "failed to write MCP request") from exc
            try:
                response_line = await asyncio.wait_for(
                    asyncio.to_thread(lease.process.stdout.readline),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise McpProtocolError("MCP response timed out") from exc

        if not response_line:
            raise McpProtocolError("MCP server closed the connection")
        if len(response_line) > TOOL_MCP_MAX_MESSAGE_BYTES:
            raise McpProtocolError("MCP response exceeds maximum message size")

        try:
            response = json.loads(response_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise McpProtocolError("MCP returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise McpProtocolError("MCP response must be an object")
        if response.get("id") != execution_id:
            raise McpProtocolError("MCP response id mismatch")
        if "error" in response:
            raise McpProtocolError("MCP tool execution failed")

        result = response.get("result")
        if not isinstance(result, dict):
            raise McpProtocolError("MCP result must be an object")
        return result

    # 写入一条完整 JSON-RPC 请求并立即刷新，确保沙箱服务端可以读取。
    @staticmethod
    def _write_request(stream, payload: bytes) -> None:
        stream.write(payload)
        stream.flush()

    # 沙箱进程已退出时读取有限长度的 stderr，帮助定位启动或协议故障。
    @staticmethod
    def _process_error(process) -> str:
        if process.stderr is None or process.poll() is None:
            return ""
        try:
            return process.stderr.read().decode(errors="replace")[:500].strip()
        except OSError:
            return ""
