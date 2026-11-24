from core.config.settings import Settings
from modules.sandbox.backend import (
    DisabledSandbox,
    DockerSandbox,
    SSHSandbox,
    build_sandbox_backend,
)


async def test_sandbox_backend_selection_and_disabled_safety() -> None:
    disabled_cfg = Settings(_env_file=None, sandbox_backend="disabled")
    disabled = build_sandbox_backend(disabled_cfg)
    assert isinstance(disabled, DisabledSandbox)
    res = await disabled.run("echo hi")
    assert res.exit_code == 126
    assert "disabled" in res.stderr.lower()

    docker_cfg = Settings(_env_file=None, sandbox_backend="docker")
    assert isinstance(build_sandbox_backend(docker_cfg), DockerSandbox)

    ssh_cfg = Settings(_env_file=None, sandbox_backend="ssh", sandbox_ssh_target="ops@10.0.0.5")
    ssh = build_sandbox_backend(ssh_cfg)
    assert isinstance(ssh, SSHSandbox)

    empty_ssh = SSHSandbox(target="")
    empty_res = await empty_ssh.run("uptime")
    assert empty_res.exit_code == 1
