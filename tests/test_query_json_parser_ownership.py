import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "text,expected,data,method",
    [
        ('{"value":3}', "object", {"value": 3}, "raw"),
        ('["one","two"]', "array", ["one", "two"], "raw"),
        ('```json\n["one"]\n```', "array", ["one"], "code_fence"),
        ('{"queries":["one"]}', "array", ["one"], "raw:wrapped:queries"),
        ("- one\n2. two\n- one", "array", ["one", "two"], "lines"),
        ("7", "any", 7, "raw"),
    ],
)
def test_shared_query_json_parser_preserves_existing_formats_and_metadata(text, expected, data, method):
    from app.rag.llm.response_parsing import parse_json_from_text

    result, metadata = parse_json_from_text(text, expected=expected)
    assert result == data
    assert metadata == {"ok": True, "method": method, "error": None}


def test_core_and_orchestrator_use_the_same_actual_parser() -> None:
    from app.rag.llm.response_parsing import parse_json_from_text
    from app.rag.retrieval.planning import model_expansion
    from app.rag.runtime import model_routing

    assert model_routing.parse_json_from_text is model_expansion.parse_json_from_text is parse_json_from_text


def test_empty_and_invalid_objects_are_not_reported_as_parse_success() -> None:
    from app.rag.llm.response_parsing import parse_json_from_text

    assert parse_json_from_text("", expected="array") == (None, {"ok": False, "method": None, "error": "empty"})
    value, metadata = parse_json_from_text("{", expected="object")
    assert value is None and metadata["ok"] is False and metadata["error"]


def test_json_parser_executes_without_loading_claim_or_rag_runtime_stacks() -> None:
    script = """
import importlib.abc
import sys
class NoRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'app.rag.engine','app.rag.retriever','app.rag.retrieval.orchestrator','app.rag.core.claim_verifier','app.rag.core.claim_nli_verifier'}:
            raise AssertionError('Parser imports unrelated runtime: ' + fullname)
sys.meta_path.insert(0, NoRuntime())
from app.rag.llm.response_parsing import parse_json_from_text
value, metadata = parse_json_from_text('{"queries":["one"]}', expected='array')
assert value == ['one'] and metadata['method'] == 'raw:wrapped:queries'
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
