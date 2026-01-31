import uuid

from app.parsing.processors.processor import DocumentProcessorService
from app.rag.preprocessing.processor import GovernanceStats


class _DummyDoc:
    def __init__(self):
        self.doc_metadata = {}


class _DummyQuery:
    def __init__(self, doc):
        self._doc = doc

    def filter(self, *args, **kwargs):  # noqa: ANN001, ANN002
        return self

    def first(self):  # noqa: ANN201
        return self._doc


class _DummyDB:
    def __init__(self, doc):
        self._doc = doc

    def query(self, model):  # noqa: ANN001, ANN201
        return _DummyQuery(self._doc)

    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def test_processor_records_governance_rule_packs_in_document_metadata():
    svc = DocumentProcessorService()
    doc = _DummyDoc()
    db = _DummyDB(doc)

    stats = GovernanceStats(documents=1, changed=1, applied_rules=1)

    svc._record_governance_metadata(  # type: ignore[arg-type]
        db,
        uuid.uuid4(),
        uuid.uuid4(),
        stats,
        rule_packs=["web_cookie_banners", "web_navigation"],
    )

    assert doc.doc_metadata.get("governance_rule_packs") == ["web_cookie_banners", "web_navigation"]


def test_build_combined_governance_rules_includes_rule_packs():
    from app.parsing.processors.processor import _build_combined_governance_rules

    class _Eff:
        governance_regex_rules = []
        governance_rule_packs = ["web_cookie_banners"]

    rules = _build_combined_governance_rules(_Eff())
    assert rules is not None
    assert any("cookie" in (r.pattern or "").lower() for r in rules)

