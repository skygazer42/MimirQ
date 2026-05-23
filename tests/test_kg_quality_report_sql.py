from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.rag.kg.models import KgRelation
from app.rag.kg.quality import kg_denoiser


def test_missing_relation_references_expr_avoids_json_equality_operator() -> None:
    expr = kg_denoiser._missing_relation_references_expr(KgRelation.references)
    compiled = str(expr.compile(dialect=postgresql.dialect()))

    assert 'kg_relations."references" IS NULL' in compiled
    assert '::JSON' not in compiled
