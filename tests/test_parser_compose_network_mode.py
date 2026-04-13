from __future__ import annotations

from pathlib import Path

import yaml


def _load_doc(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))


def test_gpu_parser_services_share_api_network_namespace() -> None:
    services = (_load_doc('docker/docker-compose.parsers.yml').get('services') or {})

    paddlevl = services['mimirq-paddlevl']
    olmocr = services['mimirq-olmocr']

    assert paddlevl.get('network_mode') == 'service:mimirq-api'
    assert olmocr.get('network_mode') == 'service:mimirq-api'
