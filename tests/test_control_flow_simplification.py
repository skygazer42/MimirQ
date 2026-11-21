from itertools import product

import pytest

from scripts.simplify_defensive_control_flow import canonical, inspect_python


def rewrite(source):  # noqa: ANN001, ANN202
    return inspect_python(source, apply=True)[0]


def test_nested_conditions_keep_short_circuit_evaluation_order():
    source = """def choose(a, b, c, visited):
    if visited.append("a") is None and a:
        if visited.append("b") is None and b:
            if visited.append("c") is None and c:
                return "selected"
    return "absent"
"""
    result = rewrite(source)
    assert result.count("    if ") == 1
    before, after = {}, {}
    exec(source, before)
    exec(result, after)
    for values in product((False, True), repeat=3):
        original_visits, rewritten_visits = [], []
        assert before["choose"](*values, original_visits) == after["choose"](*values, rewritten_visits)
        assert original_visits == rewritten_visits


@pytest.mark.parametrize("terminal", ["return 'done'", "raise ValueError('bad')"])
def test_else_after_an_exit_becomes_an_ordinary_following_statement(terminal):  # noqa: ANN001
    source = f"""def choose(flag):
    if flag:
        {terminal}
    else:
        value = 4
        return value
"""
    result = rewrite(source)
    assert "else:" not in result
    assert canonical(source) == canonical(result)


def test_loop_break_else_can_be_flattened_without_changing_loop_else():
    source = """def choose(values):
    for value in values:
        if value:
            break
        else:
            continue
    else:
        return "empty"
    return "found"
"""
    result = rewrite(source)
    assert canonical(source) == canonical(result)
    before, after = {}, {}
    exec(source, before)
    exec(result, after)
    for values in ([], [0], [0, 1], [1, 0]):
        assert before["choose"](values) == after["choose"](values)


def test_conditions_preserve_or_and_assignment_expression_precedence():
    source = """def choose(a, b, c):
    if a or b:
        if value := c:
            return value
    return None
"""
    result = rewrite(source)
    assert "(a or b) and (value := c)" in result
    assert canonical(source) == canonical(result)


def test_comments_unicode_and_crlf_are_preserved():
    source = 'def choose(a, b):\r\n    if a:\r\n        # 保留说明\r\n        if b:\r\n            return "完成"\r\n'
    result = rewrite(source)
    assert "# 保留说明\r\n" in result
    assert "\n" not in result.replace("\r\n", "")
    assert canonical(source) == canonical(result)


def test_multiline_literal_content_is_never_reindented():
    source = '''def choose(a, b):
    if a:
        if b:
            return """content
                significant whitespace
            """
'''
    result = rewrite(source)
    assert result.count("    if ") == 1
    assert canonical(result) == canonical(source)


def test_external_conversion_is_reported_for_review_not_blindly_deleted():
    source = """def parse(value):
    if value is None:
        return None
    try:
        return value if isinstance(value, int) else int(value)
    except ValueError:
        return None
"""
    result, findings, _count = inspect_python(source, apply=True)
    assert result == source
    assert any(item["rule"] == "guarded-reparse-review" for item in findings)


def test_else_of_an_elif_must_not_be_lifted_out_of_the_whole_chain():
    source = """def choose(a, b):
    if a:
        value = "first"
    elif b:
        return "second"
    else:
        value = "third"
    return value
"""
    assert rewrite(source) == source


def test_inline_else_statement_is_kept_intact():
    source = """def choose(a):
    if a:
        return 1
    else: return 2
"""
    assert rewrite(source) == source


def test_exit_ladder_can_be_flattened_in_passes_without_changing_its_values():
    source = """def choose(a, b):
    if a:
        return "first"
    elif b:
        return "second"
    else:
        return "third"
"""
    result = rewrite(rewrite(source))
    assert "elif" not in result
    assert "else:" not in result
    assert canonical(result) == canonical(source)


def test_condition_comments_are_retained_but_type_pragmas_are_not_moved():
    source = """def choose(a, b):
    if a:  # user choice
        if b:  # allowed state
            return True
"""
    result = rewrite(source)
    assert "# user choice" in result
    assert "# allowed state" in result
    assert result.count("    if ") == 1
    pragma = source.replace("# user choice", "# noqa: SIM102")
    assert rewrite(pragma) == pragma
