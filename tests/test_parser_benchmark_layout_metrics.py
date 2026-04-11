from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from langchain_core.documents import Document


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "parser_benchmark.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("parser_benchmark_layout_metrics", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _install_fake_layout_benchmark_modules(monkeypatch) -> None:  # noqa: ANN001
    factory_mod = ModuleType("app.parsing.factory")

    class _Factory:
        def parse_with_provenance(self, path, *_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            path_str = str(path)
            if "layout_tagged" in path_str:
                docs = [
                    Document(
                        page_content="\n".join(
                            [
                                "L1@@1\t0\t40\t0\t10##",
                                "L2@@1\t0\t40\t20\t30##",
                                "L3@@1\t0\t40\t40\t50##",
                                "R1@@1\t60\t100\t0\t10##",
                                "R2@@1\t60\t100\t20\t30##",
                                "R3@@1\t60\t100\t40\t50##",
                            ]
                        ),
                        metadata={"page": 1},
                    )
                ]
            else:
                docs = [Document(page_content="plain text without positions", metadata={"page": 1})]
            return docs, "basic", {"attempts": [{"backend": "basic"}]}

    factory_mod.parser_factory = _Factory()
    monkeypatch.setitem(sys.modules, "app.parsing.factory", factory_mod)

    quality_doc_mod = ModuleType("app.parsing.quality.document_quality")
    quality_doc_mod.score_document_parse_quality = lambda **_kwargs: {"score": 0.91}  # noqa: E731
    monkeypatch.setitem(sys.modules, "app.parsing.quality.document_quality", quality_doc_mod)

    scorer_mod = ModuleType("app.parsing.quality.scorer")
    scorer_mod.score_pdf_quality = lambda *_args, **_kwargs: None  # noqa: E731
    monkeypatch.setitem(sys.modules, "app.parsing.quality.scorer", scorer_mod)

    text_quality_mod = ModuleType("app.parsing.quality.text_quality")

    class _TextQuality:
        def to_dict(self) -> dict[str, float]:
            return {"density": 0.95, "replacement_ratio": 0.0}

    text_quality_mod.score_parsed_text_quality = lambda *_args, **_kwargs: _TextQuality()  # noqa: E731
    monkeypatch.setitem(sys.modules, "app.parsing.quality.text_quality", text_quality_mod)


def test_reading_order_score_helper_returns_none_without_position_tags() -> None:
    mod = _load_module()

    score = mod._reading_order_score("plain text without positions")  # type: ignore[attr-defined]

    assert score is None


def test_parser_benchmark_summary_ignores_layout_cases_without_reading_order_signal(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    fixture_root = tmp_path / "fixture"

    for case_id in ("layout_tagged", "layout_plain"):
        case_root = fixture_root / case_id
        (case_root / "input").mkdir(parents=True, exist_ok=True)
        (case_root / "golden").mkdir(parents=True, exist_ok=True)
        (case_root / "input" / "sample.md").write_text("input\n", encoding="utf-8")
        (case_root / "golden" / "sample.md").write_text("golden\n", encoding="utf-8")

    (fixture_root / "manifest.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "layout_tagged_case",
                        "path": "layout_tagged/input/sample.md",
                        "golden_markdown": "layout_tagged/golden/sample.md",
                    },
                    {
                        "id": "layout_plain_case",
                        "path": "layout_plain/input/sample.md",
                        "golden_markdown": "layout_plain/golden/sample.md",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _install_fake_layout_benchmark_modules(monkeypatch)

    out_path = tmp_path / "parser_benchmark_layout.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parser_benchmark.py",
            "--input-dir",
            str(fixture_root),
            "--manifest",
            str(fixture_root / "manifest.json"),
            "--backends",
            "basic",
            "--out",
            str(out_path),
        ],
    )

    rc = mod.main()  # type: ignore[attr-defined]
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    summary = (payload.get("summary") or {}).get("basic") or {}
    by_case = {row["id"]: row for row in payload["cases"]}

    assert by_case["layout_tagged_case"]["attempts"][0]["reading_order_score"] == 1.0
    assert by_case["layout_plain_case"]["attempts"][0]["reading_order_score"] is None
    assert summary.get("mean_reading_order_score") == 1.0
    assert 0.0 <= float(summary["mean_reading_order_score"]) <= 1.0
