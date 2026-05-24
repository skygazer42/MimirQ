from __future__ import annotations

from pathlib import Path


def _read_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_env_examples_keep_optional_live_parsers_disabled_by_default() -> None:
    for env_path in (".env.example", "docker/.env.example"):
        if not Path(env_path).exists():
            continue
        values = _read_env(env_path)
        assert values["MINERU_ENABLED"] == "false"
        assert values["DEEPSEEK_OCR_ENABLED"] == "false"
        assert values["ETL4LLM_ENABLED"] == "false"
        assert values["ETL4LLM_API_URL"] == ""
        assert values["MAGIC_PDF_ENABLED"] == "false"


def test_root_env_example_documents_single_gpu_parser_sharing_defaults() -> None:
    values = _read_env(".env.example")

    assert values["MINERU_MODEL_SOURCE"] == "local"
    assert values["MINERU_VLM_GPU_MEMORY_UTILIZATION"] == "0.45"
    assert values["PADDLEOCR_PIPELINE_TIMEOUT_SEC"] == "540"
    assert values["PADDLE_VL_TIMEOUT_SEC"] == "600"
    assert values["OLMOCR_GPU_MEMORY_UTILIZATION"] == "0.35"
    assert values["OLMOCR_MAX_MODEL_LEN"] == "8192"
    assert values["OLMOCR_PIPELINE_MAX_CONCURRENT_REQUESTS"] == "1"
    assert values["OLMOCR_MIN_FREE_GPU_GIB"] == "8"
