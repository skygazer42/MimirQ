from pathlib import Path


def test_time_context_helpers_do_not_use_naive_datetime_now() -> None:
    base_src = Path("app/rag/middleware/base.py").read_text(encoding="utf-8")
    tcadp_src = Path("app/deepdoc/parser/tcadp_parser.py").read_text(encoding="utf-8")

    assert "datetime.now().strftime(\"%Y-%m-%d %H:%M\")" not in base_src
    assert "datetime.now().strftime(\"%Y%m%d_%H%M%S\")" not in tcadp_src
