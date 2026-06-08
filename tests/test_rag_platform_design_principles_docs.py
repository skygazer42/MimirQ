from __future__ import annotations

from pathlib import Path


def test_rag_platform_design_principles_doc_is_indexed_and_executable() -> None:
    doc_path = Path("docs/guides/rag_platform_design_principles.md")
    assert doc_path.exists()

    text = doc_path.read_text(encoding="utf-8")
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
    optimization = Path("docs/guides/rag_optimization.md").read_text(encoding="utf-8")

    assert "[RAG 平台设计准则](./guides/rag_platform_design_principles.md)" in architecture
    assert "docs/guides/rag_platform_design_principles.md" in optimization

    required_sections = (
        "# RAG 平台设计准则",
        "## 1. 平台边界",
        "## 2. 入库资产链路",
        "## 3. Metadata 合约",
        "## 4. KG 使用边界",
        "## 5. Retrieval 与 Rerank",
        "## 6. Golden Gate 与发布",
        "## 7. 集成边界",
        "## 8. 变更守护",
    )
    for section in required_sections:
        assert section in text

    required_contracts = (
        "平台只消费标准合约，不理解业务字段含义",
        "插件负责治理、切块、metadata、KG 事件、retrieval hints 和 Golden rules",
        "解析 -> 治理 -> 切块 -> metadata views -> 向量/BM25 -> KG -> Golden gate -> 发布",
        "业务字段必须声明在 `metadata_schema.json`",
        "KG 是召回增强和解释层，不是业务 fast path",
        "回答生成不能作为 retrieval 质量通过的证据",
        "Dify 是兼容适配层，不承载业务排序或业务回答逻辑",
        "任何写库、写索引、写 KG 或写 dataset metadata 的动作都必须是显式命令",
    )
    for contract in required_contracts:
        assert contract in text


def test_rag_platform_design_principles_do_not_specialize_the_platform() -> None:
    doc_path = Path("docs/guides/rag_platform_design_principles.md")
    assert doc_path.exists()
    text = doc_path.read_text(encoding="utf-8")

    def blocked(*parts: str) -> str:
        return "".join(parts)

    for forbidden in (
        blocked("changzhou", "-gov-service-knowledge"),
        blocked("20260522", "政务服务智能客服知识"),
        blocked("经", "开区"),
        blocked("天", "宁区"),
        blocked("新", "北区"),
        blocked("常", "州", "市"),
        blocked("苏", "服办"),
        blocked("社会", "保障卡"),
        blocked("就业", "创业证"),
    ):
        assert forbidden not in text
