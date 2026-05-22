from __future__ import annotations

from pathlib import Path


def test_magicpdf_service_dockerfile_uses_cuda_runtime() -> None:
    dockerfile = Path("docker/magicpdf/Dockerfile").read_text(encoding="utf-8")
    from_line = next(line for line in dockerfile.splitlines() if line.startswith("FROM "))

    assert "FROM pytorch/pytorch:" in dockerfile
    assert "cuda" in from_line.lower()
    assert "2.6.0-cuda12.4-cudnn9-runtime" in from_line
    assert "2.5.1" not in from_line
    assert "torchvision==0.21.0" in dockerfile
    assert "pip install magic-pdf==1.3.12" in dockerfile
    assert "https://download.pytorch.org/whl/cpu" not in dockerfile
