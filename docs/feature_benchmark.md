# 功能对标与缺口矩阵（企业级 / 开源 RAG 平台）

更新时间：2026-01-26

本文件用于把 **主流企业级产品** 与 **主流开源项目** 的能力拆解成可落地的工程项，并对照 MimirQ 当前实现情况，产出“选择性集成”的路线图（本次实现见下方「本次集成范围」）。

## 1) 对标样本（参考方向）

### 企业级产品（代表性）
- **Glean**：以大量企业连接器为核心，强调“权限继承/安全裁剪（security trimming）”的企业搜索体验。
- **Azure AI Search（Microsoft）**：提供文档级访问控制（Document Level Access Control, DLAC）与“security trimming”的检索过滤思路。
- **Amazon Kendra**：提供对接企业身份系统/连接器的访问控制与最佳实践。
- **Elastic / OpenSearch**：文档级安全（DLS）、字段级安全（FLS）等企业检索访问控制能力。
- **Pinecone / 各类向量数据库**：通过 metadata filtering / server-side filtering 支持权限裁剪、分片、租户隔离等。

### 开源项目（代表性）
- **RAGFlow**：全链路 RAG/知识库工作台，包含解析、分块、向量检索、聊天等模块化能力。
- **Dify**：面向应用构建与知识库的产品化体验（含分隔符切块、工作流等）。
- **Haystack / LangChain / LlamaIndex**：偏工程框架（pipeline、chunking、retrieval、eval、observability），例如 LlamaIndex 的层级切分与 AutoMergingRetriever 思路。
- **Flowise / Langflow**：可视化编排（agent、RAG、工具调用），强调“可配置、可观察、可迭代”。
- **AnythingLLM / OpenWebUI**：更偏“自托管应用”，突出本地化/隐私/易用性（连接器、chunk 参数、轻量管理）。

## 2) 功能维度拆解

### A. 数据接入（Connectors / Ingestion）
常见能力：
- 多数据源连接器：Google Drive、Confluence、Notion、Slack、GitHub、Jira、SharePoint、Web URL、S3/MinIO 等
- 增量同步：定时任务、diff/版本、软删除、重试与告警
- 入库前治理：清洗、去噪、脱敏、去页眉页脚、语言检测、结构抽取

MimirQ 现状：
- 已有：文件上传（含 batch）、多解析器、治理清洗、预览链路
- 本次选择性集成（已落地）：**URL 导入**（作为“连接器骨架”的第一步）

### B. 切块（Chunking）
常见能力：
- 多策略：递归、token、语义句子、按结构（Markdown/章节/表格/对话/FAQ/代码）等
- 策略参数化：例如 parent-child 的子块比例/最小值，separator 的 preset/custom/keep/max
- 可复现与审计：保存“本次生效参数”，支持 A/B 调参
- 后处理：短块合并、重复块去重、相邻块扩展、超大文档裁剪策略
- offsets/定位：chunk 在原文中的 start/end，便于高亮与溯源

MimirQ 现状：
- 已有：大量策略、chunk-preview（含 A/B、导出、SKIP、质量提示）、去重/截断
- 本次选择性集成（已落地）：
  - **chunk_strategy_params 入库贯通**（preview/ingest 对齐，且回显生效参数便于复现）
  - **offsets rebase**（多段解析 join 后统一 offsets，保障高亮/溯源一致）
  - **短块合并（min chunk size）**（可选后处理，减少过碎块）

### C. 检索与上下文组装（Retrieval）
常见能力：
- hybrid（vector + BM25）、RRF 融合、MMR 多样性、reranker（cross-encoder/LLM）
- parent-child / multi-vector：检索小块、回填父块或更大上下文（AutoMerging 思路）
- 权限裁剪：向量端 metadata filter + DB 校验兜底

MimirQ 现状：
- 已有：hybrid、RRF、MMR、reranker、neighbor window
- 本次选择性集成（已落地）：**parent-child 自动回填父块**（避免只拿到过碎 child）

### D. 可观测与评测（Observability / Eval）
常见能力：
- trace：请求→检索→重排→生成的全链路可视化
- eval：离线评测、回归集、在线反馈闭环（LangSmith/TruLens/Phoenix/RAGAS 等）

MimirQ 现状：
- 已有：RAGAS、feedback 表、Sentry/Prometheus/OTEL 依赖与初始化
- 本次选择性集成（已落地）：补齐 **Phoenix/OTEL 的配置说明**（让能力“可用起来”）

## 3) 本次集成范围（落地项）

本次改造会优先实现以下能力（按价值/复杂度排序）：
1. **chunk_strategy_params 入库贯通**：preview → manual 入库 → upload 入库路径一致，可审计、可复现
2. **offsets rebase**：多页解析/多段文档 join 后 offsets 统一，保障前端高亮/溯源一致
3. **短块合并**：可选后处理，降低“过碎块”导致的噪声与检索碎片化
4. **parent-child 自动回填父块**：检索 child 时回填/合并 parent，提升上下文完整性
5. **URL 导入（连接器骨架）**：安全可控的 http/https 拉取 → 走标准入库流程
6. **Phoenix/OTEL 文档**：把已有 OTEL 能力落到可操作配置

> 未纳入本次实现但建议作为下一阶段：文档级 ACL/security trimming（向量端过滤 + DB 兜底）、更多连接器（Confluence/Notion/GitHub 等）、评测面板/回归集管理、可视化工作流编排。

实现入口（建议先从这几个文件看起）：
- URL 导入：`docs/guides/url_ingest.md`（后端 API + 安全开关 + 前端入口）
- Chunk 参数贯通：`web/components/pipeline-options-panel.tsx`（pipeline 参数）、`app/api/v1/documents.py`（preview/ingest 对齐）
- 短块合并与 offsets：`app/parsing/processors/processor.py`
- parent-child 回填：`app/rag/retriever.py`
- Phoenix/OTEL：`docs/guides/otel_phoenix.md`

## 4) 参考链接（对标资料）

企业级（安全裁剪 / 文档级安全）：
- Azure AI Search：Security trimming（按用户/组裁剪检索结果）https://learn.microsoft.com/en-us/azure/search/search-security-trimming
- Amazon Kendra：Access control（基于权限的检索过滤）https://docs.aws.amazon.com/kendra/latest/dg/access-control.html
- Elastic：Document level security（DLS）https://www.elastic.co/guide/en/elasticsearch/reference/current/document-level-security.html
- OpenSearch：Document-level security（DLS）https://docs.opensearch.org/latest/security/access-control/document-level-security/
- OpenSearch：Field-level security（FLS）https://docs.opensearch.org/latest/security/access-control/field-level-security/

开源/产品化平台（连接器 / 切块能力）：
- RAGFlow：Chunk templates（内置分块模板与策略说明）https://ragflow.io/docs/dev/chunk_templates
- Dify：Chunk settings（知识库切块参数与策略）https://docs.dify.ai/guides/knowledge-base/chunk-settings
- AnythingLLM：Authenticated website scraping（网页连接器/抓取）https://docs.anythingllm.com/agent/agents/agent-tools/authenticated-website-scraping
- Open WebUI：RAG（知识库/RAG 集成说明）https://docs.openwebui.com/tutorial/rag/
- Langflow：Components & Visual Workflows（可视化编排/组件）https://docs.langflow.org/components
- LangChain：ParentDocumentRetriever（检索 chunk 回填父文档）https://js.langchain.com/docs/how_to/parent_document_retriever/
- LangChain：Recursive text splitter（递归分隔符切分 / keep separator 等）https://python.langchain.com/docs/how_to/recursive_text_splitter/
- LlamaIndex：AutoMergingRetriever（父子层级自动合并检索结果）https://docs.llamaindex.ai/en/stable/api_reference/retrievers/auto_merging/
- Haystack：DocumentSplitter（split_length/split_overlap 参数化）https://docs.haystack.deepset.ai/docs/2.20/documentsplitter
- Unstructured：Chunking（含 by-similarity 语义切块思路）https://docs.unstructured.io/platform/chunking
- Phoenix（Arize）：Tracing / OTEL / Evals（企业级可观测与评测）https://arize.com/docs/phoenix
