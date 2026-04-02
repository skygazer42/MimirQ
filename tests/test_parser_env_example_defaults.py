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
        values = _read_env(env_path)
        assert values["MINERU_ENABLED"] == "false"
        assert values["DEEPSEEK_OCR_ENABLED"] == "false"
        assert values["ETL4LLM_ENABLED"] == "false"
        assert values["ETL4LLM_API_URL"] == ""
        assert values["MAGIC_PDF_ENABLED"] == "false"
