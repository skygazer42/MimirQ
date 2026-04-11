from __future__ import annotations

from app.parsing.quality.reading_order import score_reading_order


def test_score_reading_order_missing_tags_returns_no_signal() -> None:
    res = score_reading_order("hello world\n")
    assert res["schema"] == "mimirq.reading_order_score.v1"
    assert res["score"] is None
    assert "missing_position_tags" in (res.get("warnings") or [])


def test_score_reading_order_perfect_order_is_high() -> None:
    md = "\n".join(
        [
            "First@@1\t0\t100\t0\t10##",
            "Second@@1\t0\t100\t20\t30##",
            "Third@@1\t0\t100\t40\t50##",
            "Fourth@@1\t0\t100\t60\t70##",
            "Fifth@@1\t0\t100\t80\t90##",
            "Sixth@@1\t0\t100\t100\t110##",
        ]
    )
    res = score_reading_order(md, min_blocks=2)
    assert res["score"] == 1.0
    assert res["nid"] == 0.0
    assert res["blocks"] == 6


def test_score_reading_order_reversed_order_is_low() -> None:
    md = "\n".join(
        [
            "Sixth@@1\t0\t100\t100\t110##",
            "Fifth@@1\t0\t100\t80\t90##",
            "Fourth@@1\t0\t100\t60\t70##",
            "Third@@1\t0\t100\t40\t50##",
            "Second@@1\t0\t100\t20\t30##",
            "First@@1\t0\t100\t0\t10##",
        ]
    )
    res = score_reading_order(md, min_blocks=2)
    assert res["score"] is not None and float(res["score"]) <= 0.05
    assert res["nid"] is not None and float(res["nid"]) >= 0.95


def test_score_reading_order_two_column_prefers_left_then_right() -> None:
    # Expected order: left column (top->bottom) then right column (top->bottom).
    md = "\n".join(
        [
            "L1@@1\t0\t40\t0\t10##",
            "L2@@1\t0\t40\t20\t30##",
            "L3@@1\t0\t40\t40\t50##",
            "R1@@1\t60\t100\t0\t10##",
            "R2@@1\t60\t100\t20\t30##",
            "R3@@1\t60\t100\t40\t50##",
        ]
    )
    res = score_reading_order(md, min_blocks=2)
    assert res["score"] == 1.0
    assert res["column_pages"] == 1


def test_score_reading_order_tolerates_full_width_header_on_two_column_page() -> None:
    md = "\n".join(
        [
            "Header@@1\t0\t100\t0\t10##",
            "L1@@1\t0\t40\t20\t30##",
            "L2@@1\t0\t40\t40\t50##",
            "R1@@1\t60\t100\t20\t30##",
            "R2@@1\t60\t100\t40\t50##",
            "Footer@@1\t0\t100\t90\t100##",
        ]
    )
    res = score_reading_order(md, min_blocks=2)
    assert res["score"] is not None and float(res["score"]) >= 0.95
    assert res["column_pages"] == 1


def test_score_reading_order_tolerates_full_width_tail_block_after_two_columns() -> None:
    md = "\n".join(
        [
            "L1@@1\t0\t40\t0\t10##",
            "L2@@1\t0\t40\t20\t30##",
            "R1@@1\t60\t100\t0\t10##",
            "R2@@1\t60\t100\t20\t30##",
            "Summary@@1\t0\t100\t55\t65##",
            "Tail@@1\t0\t100\t75\t85##",
        ]
    )
    res = score_reading_order(md, min_blocks=2)
    assert res["score"] is not None and float(res["score"]) >= 0.95
    assert res["column_pages"] == 1
