from __future__ import annotations

from pathlib import Path


def test_paddlevl_container_installs_python_docx_for_doc_parser_exports() -> None:
    requirements = Path("docker/paddlevl/requirements.txt").read_text(encoding="utf-8")

    assert "python-docx" in requirements
