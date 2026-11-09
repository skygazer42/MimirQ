import pytest

from app.parsing.enrich.table_structure_adapter import table_extraction_from_text_grid
from app.parsing.quality.grits import compute_table_grits


@pytest.mark.parametrize("cell, expected", [(None, []), (0, [["0"]]), (False, [["False"]]), (1, [["1"]]), (True, [["True"]])])
def test_normalized_table_text_grid_preserves_scalar_values(cell, expected):
    table = table_extraction_from_text_grid(columns=["value"], rows=[[cell]])

    assert table.rows == expected


@pytest.mark.parametrize("cell, rendered, expected", [(None, "", None), (0, "0", 1.0), (False, "false", 1.0), (1, "1", 1.0), (True, "true", 1.0)])
def test_table_quality_scoring_compares_scalar_cell_text(cell, rendered, expected):
    assert compute_table_grits(pred_table=[[cell]], gold_table=[[rendered]])["content"] == expected


def test_table_quality_scoring_does_not_treat_zero_as_a_blank_cell():
    assert compute_table_grits(pred_table=[[0]], gold_table=[[""]]) == {
        "topology": 1.0, "content": 0.0, "f1": 0.5,
    }


def test_table_text_grid_preserves_scalar_column_labels():
    table = table_extraction_from_text_grid(columns=[0, False, None], rows=[["number", "flag", "blank"]])

    assert table.columns == ["0", "False", ""]


def test_table_text_grid_keeps_falsy_values_when_the_parser_has_rendered_them():
    table = table_extraction_from_text_grid(columns=["number", "flag"], rows=[["0", "False"]])

    assert table.rows == [["0", "False"]]
    assert [cell.text for cell in table.cells] == ["number", "flag", "0", "False"]
    assert compute_table_grits(pred_table=table.rows, gold_table=[["0", "false"]])["content"] == 1.0
