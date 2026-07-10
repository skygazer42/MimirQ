
import importlib.util
import sys
from argparse import Namespace
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "eval_rerank_pipeline_offline.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("eval_rerank_pipeline_offline", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_pipeline_summary_tracks_wins_losses_and_ties() -> None:
    mod = _load_module()

    summary = mod.build_pipeline_summary(  # type: ignore[attr-defined]
        cases_total=3,
        cases_used=3,
        k=20,
        top_k=50,
        pipeline=[{"provider": "colbert", "top_n": 20}],
        baseline={"hit": 0.4, "mrr": 0.3, "recall": 0.5, "ndcg": 0.35},
        pipeline_metrics={"hit": 0.5, "mrr": 0.31, "recall": 0.45, "ndcg": 0.4},
        case_metrics=[
            {
                "baseline": {"mrr": 0.2, "ndcg": 0.2},
                "pipeline": {"mrr": 0.5, "ndcg": 0.5},
            },
            {
                "baseline": {"mrr": 0.6, "ndcg": 0.6},
                "pipeline": {"mrr": 0.3, "ndcg": 0.3},
            },
            {
                "baseline": {"mrr": 0.4, "ndcg": 0.4},
                "pipeline": {"mrr": 0.4, "ndcg": 0.4},
            },
        ],
    )

    assert summary["schema"] == "mimirq.rerank_pipeline_eval.v1"
    assert summary["delta_counts"]["mrr"] == {"wins": 1, "losses": 1, "ties": 1}
    assert summary["delta_counts"]["ndcg"] == {"wins": 1, "losses": 1, "ties": 1}


def test_build_colbert_reranker_uses_provider_options(monkeypatch) -> None:  # noqa: ANN001
    mod = _load_module()

    captured = {}

    class _FakeColBERTReranker:
        def __init__(self, **kwargs):  # noqa: ANN003
            captured.update(kwargs)

    monkeypatch.setattr(mod, "ColBERTReranker", _FakeColBERTReranker, raising=True)

    args = Namespace(
        colbert_provider="hf",
        colbert_model_name="colbert-ir/colbertv2.0",
        colbert_device="cpu",
        colbert_batch_size=4,
        colbert_max_length=64,
        colbert_deterministic_dim=32,
    )

    _ = mod.build_colbert_reranker(args)  # type: ignore[attr-defined]
    assert captured["provider_name"] == "hf"
    assert captured["model_name"] == "colbert-ir/colbertv2.0"
    assert captured["batch_size"] == 4
    assert captured["max_length"] == 64
