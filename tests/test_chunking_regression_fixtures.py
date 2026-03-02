from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.rag.chunking.factory import chunker_factory
from app.rag.preprocessing.normalization import normalize_text


def _sha256_text(text: str) -> str:
    norm = normalize_text(text or "", normalize_line_endings=True, remove_control_chars=True).strip()
    return hashlib.sha256(norm.encode("utf-8", "ignore")).hexdigest()


def _stable_meta_subset(meta: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "chunk_strategy",
        "chunk_strategy_selected",
        "chunk_strategy_preset",
        "chunk_role",
        "chunk_semantic_role",
        "doc_type_kwd",
        "content_type",
        "header_path",
        "parent_id",
        "parent_node_id",
    )
    out: dict[str, Any] = {}
    for k in keep:
        v = meta.get(k)
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
    return out


def test_chunking_regression_fixtures_are_stable() -> None:
    """
    Golden regression suite for chunking strategies.

    This test is intentionally strict: any change to chunk boundaries/content will require
    updating the fixture expectations (which is the point).
    """
    root = Path(__file__).resolve().parent / "fixtures" / "chunking_regression"
    cases_path = root / "cases.json"
    expected_path = root / "expected.json"

    assert cases_path.exists(), f"Missing cases fixture: {cases_path}"
    assert expected_path.exists(), f"Missing expected fixture: {expected_path}"

    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    case_list = cases.get("cases") if isinstance(cases, dict) else None
    assert isinstance(case_list, list) and case_list, "cases.json must contain non-empty cases[]"

    expected_cases = expected.get("cases") if isinstance(expected, dict) else None
    assert isinstance(expected_cases, dict) and expected_cases, "expected.json must contain cases{}"

    for case in case_list:
        assert isinstance(case, dict)
        cid = str(case.get("id") or "").strip()
        assert cid, "case.id required"

        strategy = str(case.get("strategy") or "").strip()
        chunk_size = int(case.get("chunk_size") or 0)
        chunk_overlap = int(case.get("chunk_overlap") or 0)
        kwargs = case.get("kwargs") if isinstance(case.get("kwargs"), dict) else {}

        content_file = str(case.get("content_file") or "").strip()
        assert content_file, f"{cid}: content_file required"
        content_path = root / content_file
        assert content_path.exists(), f"{cid}: missing content file {content_path}"
        content = content_path.read_text(encoding="utf-8")

        chunker = chunker_factory.get_chunker(strategy, chunk_size, chunk_overlap, **kwargs)
        out_docs = chunker.split_documents([Document(page_content=content, metadata={"source": "fixture"})])

        got = {
            "strategy": strategy,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "kwargs": kwargs,
            "chunk_count": len(out_docs),
            "chunks": [
                {
                    "sha256": _sha256_text(d.page_content or ""),
                    "len": len(d.page_content or ""),
                    "meta": _stable_meta_subset(dict(d.metadata or {})),
                }
                for d in out_docs
            ],
        }

        exp = expected_cases.get(cid)
        assert exp is not None, f"expected.json missing case id: {cid}"
        assert got == exp, f"chunking regression mismatch for case: {cid}"

