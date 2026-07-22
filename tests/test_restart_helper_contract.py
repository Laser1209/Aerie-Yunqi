from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_restart_helper_defaults_to_project_root() -> None:
    source = (ROOT / "tools" / "restart_helper.ps1").read_text(encoding="utf-8")

    assert "[string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)" in source
    assert "Split-Path -Parent (Split-Path -Parent $PSScriptRoot)" not in source


def test_restart_endpoint_passes_runtime_identity_explicitly() -> None:
    source = (ROOT / "core" / "api_server.py").read_text(encoding="utf-8")
    restart_block = source[source.index("async def system_restart") :]
    restart_block = restart_block[: restart_block.index("@app.post", 1)]

    assert '"-ProjectRoot"' in restart_block
    assert "str(project_root)" in restart_block
    assert '"-TargetPid"' in restart_block
    assert "str(os.getpid())" in restart_block
    assert '"-PythonExecutable"' in restart_block
    assert "sys.executable" in restart_block


def test_restart_helper_prefers_target_pid_and_tcp_probe() -> None:
    source = (ROOT / "tools" / "restart_helper.ps1").read_text(encoding="utf-8")

    assert "[int]$TargetPid = 0" in source
    assert "Stop-Process -Id $TargetPid" in source
    assert 'ConnectAsync("127.0.0.1", $Port)' in source
    assert "$psi.FileName = $PythonExecutable" in source
