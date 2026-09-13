from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from langchain_core.messages import ToolMessage
from loguru import logger
from pydantic import BaseModel

from backend.config.tool_config import (
    TOOL_DEFAULT_TIMEOUT_SECONDS,
    TOOL_MAX_OUTPUT_BYTES,
    TOOL_MAX_PARALLEL_CALLS,
)
from backend.services.mcp_client import McpClient
from backend.services.sandbox_broker import SandboxBroker


# 工具网关统一处理工具注册、权限校验、并发控制、超时、重试和执行路由。
# local 工具留在宿主进程执行，mcp 工具必须通过隔离沙箱执行。
RiskLevel = Literal["R0", "R1", "R2", "R3", "R4"]
ExecutorKind = Literal["local", "mcp"]
ApprovalMode = Literal["never", "conditional", "always"]


# 工具的静态安全策略；注册时会校验风险等级、执行器、权限范围和重试条件。
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    executor: ExecutorKind = "local"
    risk_level: RiskLevel = "R0"
    side_effect: bool = False
    idempotent: bool = True
    approval_mode: ApprovalMode = "never"
    timeout_seconds: float = TOOL_DEFAULT_TIMEOUT_SECONDS
    retry_max_attempts: int = 0
    retry_backoff_ms: int = 100
    sandbox_profile: str | None = None
    required_scopes: tuple[str, ...] = ()
    concurrency_limit: int = 1


# 保存工具实现、策略和每个工具独立的并发信号量。
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}
        self._specs: dict[str, ToolSpec] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    # 注册工具并在启动阶段拒绝不完整或不安全的策略组合。
    def register(self, tool: Any, spec: ToolSpec) -> Any:
        if spec.name != tool.name or spec.name in self._tools:
            raise ValueError(f"invalid or duplicate tool registration: {spec.name}")
        if not 3 <= len(spec.description) <= 1000:
            raise ValueError(f"invalid description for {spec.name}")
        if spec.timeout_seconds <= 0:
            raise ValueError(f"{spec.name} requires a positive timeout")
        if not 0 <= spec.retry_max_attempts <= 3:
            raise ValueError(f"{spec.name} has an invalid retry count")
        if spec.retry_backoff_ms < 0:
            raise ValueError(f"{spec.name} has an invalid retry backoff")
        if spec.concurrency_limit < 1:
            raise ValueError(f"{spec.name} requires a positive concurrency limit")
        if spec.risk_level == "R0" and spec.timeout_seconds > 5:
            raise ValueError(f"{spec.name} exceeds the R0 timeout limit")
        if spec.risk_level == "R4" and spec.timeout_seconds > 30:
            raise ValueError(f"{spec.name} exceeds the R4 timeout limit")
        if spec.risk_level == "R4" and spec.executor != "mcp":
            raise ValueError(f"{spec.name} must execute through MCP")
        if spec.risk_level in ("R3", "R4") and not spec.required_scopes:
            raise ValueError(f"{spec.name} requires scopes for {spec.risk_level}")
        if spec.executor == "mcp" and spec.risk_level in ("R3", "R4") and not spec.sandbox_profile:
            raise ValueError(f"{spec.name} requires a sandbox profile")
        if spec.retry_max_attempts and (spec.side_effect or not spec.idempotent):
            raise ValueError(f"{spec.name} is not eligible for automatic retries")
        self._tools[spec.name] = tool
        self._specs[spec.name] = spec
        self._semaphores[spec.name] = asyncio.Semaphore(spec.concurrency_limit)
        return tool

    # 查询工具实现和安全策略；未知工具返回 None。
    def get(self, name: str) -> tuple[Any, ToolSpec] | None:
        if name not in self._tools:
            return None
        return self._tools[name], self._specs[name]

    # 按名称返回供 LangGraph ToolNode 使用的工具列表。
    def tools(self, names: list[str]) -> list[Any]:
        return [self._tools[name] for name in names]

    # 返回工具级并发信号量，限制同一工具的同时执行数量。
    def semaphore(self, name: str) -> asyncio.Semaphore:
        return self._semaphores[name]


TOOL_REGISTRY = ToolRegistry()


# 从请求中提取运行时上下文；这些字段由服务端注入，不能由模型工具参数覆盖。
@dataclass
class GatewayContext:
    user_id: int
    tenant_id: str
    conversation_id: str
    agent_id: str
    trace_id: str
    deadline: float
    scopes: frozenset[str]


# 读取工具请求中的 configurable 配置，主要用于审批令牌等服务端控制信息。
def values_from_request(request: Any) -> dict[str, Any]:
    runtime = getattr(request, "runtime", None)
    config = getattr(runtime, "config", None) or getattr(request, "config", None) or {}
    return config.get("configurable", {})


# 构造并校验一次工具调用的身份、租户、会话、时间预算和权限范围。
def _context(request: Any) -> GatewayContext:
    runtime = getattr(request, "runtime", None)
    config = getattr(runtime, "config", None) or getattr(request, "config", None) or {}
    values = config.get("configurable", {})
    user_id = values.get("user_id")
    tenant_id = values.get("tenant_id", "default")
    conversation_id = values.get("thread_id")
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("server-injected user_id is required")
    if not isinstance(tenant_id, str) or not 1 <= len(tenant_id) <= 64:
        raise ValueError("server-injected tenant_id is required")
    if not conversation_id:
        raise ValueError("conversation_id is required")
    return GatewayContext(
        user_id=user_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        agent_id=values.get("agent_id", "parent"),
        trace_id=values.get("trace_id", str(uuid.uuid4())),
        deadline=time.monotonic() + float(values.get("time_budget_ms", 300_000)) / 1000,
        scopes=frozenset(values.get("scopes", ())),
    )


# 统一工具调用入口：先做权限和参数校验，再按 executor 路由到 MCP 沙箱或本地执行。
# 失败统一返回 ToolMessage，避免把内部异常、凭据或沙箱细节暴露给模型。
class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry = TOOL_REGISTRY,
        broker: SandboxBroker | None = None,
        mcp_client: McpClient | None = None,
    ) -> None:
        self.registry = registry
        self.broker = broker or SandboxBroker()
        self.mcp_client = mcp_client or McpClient()
        self._global_semaphore = asyncio.Semaphore(TOOL_MAX_PARALLEL_CALLS)

    # 执行 LangGraph 的工具包装回调；全局和工具级信号量、超时与重试由此生效。
    async def awrap_tool_call(self, request: Any, handler: Callable[..., Awaitable[Any]]) -> Any:
        call = getattr(request, "tool_call", None) or {}
        name = call.get("name")
        tool_call_id = call.get("id", "")
        arguments = call.get("args", {})
        try:
            context = _context(request)
            entry = self.registry.get(name)
            if entry is None:
                raise PermissionError("unknown_tool")
            tool, spec = entry
            missing_scopes = set(spec.required_scopes) - context.scopes
            if missing_scopes:
                raise PermissionError("missing_required_scope")
            if spec.approval_mode == "always" and not values_from_request(request).get("approval_token"):
                raise PermissionError("approval_required")
            self._validate_arguments(tool, arguments)
            if spec.executor == "mcp":
                return await self._run_mcp(call, spec, context)
            return await self._run_local(request, handler, spec, context)
        except Exception as exc:
            logger.warning(
                "tool denied or failed name={} error={} reason={}",
                name,
                type(exc).__name__,
                str(exc),
            )
            return ToolMessage(
                content=json.dumps(
                    {"status": "failed", "error_code": "tool_execution_denied"},
                    ensure_ascii=False,
                ),
                tool_call_id=tool_call_id,
                name=name,
                status="error",
            )

    # 拒绝非对象参数、服务端保留字段和 schema 未声明字段。
    @staticmethod
    def _validate_arguments(tool: Any, arguments: Any) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        if set(arguments) & {"user_id", "tenant_id", "sandbox_profile", "auth_token"}:
            raise PermissionError("server-owned argument")
        schema = getattr(tool, "args_schema", None)
        if schema and isinstance(schema, type) and issubclass(schema, BaseModel):
            model_fields = getattr(schema, "model_fields", {})
            unknown = set(arguments) - set(model_fields)
            if unknown:
                raise ValueError(f"unknown tool arguments: {sorted(unknown)}")
            schema.model_validate(arguments)

    # 创建 MCP 沙箱租约并执行远程工具调用，结束后无论成功失败都清理租约。
    async def _run_mcp(self, call: dict[str, Any], spec: ToolSpec, context: GatewayContext) -> ToolMessage:
        lease = None
        try:
            execution_id = str(uuid.uuid4())
            lease = await self.broker.acquire(context.trace_id, spec.sandbox_profile or "default")
            result = await self.mcp_client.call_tool(
                lease=lease,
                execution_id=execution_id,
                tool_name=spec.name,
                arguments=call.get("args", {}),
                timeout_seconds=min(spec.timeout_seconds, context.deadline - time.monotonic()),
            )
            content = json.dumps(result, ensure_ascii=False)
            return ToolMessage(
                content=content[:TOOL_MAX_OUTPUT_BYTES],
                tool_call_id=call.get("id", ""),
                name=spec.name,
                status="success",
            )
        finally:
            if lease is not None:
                await self.broker.destroy(lease)

    # 在宿主进程执行低风险本地工具，统一应用全局/工具级并发限制、超时和安全重试。
    async def _run_local(
        self, request: Any, handler: Callable[..., Awaitable[Any]], spec: ToolSpec, context: GatewayContext
    ) -> Any:
        remaining = context.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("agent deadline exceeded")
        attempts = 1 + (spec.retry_max_attempts if spec.idempotent and not spec.side_effect else 0)
        async with self._global_semaphore, self.registry.semaphore(spec.name):
            for attempt in range(attempts):
                try:
                    result = await asyncio.wait_for(
                        handler(request), min(spec.timeout_seconds, remaining)
                    )
                    if isinstance(result, ToolMessage) and isinstance(result.content, str):
                        result.content = result.content[:TOOL_MAX_OUTPUT_BYTES]
                    return result
                except Exception:
                    if attempt + 1 >= attempts:
                        raise
                    await asyncio.sleep(spec.retry_backoff_ms / 1000 * (2**attempt))


# 主 Agent 和其他调用方共享的工具网关实例。
GATEWAY = ToolGateway()
