from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _linux_requirement_version(package: str) -> str:
    prefix = f"{package}=="
    for raw_line in _read("requirements.txt").splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        if 'platform_system == "Linux"' not in line:
            continue
        return line[len(prefix) :].split(";", 1)[0].strip()
    raise AssertionError(f"Linux requirement for {package} not found")


def test_backend_dockerfile_uses_resumable_cpu_torch_downloads() -> None:
    dockerfile = _read("docker/Dockerfile")
    torch_version = _linux_requirement_version("torch")
    torchvision_version = _linux_requirement_version("torchvision")

    assert "--continue-at -" in dockerfile
    assert "--retry-all-errors" in dockerfile
    assert f"torch-{torch_version}%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" in dockerfile
    assert f"torchvision-{torchvision_version}%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" in dockerfile
    assert "/tmp/torch-wheels" in dockerfile


def test_backend_dockerfile_retries_cached_requirements_install() -> None:
    dockerfile = _read("docker/Dockerfile")

    assert "--mount=type=cache,target=/root/.cache/pip" in dockerfile
    assert "--no-cache-dir --no-build-isolation -r" not in dockerfile
    assert "for attempt in 1 2 3" in dockerfile
    assert "/opt/venv/bin/pip install --retries 10 --timeout 120 --no-build-isolation -r" in dockerfile


def test_backend_dockerfile_allows_runtime_rapidocr_model_cache() -> None:
    dockerfile = _read("docker/Dockerfile")
    chown_section = dockerfile.split("chown -R appuser:appuser", 1)[1]

    assert "/opt/venv/lib/python3.11/site-packages/rapidocr/models" in dockerfile
    assert "/app" in chown_section
    assert "/data" in chown_section
    assert "/opt/venv/lib/python3.11/site-packages/rapidocr/models" in chown_section


def test_backend_dockerfile_allows_runtime_rapid_table_model_cache_for_magicpdf() -> None:
    dockerfile = _read("docker/Dockerfile")

    assert "/opt/venv/lib/python3.11/site-packages/rapid_table/models" in dockerfile
    assert "/opt/venv/lib/python3.11/site-packages/rapid_table/models" in dockerfile.split("chown -R appuser:appuser", 1)[1]
