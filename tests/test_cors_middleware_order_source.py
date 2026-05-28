from pathlib import Path


def test_cors_middleware_wraps_rate_limit_responses() -> None:
    src = Path("app/main.py").read_text(encoding="utf-8")

    cors_index = src.index("app.add_middleware(\n    CORSMiddleware,")
    rate_limit_index = src.index("app.add_middleware(\n        RateLimitMiddleware,")
    request_id_index = src.index("app.add_middleware(RequestIDMiddleware)")

    assert rate_limit_index < request_id_index < cors_index
    assert "CORS must be the final middleware added" in src
