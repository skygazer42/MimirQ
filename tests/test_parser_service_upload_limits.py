import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from docker.magicpdf import server as magicpdf_server
from docker.qianfanocr import server as qianfanocr_server


class _Upload:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.data)
        chunk = self.data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


@pytest.mark.parametrize("module", [magicpdf_server, qianfanocr_server])
def test_parser_uploads_have_a_hard_streamed_limit(module: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_MAX_UPLOAD_BYTES", 3)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(module._read_upload(_Upload(b"four")))

    assert exc_info.value.status_code == 413


def test_parser_host_ports_bind_to_loopback() -> None:
    compose = yaml.safe_load(Path("docker/docker-compose.parsers.yml").read_text(encoding="utf-8"))

    assert compose["services"]["mimirq-docling"]["ports"] == ["127.0.0.1:${DOCLING_PORT:-5001}:5001"]
    assert compose["services"]["mimirq-docling-gpu"]["ports"] == [
        "127.0.0.1:${DOCLING_PORT:-5001}:5001"
    ]
    assert compose["services"]["mimirq-marker"]["ports"] == ["127.0.0.1:2080:2080"]
    assert compose["services"]["mimirq-magicpdf"]["ports"] == ["127.0.0.1:2095:2095"]
    assert compose["services"]["mimirq-qianfanocr"]["ports"] == ["127.0.0.1:2090:2090"]


def test_gpu_parsers_use_compose_compatible_device_reservations() -> None:
    compose = yaml.safe_load(Path("docker/docker-compose.parsers.yml").read_text(encoding="utf-8"))
    gpu_services = (
        "mimirq-paddlevl",
        "mimirq-mineru",
        "mimirq-mineru-vlm",
        "mimirq-olmocr",
        "mimirq-magicpdf",
        "mimirq-docling-gpu",
    )

    expected = [{"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}]
    for service_name in gpu_services:
        service = compose["services"][service_name]
        assert "gpus" not in service
        devices = service["deploy"]["resources"]["reservations"]["devices"]
        if service_name == "mimirq-docling-gpu":
            assert devices == [{"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}]
        else:
            assert devices == expected


def test_docling_is_a_pinned_external_service_not_a_main_runtime_dependency() -> None:
    compose = yaml.safe_load(Path("docker/docker-compose.parsers.yml").read_text(encoding="utf-8"))
    service = compose["services"]["mimirq-docling"]
    requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()

    assert service["profiles"] == ["docling"]
    assert service["image"] == "quay.io/docling-project/docling-serve-cpu:v1.28.0"
    assert service["environment"]["DOCLING_SERVE_LOAD_MODELS_AT_BOOT"] == "true"
    assert service["healthcheck"]["start_period"] == "180s"
    assert not any(line.strip().lower().startswith(("docling==", "docling-ibm-models==")) for line in requirements)


def test_docling_gpu_service_is_pinned_and_conservative_by_default() -> None:
    compose = yaml.safe_load(Path("docker/docker-compose.parsers.yml").read_text(encoding="utf-8"))
    service = compose["services"]["mimirq-docling-gpu"]

    assert service["profiles"] == ["docling-gpu"]
    assert service["image"] == (
        "${DOCLING_GPU_IMAGE:-quay.io/docling-project/docling-serve-cu128:v1.28.0}"
    )
    assert service["environment"]["DOCLING_DEVICE"] == "${DOCLING_GPU_DEVICE:-cuda}"
    assert service["environment"]["DOCLING_SERVE_ENG_LOC_NUM_WORKERS"] == "${DOCLING_GPU_WORKERS:-1}"
    assert service["environment"]["DOCLING_SERVE_ENG_LOC_SHARE_MODELS"] == "true"
