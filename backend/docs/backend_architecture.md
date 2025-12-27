# MimirQ Backend（建议架构/职责划分）

目标：让“上传文档 -> 解析 -> 人工调整 -> 数据治理 -> 分块 ->（可选）事件原子化/KG -> 索引 -> 召回/对话”在代码结构上可一眼读懂。

## 1) 推荐流水线（Stage）

1. **Parsing（文件 -> Markdown）**
   - 输入：PDF/MD/TXT/ZIP(+images)
   - 输出：Markdown + 图片引用 + 质量评分（可选）
2. **Governance（Markdown -> Clean Markdown）**
   - 正则清洗、空行/空白规范化、控制字符移除等
   - 输出：可用于“人工调整”和“后续分块”的 Markdown
3. **Chunking（Markdown -> Chunks）**
   - 滑动窗口/递归分块/Token 分块/固定模板分块等
4. **KG（Chunks -> 事件原子/实体/关系）（可选）**
   - 从文本块抽取事件原子，构建图谱索引与搜索
5. **Indexing（Chunks -> 向量索引/混合索引）**
   - Milvus / FAISS / Chroma +（可选）BM25
6. **Retrieval + Chat**
   - 向量召回 + 重排 + 生成（流式对话）

## 2) 当前代码落位（重构后的“推荐入口”）

- Parsing：`app/parsing/*`
- Governance：`app/governance/*`（新增）
  - 预览接口：`POST /api/v1/pipeline/clean-preview`
- Chunking：`app/parsing/chunking/*`
  - RAGFlow 旧切块：`app/parsing/chunking/ragflow_legacy.py`
- KG：`app/rag/kg/*`
  - API：`/api/v1/kg/*`
- Chat/RAG：`app/rag/*`

## 3) 下一步建议（目录进一步统一）

- 将与“文档加工”无关的旧模块（如 `app/rag/chunkers_legacy`）逐步下沉到 `app/parsing/chunking/legacy/*` 并最终移除。
