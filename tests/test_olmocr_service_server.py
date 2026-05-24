from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_olmocr_service_module():
    server_path = Path(__file__).resolve().parents[1] / "docker" / "olmocr" / "server.py"
    spec = importlib.util.spec_from_file_location("mimirq_olmocr_service_test", server_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_olmocr_service_health_accepts_external_server_mode(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("OLMOCR_SERVER_URL", "http://vllm.example.test/v1")

    service = _load_olmocr_service_module()

    health = service.health()

    assert health["ok"] is True
    assert health["mode"] == "external"
    assert health["server_url_configured"] is True


def test_olmocr_service_health_fails_when_local_vllm_is_missing(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("OLMOCR_SERVER_URL", raising=False)
    service = _load_olmocr_service_module()

    monkeypatch.setattr(service, "_module_available", lambda name: name != "vllm")

    health = service.health()

    assert health["ok"] is False
    assert health["mode"] == "local_vllm"
    assert health["vllm_available"] is False
    assert health["reason"] == "vllm_unavailable"


def test_olmocr_service_health_fails_when_gpu_free_memory_is_below_threshold(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("OLMOCR_SERVER_URL", raising=False)
    monkeypatch.setenv("OLMOCR_MIN_FREE_GPU_GIB", "10")
    service = _load_olmocr_service_module()

    monkeypatch.setattr(service, "_module_available", lambda _name: True)
    monkeypatch.setattr(service, "_gpu_free_memory_gib", lambda: (8.25, None))

    health = service.health()

    assert health["ok"] is False
    assert health["gpu_free_gib"] == 8.25
    assert health["min_free_gpu_gib"] == 10.0
    assert health["reason"] == "insufficient_gpu_memory"


def test_olmocr_pipeline_command_includes_configured_vllm_limits(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("OLMOCR_GPU_MEMORY_UTILIZATION", "0.35")
    monkeypatch.setenv("OLMOCR_MAX_MODEL_LEN", "8192")
    monkeypatch.setenv("OLMOCR_MAX_SERVER_READY_TIMEOUT", "120")
    monkeypatch.setenv("OLMOCR_TENSOR_PARALLEL_SIZE", "1")
    monkeypatch.setenv("OLMOCR_DATA_PARALLEL_SIZE", "1")
    monkeypatch.setenv("OLMOCR_VLLM_PORT", "31234")
    monkeypatch.setenv("OLMOCR_EXTRA_ARGS", "--enforce-eager")

    service = _load_olmocr_service_module()

    cmd = service._build_pipeline_command(workspace=Path("/tmp/work"), input_name="input.pdf")

    assert cmd[:3] == ["python3", "-m", "olmocr.pipeline"]
    assert "--gpu-memory-utilization" in cmd
    assert cmd[cmd.index("--gpu-memory-utilization") + 1] == "0.35"
    assert "--max_model_len" in cmd
    assert cmd[cmd.index("--max_model_len") + 1] == "8192"
    assert "--max_server_ready_timeout" in cmd
    assert cmd[cmd.index("--max_server_ready_timeout") + 1] == "120"
    assert "--tensor-parallel-size" in cmd
    assert "--data-parallel-size" in cmd
    assert "--port" in cmd
    assert "--enforce-eager" in cmd
