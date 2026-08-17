import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

database_module = ModuleType("app.core.database")
database_module.SessionLocal = lambda: None
document_module = ModuleType("app.models.document")
document_module.Document = type("Document", (), {})
document_module.DocumentChunk = type("DocumentChunk", (), {})
bundle_module = ModuleType("app.services.regression_case_bundle")
bundle_module.REGRESSION_CASE_BUNDLE_SCHEMA_V1 = "mimirq.regression.case_bundle.v1"
sys.modules.setdefault("app.core.database", database_module)
sys.modules.setdefault("app.models.document", document_module)
sys.modules.setdefault("app.services.regression_case_bundle", bundle_module)


def _load_pack_module():
    import changzhou_gov_eval_pack as pack_module

    return pack_module


pack = _load_pack_module()


def _record(
    *,
    record_id: str,
    source_kind: str,
    title: str,
    question: str,
    answer: str,
    similar_questions: list[str] | None = None,
    fields: dict[str, str] | None = None,
    district: str = "常州市",
    source_file: str = "/tmp/source.txt",
    source_section: str = "section-a",
    knowledge_id: str = "kid-1",
) -> pack.SourceRecord:
    return pack.SourceRecord(
        record_id=record_id,
        source_kind=source_kind,
        source_file=source_file,
        source_section=source_section,
        knowledge_id=knowledge_id,
        title=title,
        district=district,
        question=question,
        answer=answer,
        similar_questions=list(similar_questions or []),
        fields=dict(fields or {}),
    )


def test_build_case_payload_preserves_bucket_order_and_target_total_trim() -> None:
    qa_record = _record(
        record_id="qa-1",
        source_kind="qa_text",
        title="居住证办理",
        question="居住证怎么办",
        answer="先准备材料。再去窗口办理。",
    )
    service_record = _record(
        record_id="svc-1",
        source_kind="service_item",
        title="非常非常长的补贴申请事项名称用于跳过口语化服务问题",
        question="补贴怎么办",
        answer="办理材料：身份证；办理地点：政务中心；收费情况：不收费",
        fields={
            "办理材料": "身份证",
            "办理地点": "政务中心",
            "收费情况": "不收费",
        },
    )
    one_thing_record = _record(
        record_id="ot-1",
        source_kind="one_thing",
        title="企业开办",
        question="企业开办怎么办",
        answer="先在线申请，再到窗口核验。",
        fields={
            "申请材料": "营业执照",
            "办理须知": "先在线申请",
        },
    )

    payload = pack.build_case_payload(
        records={
            "qa_records": [qa_record],
            "service_records": [service_record],
            "one_thing_records": [one_thing_record],
        },
        qa_count=1,
        service_count=1,
        user_count=5,
        target_total=3,
        seed=7,
    )

    assert [case["case_type"] for case in payload["cases"]] == [
        "qa_exact",
        "service_direct",
        "one_thing_user",
    ]
    assert payload["generation_policy"]["effective"] == {
        "qa_count": 1,
        "service_count": 1,
        "user_count": 1,
    }
    assert payload["generation_policy"]["summary"]["total"] == 3


def test_build_case_payload_skips_duplicate_user_questions() -> None:
    qa_record = _record(
        record_id="qa-dup",
        source_kind="qa_text",
        title="重复问法",
        question="重复问法",
        answer="按要求准备材料。",
        similar_questions=["重复问法", "换个说法", "换个说法"],
    )

    payload = pack.build_case_payload(
        records={
            "qa_records": [qa_record],
            "service_records": [],
            "one_thing_records": [],
        },
        qa_count=1,
        service_count=0,
        user_count=3,
        target_total=0,
        seed=11,
    )

    assert [case["question"] for case in payload["cases"]] == ["重复问法", "换个说法"]
    assert [case["case_type"] for case in payload["cases"]] == ["qa_exact", "user_simulated"]


class _Column:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> tuple[str, str, object]:
        return ("eq", self.name, other)

    def ilike(self, value: str) -> tuple[str, str, str]:
        return ("ilike", self.name, value)

    def is_(self, other: object) -> tuple[str, str, object]:
        return ("is", self.name, other)

    def asc(self) -> tuple[str, str]:
        return ("asc", self.name)


class _FakeDocument:
    id = _Column("document_id")
    tenant_id = _Column("document_tenant_id")
    filename = _Column("filename")
    dataset_id = _Column("dataset_id")


class _FakeDocumentChunk:
    document_id = _Column("document_id")
    tenant_id = _Column("chunk_tenant_id")
    disabled_at = _Column("disabled_at")
    content = _Column("content")
    chunk_index = _Column("chunk_index")


class _FakeQuery:
    def __init__(self, db: "_FakeDB") -> None:
        self._db = db
        self._term = ""
        self._source_filename = ""

    def join(self, *_args: object, **_kwargs: object) -> "_FakeQuery":
        return self

    def filter(self, *conditions: object) -> "_FakeQuery":
        for condition in conditions:
            if not isinstance(condition, tuple):
                continue
            operator, field_name, value = condition
            if operator == "ilike" and field_name == "content":
                self._term = value.strip("%")
            elif operator == "eq" and field_name == "filename":
                self._source_filename = str(value)
        return self

    def order_by(self, *_args: object) -> "_FakeQuery":
        return self

    def limit(self, _value: int) -> "_FakeQuery":
        return self

    def all(self) -> list[tuple[SimpleNamespace, str]]:
        self._db.calls.append((self._term, self._source_filename))
        return list(self._db.rows.get((self._term, self._source_filename), []))


class _FakeDB:
    def __init__(self, rows: dict[tuple[str, str], list[tuple[SimpleNamespace, str]]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def query(self, *_args: object) -> _FakeQuery:
        return _FakeQuery(self)

    def close(self) -> None:
        self.closed = True


def _row(
    *,
    chunk_id: str,
    document_id: str = "22222222-2222-2222-2222-222222222222",
    filename: str = "source.txt",
    content: str = "引用内容",
) -> tuple[SimpleNamespace, str]:
    return (
        SimpleNamespace(
            document_id=document_id,
            id=chunk_id,
            chunk_index=0,
            page_number=1,
            start_char=0,
            end_char=len(content),
            content=content,
        ),
        filename,
    )


def _service_case() -> dict[str, object]:
    return {
        "id": "case-1",
        "question": "我要办落户",
        "expected_answer": "",
        "case_type": "service_direct",
        "source_section": "事项知识",
        "knowledge_id": "kid-2",
        "source_file": "/tmp/source.txt",
        "source_record_title": "落户办理",
        "case_generation": "gen-1",
        "dimension_fields": ["办理地点"],
        "evidence_clauses": [
            {
                "required_terms": [
                    "事项名称：落户办理",
                    "办理地点：",
                    "市民中心A厅窗口办理",
                ]
            }
        ],
    }


def test_resolve_reference_sources_uses_anchor_then_fallback_search_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB(
        {
            ("市民中心A厅窗口办理", ""): [
                _row(
                    chunk_id="33333333-3333-3333-3333-333333333333",
                    content="市民中心A厅窗口办理",
                )
            ]
        }
    )
    monkeypatch.setattr(pack, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(pack, "Document", _FakeDocument, raising=True)
    monkeypatch.setattr(pack, "DocumentChunk", _FakeDocumentChunk, raising=True)
    monkeypatch.setattr(pack, "and_", lambda *args: ("and", args), raising=True)

    bundle, report = pack.resolve_reference_sources(
        [_service_case()],
        dataset_id="11111111-1111-1111-1111-111111111111",
        tenant_id="00000000-0000-0000-0000-000000000000",
    )

    assert db.calls == [
        ("事项名称：落户办理", "source.txt"),
        ("我要办落户", "source.txt"),
        ("事项名称：落户办理", ""),
        ("我要办落户", ""),
        ("市民中心A厅窗口办理", "source.txt"),
        ("市民中心A厅窗口办理", ""),
    ]
    assert db.closed is True
    assert report["resolved"] == 1
    assert report["unresolved"] == 0
    assert bundle["items"][0]["reference_sources"] == [
        {
            "document_id": "22222222-2222-2222-2222-222222222222",
            "chunk_id": "33333333-3333-3333-3333-333333333333",
            "chunk_index": 0,
            "page_number": 1,
            "start_char": 0,
            "end_char": len("市民中心A厅窗口办理"),
            "quote": "市民中心A厅窗口办理",
            "label": "term:市民中心A厅窗口办理",
        }
    ]


def test_resolve_reference_sources_reports_unresolved_terms_in_search_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB({})
    monkeypatch.setattr(pack, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(pack, "Document", _FakeDocument, raising=True)
    monkeypatch.setattr(pack, "DocumentChunk", _FakeDocumentChunk, raising=True)
    monkeypatch.setattr(pack, "and_", lambda *args: ("and", args), raising=True)

    bundle, report = pack.resolve_reference_sources(
        [_service_case()],
        dataset_id="11111111-1111-1111-1111-111111111111",
        tenant_id="00000000-0000-0000-0000-000000000000",
    )

    assert bundle["items"] == []
    assert report["unresolved_items"] == [
        {
            "case_id": "case-1",
            "question": "我要办落户",
            "source_file": "/tmp/source.txt",
            "search_terms": [
                "事项名称：落户办理",
                "我要办落户",
                "市民中心A厅窗口办理",
            ],
        }
    ]


def test_resolve_reference_sources_invalid_dataset_id_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pack, "SessionLocal", lambda: _FakeDB({}), raising=True)

    with pytest.raises(ValueError):
        pack.resolve_reference_sources(
            [_service_case()],
            dataset_id="not-a-uuid",
            tenant_id="00000000-0000-0000-0000-000000000000",
        )
