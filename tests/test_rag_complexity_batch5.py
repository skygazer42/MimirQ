
from langchain_core.documents import Document

from app.rag.chunking.strategies.ansible_playbook import AnsiblePlaybookChunker
from app.rag.chunking.strategies.csv_rows import CsvRowsChunker
from app.rag.chunking.strategies.junit_xml import JUnitXMLChunker
from app.rag.chunking.strategies.sentence_window import SentenceWindowChunker
from app.rag.chunking.strategies.text_hierarchy import TextHierarchyChunker
from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown
from app.rag.preprocessing.markdown_canonical import canonicalize_markdown
from app.rag.preprocessing.pii_anonymizer import PiiMatch, find_pii_matches
from app.rag.preprocessing.references import ReferencesTrimResult, trim_references_section
from app.rag.preprocessing.tables import TableNormalizeResult, normalize_markdown_tables


def _chunk_summary(chunker, text: str) -> list[tuple[str, dict[str, object]]]:
    return [
        (
            chunk.page_content,
            {key: value for key, value in chunk.metadata.items() if key != "source"},
        )
        for chunk in chunker.split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    ]


def test_ansible_playbook_chunker_preserves_preamble_offsets_and_play_metadata() -> None:
    text = (
        "# generated\n"
        "- name: Setup web\n"
        "  hosts: web\n"
        "  tasks:\n"
        '    - debug: msg="a"\n'
        "- hosts: db\n"
        "  name: Configure db\n"
        "  tasks:\n"
        '    - debug: msg="b"\n'
    )

    assert _chunk_summary(AnsiblePlaybookChunker(10_000, 0), text) == [
        (
            "# generated",
            {
                "chunk_strategy": "ansible_playbook",
                "start_char": 0,
                "end_char": 11,
                "ansible_playbook_preamble": True,
                "doc_type_kwd": "ansible",
                "chunk_index": 0,
            },
        ),
        (
            '- name: Setup web\n  hosts: web\n  tasks:\n    - debug: msg="a"',
            {
                "chunk_strategy": "ansible_playbook",
                "start_char": 12,
                "end_char": 72,
                "doc_type_kwd": "ansible",
                "ansible_play_index": 0,
                "ansible_play_count": 2,
                "ansible_play_name": "Setup web",
                "ansible_hosts": "web",
                "chunk_index": 1,
            },
        ),
        (
            '- hosts: db\n  name: Configure db\n  tasks:\n    - debug: msg="b"',
            {
                "chunk_strategy": "ansible_playbook",
                "start_char": 73,
                "end_char": 135,
                "doc_type_kwd": "ansible",
                "ansible_play_index": 1,
                "ansible_play_count": 2,
                "ansible_play_name": "Configure db",
                "ansible_hosts": "db",
                "chunk_index": 2,
            },
        ),
    ]


def test_csv_rows_chunker_preserves_row_overlap_and_offsets() -> None:
    text = "".join(f"row {idx}: value={idx}\n" for idx in range(1, 6))

    assert _chunk_summary(CsvRowsChunker(31, 16), text) == [
        (
            "row 1: value=1\nrow 2: value=2\n",
            {
                "chunk_strategy": "csv_rows",
                "start_char": 0,
                "end_char": 30,
                "csv_row_count": 2,
                "csv_row_start": 1,
                "csv_row_end": 2,
                "chunk_index": 0,
            },
        ),
        (
            "row 2: value=2\nrow 3: value=3\n",
            {
                "chunk_strategy": "csv_rows",
                "start_char": 15,
                "end_char": 45,
                "csv_row_count": 2,
                "csv_row_start": 2,
                "csv_row_end": 3,
                "chunk_index": 1,
            },
        ),
        (
            "row 3: value=3\nrow 4: value=4\n",
            {
                "chunk_strategy": "csv_rows",
                "start_char": 30,
                "end_char": 60,
                "csv_row_count": 2,
                "csv_row_start": 3,
                "csv_row_end": 4,
                "chunk_index": 2,
            },
        ),
        (
            "row 4: value=4\nrow 5: value=5\n",
            {
                "chunk_strategy": "csv_rows",
                "start_char": 45,
                "end_char": 75,
                "csv_row_count": 2,
                "csv_row_start": 4,
                "csv_row_end": 5,
                "chunk_index": 3,
            },
        ),
        (
            "row 5: value=5\n",
            {
                "chunk_strategy": "csv_rows",
                "start_char": 60,
                "end_char": 75,
                "csv_row_count": 1,
                "csv_row_start": 5,
                "csv_row_end": 5,
                "chunk_index": 4,
            },
        ),
    ]


def test_junit_xml_chunker_preserves_preamble_offsets_and_case_metadata() -> None:
    text = (
        '<?xml version="1.0"?>\n<testsuite>\n'
        '<testcase classname="suite.A" name="test_one"><failure/></testcase>\n'
        '<testcase classname="suite.B" name="test_two" />\n'
        "</testsuite>\n"
    )

    assert _chunk_summary(JUnitXMLChunker(10_000, 0), text) == [
        (
            '<?xml version="1.0"?>\n<testsuite>',
            {
                "chunk_strategy": "junit_xml",
                "start_char": 0,
                "end_char": 33,
                "junit_xml_preamble": True,
                "doc_type_kwd": "junit",
                "chunk_index": 0,
            },
        ),
        (
            '<testcase classname="suite.A" name="test_one"><failure/></testcase>',
            {
                "chunk_strategy": "junit_xml",
                "start_char": 34,
                "end_char": 101,
                "doc_type_kwd": "junit",
                "junit_case_index": 0,
                "junit_case_count": 2,
                "junit_case": "test_one",
                "junit_classname": "suite.A",
                "chunk_index": 1,
            },
        ),
        (
            '<testcase classname="suite.B" name="test_two" />',
            {
                "chunk_strategy": "junit_xml",
                "start_char": 102,
                "end_char": 150,
                "doc_type_kwd": "junit",
                "junit_case_index": 1,
                "junit_case_count": 2,
                "junit_case": "test_two",
                "junit_classname": "suite.B",
                "chunk_index": 2,
            },
        ),
    ]


def test_sentence_window_chunker_preserves_current_overlap_boundaries() -> None:
    text = "Alpha one. Beta two. Gamma three. Delta four."

    assert _chunk_summary(SentenceWindowChunker(25, 15), text) == [
        (
            "Alpha one. Beta two.",
            {
                "chunk_strategy": "sentence_window",
                "start_char": 0,
                "end_char": 20,
                "sentence_count": 3,
                "chunk_index": 0,
            },
        ),
        (
            "e. Beta two. Gamma three.",
            {
                "chunk_strategy": "sentence_window",
                "start_char": 8,
                "end_char": 33,
                "sentence_count": 3,
                "chunk_index": 1,
            },
        ),
        (
            " Gamma three. Delta four.",
            {
                "chunk_strategy": "sentence_window",
                "start_char": 20,
                "end_char": 45,
                "sentence_count": 2,
                "chunk_index": 2,
            },
        ),
        (
            " Delta four.",
            {
                "chunk_strategy": "sentence_window",
                "start_char": 33,
                "end_char": 45,
                "sentence_count": 1,
                "chunk_index": 3,
            },
        ),
    ]


def test_text_hierarchy_chunker_preserves_order_and_hierarchy_keys() -> None:
    text = "Intro line.\n\n## Header\nBody one. Body two.\n- item one\n- item two\n"

    chunks = TextHierarchyChunker(0, 0).split_documents([Document(page_content=text, metadata={"source": "fixture"})])

    assert [chunk.metadata["chunk_role"] for chunk in chunks] == [
        "paragraph",
        "sentence",
        "paragraph",
        "sentence",
        "sentence",
        "sentence",
        "paragraph",
        "sentence",
        "paragraph",
        "sentence",
    ]
    assert chunks[0].metadata["hierarchy_node_key"] == "md:b0a9210cbacbe43135f79a9fece68ffc"
    assert chunks[2].metadata["hierarchy_node_key"] == "md:cdee5bbe1cbdb545ebdcce95619f5dcd"
    assert chunks[6].metadata["hierarchy_node_key"] == "md:cace2b31783471bf5e6d0686d61c0a46"
    assert chunks[8].metadata["hierarchy_node_key"] == "md:f4f884da30958a8ca6a6f2fbfb0ca0bf"
    assert chunks[2].metadata["hierarchy_prev_sibling_key"] == chunks[0].metadata["hierarchy_node_key"]
    assert chunks[2].metadata["hierarchy_next_sibling_key"] == chunks[6].metadata["hierarchy_node_key"]
    assert chunks[3].metadata["parent_id"] == chunks[2].metadata["hierarchy_node_key"]
    assert chunks[4].metadata["hierarchy_prev_sibling_key"] == chunks[3].metadata["hierarchy_node_key"]
    assert chunks[5].metadata["hierarchy_next_sibling_key"] is None


def test_hierarchical_chunk_markdown_preserves_code_fence_table_and_sibling_links() -> None:
    data = hierarchical_chunk_markdown("Lead\n\n```py\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")

    assert [paragraph["text"] for paragraph in data["paragraphs"]] == [
        "Lead\n",
        "```py\nprint(1)\n```\n",
        "| a | b |\n|---|---|\n| 1 | 2 |\n",
    ]
    assert [paragraph["hierarchy_node_key"] for paragraph in data["paragraphs"]] == [
        "md:4cc39cd2a251e2684256490d03caa839",
        "md:a69a389f0374890015d6077c0ad2ae0d",
        "md:666aa063e4addd58c20d1c3874f7628b",
    ]
    assert data["paragraphs"][1]["hierarchy_prev_sibling_key"] == data["paragraphs"][0]["hierarchy_node_key"]
    assert data["paragraphs"][1]["hierarchy_next_sibling_key"] == data["paragraphs"][2]["hierarchy_node_key"]
    assert [sentence["text"] for sentence in data["sentences"][1:4]] == ["```py\n", "print(1)\n", "```\n"]
    assert data["sentences"][4]["hierarchy_parent_key"] == data["paragraphs"][2]["hierarchy_node_key"]
    assert data["sentences"][5]["hierarchy_prev_sibling_key"] == data["sentences"][4]["hierarchy_node_key"]
    assert data["sentences"][6]["hierarchy_next_sibling_key"] is None


def test_canonicalize_markdown_normalizes_headings_lists_and_tables() -> None:
    result = canonicalize_markdown("##Heading\n| a | b |\n| ---- | :---: |\n|  1  |  2  |\n")

    assert result.text == "## Heading\n| a | b |\n| --- | :---: |\n| 1 | 2 |"
    assert result.headings_changed == 1
    assert result.tables == 1
    assert result.table_rows_changed == 2
    assert result.changed is True


def test_find_pii_matches_preserves_validator_order_overlap_and_invalid_ip_fallback() -> None:
    text = (
        "email a@example.com ip 10.0.0.1 ssn 123-45-6789 "
        "card 4111 1111 1111 1111 phone +1 (415) 555-1212 bad 999.999.999.999"
    )

    assert find_pii_matches(text, max_matches=10) == [
        PiiMatch(kind="email", start=6, end=19, text="a@example.com"),
        PiiMatch(kind="ip", start=23, end=31, text="10.0.0.1"),
        PiiMatch(kind="ssn", start=36, end=47, text="123-45-6789"),
        PiiMatch(kind="credit_card", start=53, end=72, text="4111 1111 1111 1111"),
        PiiMatch(kind="phone", start=79, end=96, text="+1 (415) 555-1212"),
        PiiMatch(kind="phone", start=101, end=116, text="999.999.999.999"),
    ]


def test_trim_references_section_preserves_threshold_and_collapsed_tail_behavior() -> None:
    multiline = (
        "Intro\n"
        "body\n"
        "more\n\n"
        "# References\n"
        "[1] one\n"
        "[2] two\n"
        "[3] three\n"
        "[4] four\n"
        "[5] five\n"
        "[6] six\n"
        "[7] seven\n"
        "[8] eight\n"
    )
    collapsed = "Intro\nMore context\n# References\n[1] one [2] two [3] three [4] four\n"

    assert trim_references_section(multiline, min_position_ratio=0.2, min_lines_after=8) == ReferencesTrimResult(
        text="Intro\nbody\nmore",
        removed_lines=10,
        changed=True,
    )
    assert trim_references_section(collapsed, min_position_ratio=0.2, min_lines_after=3, citation_like_ratio=0.0) == (
        ReferencesTrimResult(
            text="Intro\nMore context",
            removed_lines=2,
            changed=True,
        )
    )


def test_normalize_markdown_tables_preserves_real_table_detection_without_touching_non_tables() -> None:
    assert normalize_markdown_tables("| a | b |\n| -- | :---: |\n|  1  |  2  |\n| 3 |4|\n") == TableNormalizeResult(
        text="| a | b |\n| --- | :---: |\n| 1 | 2 |\n| 3 | 4 |",
        tables=1,
        rows_changed=3,
        changed=True,
    )
    assert normalize_markdown_tables("keep a | b\n\n```text\n| x | y |\n```\n") == TableNormalizeResult(
        text="keep a | b\n\n```text\n| x | y |\n```",
        tables=0,
        rows_changed=0,
        changed=True,
    )
