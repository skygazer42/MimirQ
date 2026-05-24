from __future__ import annotations

from pathlib import Path

import yaml


def _load_doc(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))


def test_gpu_parser_services_use_named_compose_networks() -> None:
    services = (_load_doc('docker/docker-compose.parsers.yml').get('services') or {})

    paddlevl = services['mimirq-paddlevl']
    olmocr = services['mimirq-olmocr']
    magicpdf = services['mimirq-magicpdf']

    assert 'network_mode' not in paddlevl
    assert 'network_mode' not in olmocr
    assert 'network_mode' not in magicpdf
    assert 'mimirq-paddlevl' in ((paddlevl.get('networks') or {}).get('default') or {}).get('aliases', [])
    assert 'mimirq-olmocr' in ((olmocr.get('networks') or {}).get('default') or {}).get('aliases', [])
    assert 'mimirq-magicpdf' in ((magicpdf.get('networks') or {}).get('default') or {}).get('aliases', [])


def test_paddlevl_service_exposes_pipeline_timeout() -> None:
    services = (_load_doc('docker/docker-compose.parsers.yml').get('services') or {})
    paddlevl = services['mimirq-paddlevl']

    env = paddlevl.get('environment') or {}
    volumes = paddlevl.get('volumes') or []
    assert env.get('PADDLEOCR_PIPELINE_TIMEOUT_SEC') == '${PADDLEOCR_PIPELINE_TIMEOUT_SEC:-540}'
    assert env.get('PADDLE_PDX_MODEL_SOURCE') == '${PADDLE_PDX_MODEL_SOURCE:-aistudio}'
    assert env.get('PADDLE_PDX_CACHE_HOME') == '${PADDLE_PDX_CACHE_HOME:-/home/paddleocr/.paddlex}'
    assert 'paddlevl_cache:/home/paddleocr/.paddlex' in volumes


def test_mineru_vlm_service_uses_single_gpu_shared_defaults() -> None:
    services = (_load_doc('docker/docker-compose.parsers.yml').get('services') or {})
    mineru_vlm = services['mimirq-mineru-vlm']

    env = mineru_vlm.get('environment') or {}
    assert env.get('MINERU_MODEL_SOURCE') == '${MINERU_MODEL_SOURCE:-local}'
    assert env.get('MINERU_VLM_GPU_MEMORY_UTILIZATION') == '${MINERU_VLM_GPU_MEMORY_UTILIZATION:-0.45}'


def test_magicpdf_service_is_gpu_first_and_uses_shared_model_cache() -> None:
    services = (_load_doc('docker/docker-compose.parsers.yml').get('services') or {})
    magicpdf = services['mimirq-magicpdf']

    env = magicpdf.get('environment') or {}
    volumes = magicpdf.get('volumes') or []

    assert magicpdf.get('gpus') == 'all'
    assert env.get('MAGIC_PDF_DEVICE_MODE') == '${MAGIC_PDF_DEVICE_MODE:-cuda}'
    assert env.get('MAGIC_PDF_MODELS_DIR') == '${MAGIC_PDF_MODELS_DIR:-/opt/mimirq-model-cache}'
    assert 'mineru_cache:/opt/mimirq-model-cache:ro' in volumes


def test_olmocr_service_exposes_vllm_limits_and_checks_health_payload() -> None:
    services = (_load_doc('docker/docker-compose.parsers.yml').get('services') or {})
    olmocr = services['mimirq-olmocr']

    env = olmocr.get('environment') or {}
    healthcheck = olmocr.get('healthcheck') or {}
    health_cmd = ' '.join(str(part) for part in (healthcheck.get('test') or []))

    assert env.get('OLMOCR_PIPELINE_MAX_CONCURRENT_REQUESTS') == '${OLMOCR_PIPELINE_MAX_CONCURRENT_REQUESTS:-1}'
    assert env.get('OLMOCR_GPU_MEMORY_UTILIZATION') == '${OLMOCR_GPU_MEMORY_UTILIZATION:-0.35}'
    assert env.get('OLMOCR_MAX_MODEL_LEN') == '${OLMOCR_MAX_MODEL_LEN:-8192}'
    assert env.get('OLMOCR_MAX_SERVER_READY_TIMEOUT') == '${OLMOCR_MAX_SERVER_READY_TIMEOUT:-}'
    assert env.get('OLMOCR_MIN_FREE_GPU_GIB') == '${OLMOCR_MIN_FREE_GPU_GIB:-8}'
    assert 'data.get("ok")' in health_cmd
