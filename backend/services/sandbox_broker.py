from __future__ import annotations

import asyncio
import subprocess
import uuid
from dataclasses import dataclass, field

from backend.config.tool_config import (
    SANDBOX_CREATE_TIMEOUT_SECONDS,
    SANDBOX_DESTROY_GRACE_SECONDS,
    SANDBOX_IMAGE,
    SANDBOX_RUNTIME,
)


# 描述一次沙箱租约及其 stdio 通道；request_lock 保证同一进程内请求按顺序配对。
@dataclass
class SandboxLease:
    sandbox_id: str
    endpoint: str
    auth_token: str
    session_id: str
    process: subprocess.Popen[bytes]
    request_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# 沙箱创建、启动或清理失败时使用的明确异常类型。
class SandboxError(RuntimeError):
    pass


# 负责 Docker 沙箱生命周期，不参与 MCP JSON-RPC 编解码。
# 沙箱默认关闭网络、只读文件系统、丢弃 capability，并限制进程、内存和 CPU。
class SandboxBroker:
    # 校验沙箱配置、启动固定镜像并返回带 stdio 管道的租约。
    # 镜像必须预先存在，启动参数禁止网络和提权能力。
    async def acquire(self, session_id: str, profile: str) -> SandboxLease:
        if SANDBOX_RUNTIME != "docker":
            raise SandboxError(f"unsupported sandbox runtime: {SANDBOX_RUNTIME}")
        if not SANDBOX_IMAGE or SANDBOX_IMAGE.endswith("@sha256:"):
            raise SandboxError("SANDBOX_IMAGE must reference a built image")

        await self._ensure_image_available()
        sandbox_id = f"tool-{uuid.uuid4().hex}"
        command = [
            "docker",
            "run",
            "--rm",
            "--interactive",
            "--name",
            sandbox_id,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--user=65532:65532",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--memory=512m",
            "--cpus=1",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHONUNBUFFERED=1",
            SANDBOX_IMAGE,
            "python",
            "/app/server.py",
        ]
        try:
            process = await asyncio.to_thread(
                subprocess.Popen,
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise SandboxError(f"sandbox creation failed: {exc}") from exc

        await asyncio.sleep(0.1)
        if process.poll() is not None:
            detail = self._read_stderr(process)
            raise SandboxError(detail or "sandbox exited during startup")

        return SandboxLease(
            sandbox_id=sandbox_id,
            endpoint=f"stdio://{sandbox_id}",
            auth_token=uuid.uuid4().hex,
            session_id=session_id,
            process=process,
        )

    # 关闭沙箱进程并删除容器；优雅退出超时后才强制终止。
    async def destroy(self, lease: SandboxLease) -> None:
        process = lease.process
        if process.poll() is None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                await asyncio.to_thread(
                    process.wait,
                    timeout=SANDBOX_DESTROY_GRACE_SECONDS,
                )
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)

        await self._remove_container(lease.sandbox_id)

    # 在创建容器前确认本地镜像存在，避免运行阶段才发现镜像缺失。
    async def _ensure_image_available(self) -> None:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "image", "inspect", SANDBOX_IMAGE],
                capture_output=True,
                timeout=SANDBOX_CREATE_TIMEOUT_SECONDS,
            )
        except OSError as exc:
            raise SandboxError(f"sandbox image check failed: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxError("sandbox image check timed out") from exc
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace")[:500].strip()
            raise SandboxError(detail or "sandbox image not found")

    @staticmethod
    # 清理指定容器；已不存在的容器视为幂等清理成功。
    async def _remove_container(sandbox_id: str) -> None:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "rm", "--force", sandbox_id],
                capture_output=True,
                timeout=SANDBOX_DESTROY_GRACE_SECONDS,
            )
        except OSError as exc:
            raise SandboxError(f"sandbox cleanup failed: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxError("sandbox cleanup timed out") from exc

        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace")
            if "No such container" not in detail:
                raise SandboxError(detail[:500].strip() or "sandbox cleanup failed")

    @staticmethod
    # 读取启动失败进程的有限 stderr，避免错误信息无限制进入日志。
    def _read_stderr(process: subprocess.Popen[bytes]) -> str:
        if process.stderr is None:
            return ""
        return process.stderr.read().decode(errors="replace")[:500].strip()
