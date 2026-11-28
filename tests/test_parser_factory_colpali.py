import pytest

from app.infrastructure.model_policy import RetiredModelProviderError
from app.rag.ingestion.parsing.factory import ParserFactory


@pytest.mark.parametrize("backend", ["colpali", "col-pali", "colqwen", "col-qwen"])
def test_colpali_pdf_backend_is_retired(tmp_path, backend):
    pdf_path = tmp_path / "visual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    with pytest.raises(RetiredModelProviderError, match="has been retired"):
        ParserFactory().parse(pdf_path, parser_backend=backend, allow_fallback=False)
