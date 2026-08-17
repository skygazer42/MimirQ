
import datetime as dt

from langchain_core.documents import Document

if not hasattr(dt, "UTC"):
    dt.UTC = dt.timezone.utc

from app.rag.chunking.strategies.openapi_spec import OpenAPISpecChunker, looks_like_openapi_spec
from app.rag.chunking.strategies.outline import OutlineChunker, looks_like_outline
from app.rag.chunking.strategies.pdf_layout import PDFLayoutChunker
from app.rag.chunking.strategies.sop_steps import SOPStepsChunker, looks_like_sop
from app.rag.chunking.strategies.yaml_manifest import YAMLManifestChunker, looks_like_yaml_manifest


def test_yaml_manifest_chunker_preserves_multi_doc_offsets_and_metadata() -> None:
    text = (
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        "  name: alpha\n"
        "data:\n"
        "  k: v\n"
        "---\n"
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: beta\n"
        "spec:\n"
        "  replicas: 2\n"
    )

    assert looks_like_yaml_manifest(text) is True

    chunks = YAMLManifestChunker(500, 0).split_documents([Document(page_content=text, metadata={"source": "x"})])

    assert len(chunks) == 2
    first, second = chunks

    assert first.metadata == {
        "source": "x",
        "chunk_strategy": "yaml_manifest",
        "start_char": 0,
        "end_char": 67,
        "doc_type_kwd": "yaml",
        "yaml_doc_index": 0,
        "yaml_doc_count": 2,
        "yaml_api_version": "v1",
        "yaml_kind": "ConfigMap",
        "yaml_name": "alpha",
        "yaml_id": "ConfigMap/alpha",
        "chunk_index": 0,
    }
    assert second.metadata == {
        "source": "x",
        "chunk_strategy": "yaml_manifest",
        "start_char": 68,
        "end_char": 151,
        "doc_type_kwd": "yaml",
        "yaml_doc_index": 1,
        "yaml_doc_count": 2,
        "yaml_api_version": "apps/v1",
        "yaml_kind": "Deployment",
        "yaml_name": "beta",
        "yaml_id": "Deployment/beta",
        "chunk_index": 1,
    }
    assert text[first.metadata["start_char"] : first.metadata["end_char"]].strip() == first.page_content
    assert text[second.metadata["start_char"] : second.metadata["end_char"]].strip() == second.page_content


def test_sop_steps_chunker_preserves_step_numbers_titles_and_preamble_offsets() -> None:
    text = (
        "背景说明\n"
        "这里是较长的准备说明，用来保证启发式长度足够，并保留前导段落。" * 4 + "\n"
        "步骤一：准备环境\n"
        "确认账号、权限、网络和依赖都已经准备完成。\n"
        "步骤二：执行发布\n"
        "依次运行检查、部署和验证命令，记录关键输出信息。\n"
        "步骤三：确认结果\n"
        "核对服务状态、告警面板、回滚入口以及值班交接说明。\n"
    )

    assert looks_like_sop(text) is True

    chunks = SOPStepsChunker(500, 0).split_documents([Document(page_content=text, metadata={"source": "x"})])

    assert len(chunks) == 4
    preamble, step_one, step_two, step_three = chunks

    assert preamble.page_content == (
        "背景说明\n"
        "这里是较长的准备说明，用来保证启发式长度足够，并保留前导段落。背景说明\n"
        "这里是较长的准备说明，用来保证启发式长度足够，并保留前导段落。背景说明\n"
        "这里是较长的准备说明，用来保证启发式长度足够，并保留前导段落。背景说明\n"
        "这里是较长的准备说明，用来保证启发式长度足够，并保留前导段落。"
    )
    assert preamble.metadata == {
        "source": "x",
        "chunk_strategy": "sop_steps",
        "start_char": 0,
        "end_char": 144,
        "chunk_index": 0,
    }

    assert step_one.metadata["sop_step_heading"] == "步骤一：准备环境"
    assert step_one.metadata["sop_step_no"] == "一"
    assert step_one.metadata["sop_step_title"] == "准备环境"
    assert step_one.metadata["start_char"] == 145

    assert step_two.metadata["sop_step_heading"] == "步骤二：执行发布"
    assert step_two.metadata["sop_step_no"] == "二"
    assert step_two.metadata["sop_step_title"] == "执行发布"

    assert step_three.metadata["sop_step_heading"] == "步骤三：确认结果"
    assert step_three.metadata["sop_step_no"] == "三"
    assert step_three.metadata["sop_step_title"] == "确认结果"
    assert step_three.metadata["chunk_index"] == 3


def test_pdf_layout_chunker_preserves_page_and_bbox_metadata() -> None:
    text = "Alpha@@1\t10\t40\t10\t20##\nBeta@@1\t60\t90\t21\t32##\nGamma@@2\t10\t40\t33\t44##\n"

    chunks = PDFLayoutChunker(20, 0).split_documents([Document(page_content=text, metadata={"source": "x"})])

    assert len(chunks) == 1
    chunk = chunks[0]
    layout = chunk.metadata["layout"]

    assert chunk.page_content == "Alpha\nBeta\nGamma"
    assert chunk.metadata["chunk_strategy"] == "pdf_layout"
    assert chunk.metadata["start_char"] == 0
    assert chunk.metadata["end_char"] == 67
    assert chunk.metadata["page"] == 1
    assert chunk.metadata["page_number"] == 1
    assert layout["schema"] == "mimirq.pdf_layout.v1"
    assert layout["pages"] == [1, 2]
    assert layout["tag_count"] == 3
    assert layout["page_layout"][0]["column_count"] == 2
    assert layout["page_layout"][0]["bbox"] == {"x0": 10.0, "x1": 90.0, "y0": 10.0, "y1": 32.0}
    assert layout["page_layout"][1]["column_count"] == 1
    assert layout["page_layout"][1]["columns"][0]["bbox"] == {"x0": 10.0, "x1": 40.0, "y0": 33.0, "y1": 44.0}


def test_outline_chunker_preserves_hierarchy_and_resets_top_level_path() -> None:
    text = (
        "Preamble\n"
        "This is introductory text that keeps the sample above the heuristic length.\n"
        "1. Start\n"
        "Body paragraph.\n"
        "1.1 Detail\n"
        "Nested paragraph.\n"
        "2. End\n"
        "Final paragraph.\n"
    )

    assert looks_like_outline(text) is True

    chunks = OutlineChunker(500, 0).split_documents([Document(page_content=text, metadata={"source": "x"})])

    assert len(chunks) == 4
    _, top_level, nested, final = chunks

    assert top_level.metadata["outline_heading"] == "1. Start"
    assert top_level.metadata["outline_level"] == 1
    assert top_level.metadata["outline_path"] == ["1. Start"]
    assert top_level.metadata["outline_path_str"] == "1. Start"
    assert top_level.metadata["header_path"] == "1. Start"

    assert nested.metadata["outline_heading"] == "1.1 Detail"
    assert nested.metadata["outline_level"] == 2
    assert nested.metadata["outline_path"] == ["1. Start", "1.1 Detail"]
    assert nested.metadata["outline_path_str"] == "1. Start / 1.1 Detail"
    assert nested.metadata["header_path"] == "1. Start / 1.1 Detail"

    assert final.metadata["outline_heading"] == "2. End"
    assert final.metadata["outline_level"] == 1
    assert final.metadata["outline_path"] == ["2. End"]
    assert final.metadata["outline_path_str"] == "2. End"
    assert final.metadata["header_path"] == "2. End"


def test_openapi_chunker_preserves_preamble_path_method_and_index_metadata() -> None:
    text = (
        "openapi: 3.1.0\n"
        "info:\n"
        "  title: Demo\n"
        "paths:\n"
        "  /pets:\n"
        "    get:\n"
        "      summary: List pets\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n"
        "  /pets/{id}:\n"
        "    post:\n"
        "      summary: Save pet\n"
        "      requestBody:\n"
        "        content:\n"
        "          application/json:\n"
        "            schema:\n"
        "              type: object\n"
    )

    assert looks_like_openapi_spec(text) is True

    chunks = OpenAPISpecChunker(500, 0).split_documents([Document(page_content=text, metadata={"source": "x"})])

    assert len(chunks) == 3
    preamble, pets, pet_by_id = chunks

    assert preamble.metadata == {
        "source": "x",
        "chunk_strategy": "openapi_spec",
        "start_char": 0,
        "end_char": 41,
        "openapi_preamble": True,
        "openapi_version": "3.1.0",
        "doc_type_kwd": "openapi",
        "chunk_index": 0,
    }
    assert preamble.page_content == "openapi: 3.1.0\ninfo:\n  title: Demo\npaths:"

    assert pets.metadata["openapi_path"] == "/pets"
    assert pets.metadata["openapi_methods"] == ["GET"]
    assert pets.metadata["openapi_path_index"] == 0
    assert pets.metadata["openapi_path_count"] == 2
    assert text[pets.metadata["start_char"] : pets.metadata["end_char"]].strip() == pets.page_content

    assert pet_by_id.metadata["openapi_path"] == "/pets/{id}"
    assert pet_by_id.metadata["openapi_methods"] == ["POST"]
    assert pet_by_id.metadata["openapi_path_index"] == 1
    assert pet_by_id.metadata["openapi_path_count"] == 2
    assert "schema:" in pet_by_id.page_content
