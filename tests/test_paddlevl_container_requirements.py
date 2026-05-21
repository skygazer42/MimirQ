from __future__ import annotations

from pathlib import Path


def test_paddlevl_container_installs_python_docx_for_doc_parser_exports() -> None:
    requirements = Path("docker/paddlevl/requirements.txt").read_text(encoding="utf-8")

    assert "python-docx" in requirements


def test_paddlevl_server_runs_doc_parser_off_event_loop_with_timeout() -> None:
    source = Path("docker/paddlevl/server.py").read_text(encoding="utf-8")

    assert "run_in_threadpool" in source
    assert "PADDLEOCR_PIPELINE_TIMEOUT_SEC" in source
    assert "subprocess.TimeoutExpired" in source
