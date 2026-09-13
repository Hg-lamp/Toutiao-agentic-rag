import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

import backend.services.tools  # noqa: F401 - registers application tools
from backend.services.mcp_client import McpClient
from backend.services.sandbox_broker import SandboxLease
from backend.services.tool_gateway import (
    GATEWAY,
    ToolGateway,
    ToolRegistry,
    ToolSpec,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@tool
async def local_probe(value: str) -> str:
    """Return a value from the local executor."""
    return value


class ToolGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_tool_runs_through_gateway(self):
        registry = ToolRegistry()
        registry.register(
            local_probe,
            ToolSpec(
                name="local_probe",
                description="Test local tool execution.",
                risk_level="R0",
                timeout_seconds=5,
            ),
        )
        gateway = ToolGateway(registry=registry)
        request = SimpleNamespace(
            tool_call={
                "name": "local_probe",
                "id": "call_local",
                "args": {"value": "ok"},
            },
            runtime=SimpleNamespace(
                config={
                    "configurable": {
                        "user_id": 1,
                        "tenant_id": "user:1",
                        "thread_id": "thread-1",
                        "agent_id": "parent",
                        "trace_id": "trace-1",
                        "scopes": [],
                    }
                }
            ),
            state={"messages": []},
        )

        async def handler(_request):
            return ToolMessage(
                content="ok",
                tool_call_id="call_local",
                name="local_probe",
            )

        result = await gateway.awrap_tool_call(request, handler)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.content, "ok")

    async def test_r4_local_tool_is_rejected(self):
        registry = ToolRegistry()
        with self.assertRaisesRegex(ValueError, "must execute through MCP"):
            registry.register(
                local_probe,
                ToolSpec(
                    name="local_probe",
                    description="Unsafe local tool.",
                    executor="local",
                    risk_level="R4",
                    required_scopes=("test.high_risk",),
                    timeout_seconds=30,
                ),
            )

    async def test_sandbox_echo_is_registered_as_mcp(self):
        entry = GATEWAY.registry.get("sandbox_echo")
        self.assertIsNotNone(entry)
        _, spec = entry
        self.assertEqual(spec.executor, "mcp")
        self.assertEqual(spec.sandbox_profile, "default")

    async def test_sandbox_run_command_is_high_risk_mcp(self):
        entry = GATEWAY.registry.get("sandbox_run_command")
        self.assertIsNotNone(entry)
        _, spec = entry
        self.assertEqual(spec.executor, "mcp")
        self.assertEqual(spec.risk_level, "R4")
        self.assertEqual(spec.required_scopes, ("sandbox.command.execute",))


class McpStdioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.process = await asyncio.to_thread(
            subprocess.Popen,
            [
                sys.executable,
                str(PROJECT_ROOT / "backend" / "mcp" / "server.py"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.lease = SandboxLease(
            sandbox_id="stdio-test",
            endpoint="stdio://stdio-test",
            auth_token="test-token",
            session_id="test-session",
            process=self.process,
        )

    async def asyncTearDown(self):
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            await asyncio.to_thread(self.process.wait, timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            await asyncio.to_thread(self.process.wait)
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    async def test_sandbox_echo_over_stdio(self):
        result = await McpClient().call_tool(
            lease=self.lease,
            execution_id="call-1",
            tool_name="sandbox_echo",
            arguments={"text": "hello"},
            timeout_seconds=5,
        )

        self.assertEqual(result["content"][0]["text"], '{"echo": "hello"}')

    async def test_sandbox_run_command_over_stdio(self):
        result = await McpClient().call_tool(
            lease=self.lease,
            execution_id="call-2",
            tool_name="sandbox_run_command",
            arguments={"command": "python_version"},
            timeout_seconds=5,
        )

        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("Python", payload["stdout"] + payload["stderr"])


if __name__ == "__main__":
    unittest.main()
