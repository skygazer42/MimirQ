from __future__ import annotations

from pathlib import Path

import yaml


def _load_doc(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))


def test_gpu_parser_services_use_named_compose_networks() -> None:
    services = (_load_doc('docker/docker-compose.parsers.yml').get('services') or {})

    paddlevl = services['mimirq-paddlevl']
    olmocr = services['mimirq-olmocr']

    assert 'network_mode' not in paddlevl
    assert 'network_mode' not in olmocr
    assert 'mimirq-paddlevl' in ((paddlevl.get('networks') or {}).get('default') or {}).get('aliases', [])
    assert 'mimirq-olmocr' in ((olmocr.get('networks') or {}).get('default') or {}).get('aliases', [])


def test_paddlevl_service_exposes_pipeline_timeout() -> None:
    services = (_load_doc('docker/docker-compose.parsers.yml').get('services') or {})
    paddlevl = services['mimirq-paddlevl']

    env = paddlevl.get('environment') or {}
    assert 'PADDLEOCR_PIPELINE_TIMEOUT_SEC' in env
