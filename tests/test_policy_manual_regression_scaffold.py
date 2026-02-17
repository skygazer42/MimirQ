from __future__ import annotations

import json
from pathlib import Path

from app.rag.policy.clause_refs import extract_clause_refs


def test_policy_regression_cases_file_is_valid_jsonl() -> None:
    path = Path("tests/fixtures/policy_manual_cases.jsonl")
    assert path.exists()
    for line in path.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        assert "question" in obj
        assert "expected_refs" in obj
        refs = extract_clause_refs(obj["question"])
        assert isinstance(refs, list)

