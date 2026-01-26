import json

import pytest
from fastapi import HTTPException

from app.services.dataset_precheck_service import _list_finding_from_jsonl


def test_precheck_findings_from_jsonl_basic_and_exact_dup(tmp_path):
    p = tmp_path / "files.jsonl"
    lines = [
        {
            "name": "a.txt",
            "file_type": "txt",
            "file_size": 10,
            "text_characters": 10,
            "estimated_text": False,
            "findings": ["pii"],
            "pii_hits": {"phone": 1},
            "secrets_hits": {},
            "file_sha256": "a" * 64,
        },
        {
            "name": "b.txt",
            "file_type": "txt",
            "file_size": 12,
            "text_characters": 12,
            "estimated_text": False,
            "findings": [],
            "pii_hits": {},
            "secrets_hits": {},
            "file_sha256": "a" * 64,
        },
        {
            "name": "c.txt",
            "file_type": "txt",
            "file_size": 14,
            "text_characters": 14,
            "estimated_text": False,
            "findings": ["parse_failed"],
            "pii_hits": {},
            "secrets_hits": {},
            "file_sha256": "b" * 64,
        },
    ]
    with p.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")

    res = _list_finding_from_jsonl(jsonl_path=p, finding_key="pii", skip=0, limit=50)
    assert res.total == 1
    assert len(res.items) == 1
    assert res.items[0].name == "a.txt"

    dup = _list_finding_from_jsonl(jsonl_path=p, finding_key="exact_dup", skip=0, limit=50)
    assert dup.total == 2
    assert {x.name for x in dup.items} == {"a.txt", "b.txt"}

    dup_page2 = _list_finding_from_jsonl(jsonl_path=p, finding_key="exact_dup", skip=1, limit=1)
    assert dup_page2.total == 2
    assert len(dup_page2.items) == 1


def test_precheck_findings_unknown_key_400(tmp_path):
    p = tmp_path / "files.jsonl"
    p.write_text("", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        _list_finding_from_jsonl(jsonl_path=p, finding_key="nope", skip=0, limit=10)
    assert exc.value.status_code == 400

