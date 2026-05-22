from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_server_module():
    path = Path("docker/qianfanocr/server.py").resolve()
    spec = importlib.util.spec_from_file_location("qianfanocr_server_under_test", str(path))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_qianfanocr_builds_baidu_qianfan_v2_chat_url(monkeypatch):
    module = _load_server_module()
    monkeypatch.setattr(module, "_SERVER_URL", "https://qianfan.baidubce.com/v2")

    assert module._build_api_url() == "https://qianfan.baidubce.com/v2/chat/completions"


def test_qianfanocr_accepts_full_chat_completions_url(monkeypatch):
    module = _load_server_module()
    monkeypatch.setattr(module, "_SERVER_URL", "https://qianfan.baidubce.com/v2/chat/completions")

    assert module._build_api_url() == "https://qianfan.baidubce.com/v2/chat/completions"


def test_qianfanocr_keeps_openai_compatible_v1_default(monkeypatch):
    module = _load_server_module()
    monkeypatch.setattr(module, "_SERVER_URL", "http://vision.local:8000/v1")

    assert module._build_api_url() == "http://vision.local:8000/v1/chat/completions"


def test_qianfanocr_uses_short_prompt_for_baidu_online_endpoint():
    module = _load_server_module()

    assert module._default_prompt_for_server("https://qianfan.baidubce.com/v2") == "OCR this image."


def test_qianfanocr_keeps_markdown_prompt_for_openai_compatible_endpoint():
    module = _load_server_module()

    assert "markdown" in module._default_prompt_for_server("http://vision.local:8000/v1").lower()
