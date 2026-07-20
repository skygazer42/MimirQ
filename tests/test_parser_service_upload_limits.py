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

    assert compose["services"]["mimirq-magicpdf"]["ports"] == ["127.0.0.1:2095:2095"]
    assert compose["services"]["mimirq-qianfanocr"]["ports"] == ["127.0.0.1:2090:2090"]
