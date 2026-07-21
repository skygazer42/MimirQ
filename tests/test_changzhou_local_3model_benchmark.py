from scripts.changzhou_local_3model_benchmark import (
    _llm_url,
    _run_summary,
    build_generation_messages,
)


def test_build_generation_messages_limits_and_labels_evidence() -> None:
    records = [{"title": f"标题{i}", "content": f"内容{i}"} for i in range(1, 7)]

    messages = build_generation_messages("怎么办理？", records)

    assert messages[0]["role"] == "system"
    assert "只能依据" in messages[0]["content"]
    assert "用户问题：怎么办理？" in messages[1]["content"]
    assert "[证据 1] 标题1" in messages[1]["content"]
    assert "[证据 5] 标题5" in messages[1]["content"]
    assert "标题6" not in messages[1]["content"]


def test_run_summary_requires_every_case_to_succeed() -> None:
    items = [
        {"ok": True, "latency_ms": 100, "retrieval_latency_ms": 20, "generation_latency_ms": 80},
        {"ok": False, "latency_ms": 300},
    ]

    summary = _run_summary(items, cases=2, resumed=0)

    assert summary["complete"] is False
    assert summary["succeeded"] == 1
    assert summary["latency_ms"]["mean"] == 200.0
    assert _llm_url("http://local/v1") == "http://local/v1/chat/completions"
