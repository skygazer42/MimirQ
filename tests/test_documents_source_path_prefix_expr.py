from sqlalchemy.dialects import postgresql


def test_documents_source_path_prefix_filter_expr_compiles():
    from app.api.v1.documents import _source_path_prefix_expr

    expr = _source_path_prefix_expr("foo/bar/")
    assert expr is not None

    sql = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "source_path" in sql
    assert "LIKE" in sql.upper()
    assert "foo/bar/" in sql
