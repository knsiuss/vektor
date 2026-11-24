import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

_MAX_OUTPUT_CHARS = 8000


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """Captured result from a sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@runtime_checkable
class SandboxBackend(Protocol):
    """Contract for isolated command execution without host .env exposure."""

    async def run(self, command: str, *, timeout_seconds: float = 15.0) -> SandboxResult:
        """Execute a shell command inside the isolated sandbox."""
        ...


class DisabledSandbox:
    """Safe default backend that refuses terminal execution."""

    async def run(self, command: str, *, timeout_seconds: float = 15.0) -> SandboxResult:
        _ = (command, timeout_seconds)
        return SandboxResult(
            exit_code=126,
            stdout="",
            stderr="Sandbox execution is disabled (VEKTOR_SANDBOX_BACKEND=disabled).",
        )


class DockerSandbox:
    """Runs commands inside an isolated Docker container without host .env access."""

    def __init__(
        self,
        *,
        image: str = "python:3.12-slim",
        workspace_dir: str = "./sandbox_workspace",
    ) -> None:
        self._image = image
        self._workspace = Path(workspace_dir).resolve()

    async def run(self, command: str, *, timeout_seconds: float = 15.0) -> SandboxResult:
        self._workspace.mkdir(parents=True, exist_ok=True)
        cmd = [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid",
            "-v",
            f"{self._workspace}:/workspace:rw",
            "-w",
            "/workspace",
            self._image,
            "sh",
            "-c",
            command,
        ]
        return await _exec_subprocess(cmd, timeout_seconds=timeout_seconds)


class SSHSandbox:
    """Runs commands on an authorized remote host over SSH."""

    def __init__(self, *, target: str) -> None:
        self._target = target.strip()

    async def run(self, command: str, *, timeout_seconds: float = 15.0) -> SandboxResult:
        if not self._target:
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr="VEKTOR_SANDBOX_SSH_TARGET is empty.",
            )
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            self._target,
            command,
        ]
        return await _exec_subprocess(cmd, timeout_seconds=timeout_seconds)


async def _exec_subprocess(cmd: list[str], *, timeout_seconds: float) -> SandboxResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return SandboxResult(exit_code=127, stdout="", stderr=str(exc))

    try:
        raw_out, raw_err = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        return SandboxResult(
            exit_code=proc.returncode or 0,
            stdout=raw_out.decode("utf-8", errors="replace")[:_MAX_OUTPUT_CHARS],
            stderr=raw_err.decode("utf-8", errors="replace")[:_MAX_OUTPUT_CHARS],
            timed_out=False,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return SandboxResult(
            exit_code=124,
            stdout="",
            stderr=f"Command timed out after {timeout_seconds}s.",
            timed_out=True,
        )


def build_sandbox_backend(settings: Any) -> SandboxBackend:
    """Build the configured SandboxBackend from application Settings."""
    mode = getattr(settings, "sandbox_backend", "disabled")
    if mode == "docker":
        return DockerSandbox(
            image=getattr(settings, "sandbox_docker_image", "python:3.12-slim"),
            workspace_dir=getattr(settings, "sandbox_workspace_dir", "./sandbox_workspace"),
        )
    if mode == "ssh":
        return SSHSandbox(target=getattr(settings, "sandbox_ssh_target", "") or "")
    return DisabledSandbox()
