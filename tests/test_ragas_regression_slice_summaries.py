from __future__ import annotations


def test_merge_summary_includes_retrieval_slices_by_bucket() -> None:
    from app.rag.evaluation import ragas as mod

    eval_items = [
        {
            "item_meta": {
                "slice_file_type": "pdf",
                "slice_language": "zh",
                "slice_directory": "a",
                "slice_hit_type": "vector",
                "slice_quality_bucket": "high_density",
                "slice_pipeline_hash": "ph1",
                "retrieval_recall": 1.0,
                "retrieval_hit_at_20": True,
                "abstain_triggered": False,
            }
        },
        {
            "item_meta": {
                "slice_file_type": "pdf",
                "slice_language": "zh",
                "slice_directory": "a",
                "slice_hit_type": "keyword",
                "slice_quality_bucket": "low_density",
                "slice_pipeline_hash": "ph1",
                "retrieval_recall": 0.0,
                "retrieval_hit_at_20": False,
                "abstain_triggered": True,
            }
        },
        {
            "item_meta": {
                "slice_file_type": "md",
                "slice_language": "en",
                "slice_directory": "b",
                "slice_hit_type": "vector",
                "slice_quality_bucket": "high_density",
                "slice_pipeline_hash": "ph2",
                "retrieval_recall": 1.0,
                "retrieval_hit_at_20": True,
                "abstain_triggered": False,
            }
        },
    ]

    out = mod._merge_summary_with_regression_gate({"items": 3}, eval_items=eval_items)  # noqa: SLF001
    slices = out.get("retrieval_slices")
    assert isinstance(slices, dict)

    ft = slices.get("file_type")
    assert isinstance(ft, dict)
    buckets = ft.get("buckets")
    assert isinstance(buckets, list)
    pdf = next((b for b in buckets if isinstance(b, dict) and b.get("key") == "pdf"), None)
    assert pdf is not None
    assert pdf.get("items") == 2
    assert pdf.get("retrieval_recall") == 0.5
    assert pdf.get("retrieval_hit_at_20") == 0.5
    assert pdf.get("abstain_rate") == 0.5

    ht = slices.get("hit_type")
    assert isinstance(ht, dict)
    buckets = ht.get("buckets")
    assert isinstance(buckets, list)
    vec = next((b for b in buckets if isinstance(b, dict) and b.get("key") == "vector"), None)
    assert vec is not None
    assert vec.get("items") == 2
    assert vec.get("retrieval_recall") == 1.0
    assert vec.get("retrieval_hit_at_20") == 1.0

    qb = slices.get("quality")
    assert isinstance(qb, dict)
    buckets = qb.get("buckets")
    assert isinstance(buckets, list)
    high = next((b for b in buckets if isinstance(b, dict) and b.get("key") == "high_density"), None)
    assert high is not None
    assert high.get("items") == 2
    assert high.get("retrieval_recall") == 1.0

    ph = slices.get("pipeline_hash")
    assert isinstance(ph, dict)
    buckets = ph.get("buckets")
    assert isinstance(buckets, list)
    ph1 = next((b for b in buckets if isinstance(b, dict) and b.get("key") == "ph1"), None)
    assert ph1 is not None
    assert ph1.get("items") == 2
    assert ph1.get("retrieval_recall") == 0.5
