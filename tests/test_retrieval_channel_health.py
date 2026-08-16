from app.rag.retrieval.hybrid.channel_health import RetrievalChannelHealth


def test_retrieval_channel_health_publishes_sorted_channels_and_failures() -> None:
    health = RetrievalChannelHealth()
    metrics = {
        "retrieval_degraded": False,
        "degraded_reasons": [],
        "all_retrieval_channels_failed": False,
    }

    health.started("vector")
    health.started("bm25")
    health.succeeded("bm25")
    health.failed("vector", ConnectionError("vector down"))
    health.failed("scope", LookupError("scope missing"))

    health.publish(metrics)

    assert metrics["retrieval_degraded"] is True
    assert metrics["degraded_reasons"] == [
        {"channel": "scope", "error_type": "LookupError"},
        {"channel": "vector", "error_type": "ConnectionError"},
    ]
    assert metrics["attempted_channels"] == ["bm25", "scope", "vector"]
    assert metrics["successful_channels"] == ["bm25"]
    assert metrics["all_retrieval_channels_failed"] is False


def test_retrieval_channel_health_marks_total_channel_failure() -> None:
    health = RetrievalChannelHealth()
    metrics = {}

    health.failed("scope", LookupError("scope missing"))
    health.publish(metrics)

    assert metrics["retrieval_degraded"] is True
    assert metrics["degraded_reasons"] == [{"channel": "scope", "error_type": "LookupError"}]
    assert metrics["attempted_channels"] == ["scope"]
    assert metrics["successful_channels"] == []
    assert metrics["all_retrieval_channels_failed"] is True
