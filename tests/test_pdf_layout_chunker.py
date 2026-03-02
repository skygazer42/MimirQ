from __future__ import annotations

import re

from langchain_core.documents import Document


def test_pdf_layout_chunker_splits_by_position_blocks_and_emits_layout_meta():  # noqa: ANN001
    from app.rag.chunking.factory import chunker_factory

    raw = (
        "A1@@1\t10\t100\t10\t20##\n\n"
        "B1@@1\t300\t420\t10\t20##\n\n"
        "A2@@1\t12\t102\t30\t40##\n\n"
        "B2@@1\t310\t400\t30\t40##"
    )
    tag_re = re.compile(r"@@([0-9-]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##")
    matches = list(tag_re.finditer(raw))
    assert len(matches) == 4

    doc = Document(page_content=raw, metadata={"file_type": "pdf"})
    chunker = chunker_factory.get_chunker("pdf_layout", chunk_size=7, chunk_overlap=0)
    chunks = chunker.split_documents([doc])

    assert len(chunks) == 2

    c0 = chunks[0]
    assert c0.metadata.get("chunk_strategy") == "pdf_layout"
    assert "@@" not in c0.page_content
    assert "##" not in c0.page_content
    assert c0.page_content == "A1\n\nB1"

    assert c0.metadata.get("start_char") == 0
    assert c0.metadata.get("end_char") == matches[1].end()
    assert raw[int(c0.metadata["start_char"]) : int(c0.metadata["end_char"])].count("@@") >= 2

    assert c0.metadata.get("page") == 1
    layout0 = c0.metadata.get("layout")
    assert isinstance(layout0, dict)
    assert layout0.get("schema") == "mimirq.pdf_layout.v1"
    assert layout0.get("pages") == [1]
    assert isinstance(layout0.get("page_layout"), list) and layout0["page_layout"]
    assert layout0["page_layout"][0].get("column_count") == 2

    c1 = chunks[1]
    assert c1.page_content == "A2\n\nB2"
    assert c1.metadata.get("start_char") == matches[1].end()
    assert c1.metadata.get("end_char") == matches[3].end()

