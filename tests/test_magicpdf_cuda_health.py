import importlib.util
import subprocess
from pathlib import Path


def _load_magicpdf_server():
    server_path = Path(__file__).resolve().parents[1] / "docker" / "magicpdf" / "server.py"
    spec = importlib.util.spec_from_file_location("mimirq_magicpdf_server_test", server_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cuda_health_rejects_stale_torch_result_when_nvidia_smi_fails(monkeypatch):
    server = _load_magicpdf_server()
    monkeypatch.setattr(server.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        server.shutil, "which", lambda command: "/usr/bin/nvidia-smi" if command == "nvidia-smi" else None
    )

    def fail_nvidia_smi(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["nvidia-smi", "-L"])

    monkeypatch.setattr(server.subprocess, "run", fail_nvidia_smi)

    assert server._cuda_available() is False
