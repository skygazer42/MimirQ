import ast
from types import SimpleNamespace

import pytest

from scripts.audit_defensive_code import PythonAudit

FIELDS = {"LABEL": "str", "COUNT": "int", "RATIO": "float", "OPTIONAL": None, "MODE": "str"}


def rewrite(source):  # noqa: ANN001, ANN202
    return PythonAudit(source, FIELDS, {"MODE"}).analyze()[1]


def test_unicode_and_crlf_source_spans_preserve_surrounding_text():
    source = 'from app.infrastructure.config import settings\r\nresult = {"标签": str(getattr(settings, "LABEL", "") or "")}\r\n'
    assert rewrite(source) == 'from app.infrastructure.config import settings\r\nresult = {"标签": settings.LABEL}\r\n'


def test_identity_cast_removal_preserves_operator_precedence_and_non_neutral_default():
    source = 'from app.infrastructure.config import settings\nresult = 5 * int(getattr(settings, "COUNT", 0) or 3)\n'
    result = rewrite(source)
    assert "getattr" not in result
    for count in (0, 1, -3, 12):
        original_ast = ast.parse(source).body[1].value
        rewritten_ast = ast.parse(result).body[1].value
        env = {"settings": SimpleNamespace(COUNT=count)}
        assert eval(compile(ast.Expression(original_ast), "before", "eval"), env) == eval(
            compile(ast.Expression(rewritten_ast), "after", "eval"), env
        )


def test_multiline_conversion_keeps_the_expression_parenthesized():
    source = """from app.infrastructure.config import settings
result = 5 * int(
    getattr(settings, "COUNT", 0)
    or 3
)
"""
    result = rewrite(source)
    ast.parse(result)
    expression = ast.parse(result).body[1].value
    for count in (0, 2):
        assert eval(
            compile(ast.Expression(expression), "after", "eval"),
            {
                "settings": SimpleNamespace(COUNT=count),
            },
        ) == 5 * (count or 3)


@pytest.mark.parametrize(
    "source",
    [
        'from app.infrastructure.config import settings\ndef f(settings):\n return str(getattr(settings, "LABEL", ""))\n',
        'from app.infrastructure.config import settings\nsettings = fake()\nresult = str(getattr(settings, "LABEL", ""))\n',
        'from app.infrastructure.config import settings\ndef f(getattr):\n return getattr(settings, "LABEL", "")\n',
        "from app.infrastructure.config import settings\nstr = custom\nresult = str(settings.LABEL)\n",
        'from app.infrastructure.config import settings\nresult = [getattr(settings, "LABEL", "fallback") for settings in rows]\n',
        'from app.infrastructure.config import settings\nclass C:\n settings = fake()\n result = getattr(settings, "LABEL", "fallback")\n',
        "from app.infrastructure.config import settings\nclass C:\n str = custom\n result = str(settings.LABEL)\n",
        'from app.infrastructure.config import settings\nif flag:\n settings = fake()\nresult = getattr(settings, "LABEL", "fallback")\n',
        "from app.infrastructure.config import settings\nfor str in wrappers:\n result = str(settings.LABEL)\n",
        'from app.infrastructure.config import settings\ndef f(value=(settings := fake())):\n return getattr(settings, "LABEL", "fallback")\n',
        'from app.infrastructure.config import settings\nf = lambda: ((settings := fake()), getattr(settings, "LABEL", "fallback"))\n',
    ],
)
def test_shadowed_names_are_not_treated_as_live_settings_or_builtins(source):  # noqa: ANN001
    assert rewrite(source) == source


def test_optional_and_float_serialization_casts_remain_explicit():
    source = 'from app.infrastructure.config import settings\na = str(getattr(settings, "OPTIONAL", None) or "")\nb = float(settings.RATIO)\nc = float(getattr(settings, "RATIO", 0))\n'
    result = rewrite(source)
    assert 'str(settings.OPTIONAL or "")' in result
    assert "float(settings.RATIO)" in result
    assert "c = float(settings.RATIO)" in result


def test_unsupported_fields_and_fallbacks_with_side_effects_are_not_automatically_removed():
    source = 'from app.infrastructure.config import settings\na = getattr(settings, "MISSING", "")\nb = getattr(settings, "LABEL", side_effect())\n'
    assert rewrite(source) == source


def test_boundary_uuid_parser_is_reported_without_deleting_validation():
    source = """from uuid import UUID
def _coerce_uuid(raw: object):
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None
"""
    findings, result, count = PythonAudit(source, FIELDS, set()).analyze()
    assert result == source
    assert count == 0
    assert any(item["rule"] == "coercion-helper" for item in findings)


def test_parent_conversion_render_does_not_bypass_comprehension_scope():
    source = """from app.infrastructure.config import settings
result = int(int(sum([int(settings.COUNT) for int in [lambda value: value * 2]])))
"""
    assert rewrite(source) == source


def test_nested_dictionary_edits_are_applied_in_source_order():
    source = """from app.infrastructure.config import settings
result = int(int(len({str(settings.LABEL): str(settings.LABEL), str(settings.MODE): "value"})))
"""
    result = rewrite(source)
    env = {"settings": SimpleNamespace(LABEL="label", MODE="mode")}
    original = ast.parse(source).body[1].value
    changed = ast.parse(result).body[1].value
    assert eval(compile(ast.Expression(original), "before", "eval"), env) == eval(
        compile(ast.Expression(changed), "after", "eval"), env
    )


def test_double_string_cast_may_normalize_a_custom_string_subclass():
    source = "result = str(str(value)).upper()\n"
    assert rewrite(source) == source


def test_local_builtin_import_remains_an_explicit_conversion():
    source = """from app.infrastructure.config import settings
def f():
    from builtins import ascii as str
    return str(settings.LABEL)
"""
    assert rewrite(source) == source


def test_primitive_conversion_exception_can_be_narrowed_without_changing_malformed_input():
    source = """def _coerce_number(value):
    try:
        return int(value)
    except Exception:
        return None
"""
    _findings, result, _edits = PythonAudit(source, FIELDS, set(), narrow_errors=True).analyze()
    env = {}
    exec(result, env)
    assert env["_coerce_number"]("bad") is None
    assert env["_coerce_number"]("0") == 0

    class Broken:
        def __int__(self):
            raise RuntimeError("implementation defect")

    with pytest.raises(RuntimeError, match="implementation defect"):
        env["_coerce_number"](Broken())


def test_primitive_rule_does_not_change_db_or_external_call_exception_policies():
    source = """def fetch(db):
    try:
        return int(db.query().first())
    except Exception:
        return None
"""
    _findings, result, count = PythonAudit(source, FIELDS, set(), narrow_errors=True).analyze()
    assert result == source
    assert count == 0


@pytest.mark.parametrize("expression", ["int(collection.num_entities)", "int(row['count'])", "int(value.strip())"])
def test_property_index_and_unknown_method_boundaries_are_not_primitive_only(expression):  # noqa: ANN001
    source = f"""def read(value, row, collection):
    try:
        return {expression}
    except Exception:
        return 0
"""
    _findings, result, count = PythonAudit(source, FIELDS, set(), narrow_errors=True).analyze()
    assert result == source
    assert count == 0
