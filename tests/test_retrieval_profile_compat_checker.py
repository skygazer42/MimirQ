from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_retrieval_profile_compat_checker_passes_with_defaults(capsys) -> None:  # noqa: ANN001
    mod = _load_script("scripts/check_retrieval_profile_compat.py")
    rc = mod.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "compatible" in out.lower()


def test_retrieval_profile_compat_checker_rejects_hybrid_ce_with_llm_reranker(capsys) -> None:  # noqa: ANN001
    mod = _load_script("scripts/check_retrieval_profile_compat.py")
    rc = mod.main(
        [
            "--retrieval-profile",
            "hybrid_ce",
            "--enable-reranker",
            "true",
            "--reranker-provider",
            "llm",
        ]
    )
    assert rc != 0
    err = (capsys.readouterr().err or "").lower()
    assert "hybrid_ce" in err
    assert "cross_encoder" in err


def test_makefile_has_retrieval_profile_compat_target() -> None:
    text = Path("Makefile").read_text(encoding="utf-8")
    assert re.search(r"^check-retrieval-profile-compat:$", text, flags=re.MULTILINE)

