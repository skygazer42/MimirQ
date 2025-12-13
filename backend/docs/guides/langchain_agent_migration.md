# LangChain RAG 架构与迁移说明

## 概述

当前后端已收口为 **纯 LangChain 1.x** 的 RAG 实现：

- 检索：`HybridRetriever` 继承 `BaseRetriever`，统一对外 `invoke/ainvoke`。
- 向量库：`milvus_store` 内部用 LangChain `Milvus` vectorstore 管理 collection / 索引 / 相似度检索。
- 关键词：LangChain `BM25Retriever` 管理 BM25 索引。
- 生成：`RAGEngine` 以 Runnable 方式编排 `Prompt → LLM → OutputParser`，支持流式输出。

本文件记录从历史 LangGraph/Agent 方案迁移到纯 LangChain 的原因、结构与使用方式。

## 迁移原因

历史版本采用 LangGraph Agent + Tool Calling + Checkpoint：

- 依赖链长、版本耦合强（LangChain/LangGraph/API 变动频繁）。
- 代理环境/依赖缺失时容易在 import 阶段崩溃。
- 对本项目的“知识库问答”场景而言，Agent 能力并非必须。

因此收口为：

- **Retriever 统一管理检索**（易测、易扩展）。
- **Runnable 链式管理生成**（标准 LangChain 1.x 用法）。
- 对话持久化交给业务层 PostgreSQL（`Conversation/Message` 表）。

## 当前架构

```
用户请求
  ↓
FastAPI (/api/v1/chat/stream)
  ↓
HybridRetriever (LangChain BaseRetriever)
  ├─ 向量检索：Milvus vectorstore
  └─ 关键词检索：BM25Retriever
  ↓
RAGEngine Runnable chain
  (ChatPromptTemplate | ChatOpenAI | StrOutputParser)
  ↓
SSE 流式返回 token / citations / done
  ↓
PostgreSQL 持久化 Message / Conversation
```

### 关键模块

- `backend/app/services/milvus_store.py`
  - LangChain Milvus vectorstore 管理。
  - 对外保留 `add_documents/search/delete_by_document_id/get_collection_count`。
- `backend/app/services/hybrid_retriever.py`
  - 继承 `BaseRetriever`，对外 `invoke/ainvoke`。
  - BM25 索引按租户缓存，`build_bm25_index()` 在启动和上传后重建。
- `backend/app/services/rag_engine.py`
  - Runnable chain + 流式生成。
  - `stream_chat()` 负责 citations/context/history 拼接与事件输出。
- `backend/app/api/v1/chat.py`
  - 调用 `get_rag_engine().stream_chat(...)`，SSE 输出。

## 依赖（LangChain 1.x）

`backend/requirements.txt` 中保留：

```txt
langchain==1.1.0
langchain-core==1.1.0
langchain-community==0.4.1
langchain-openai==1.1.0
langchain-text-splitters==0.3.0
pymilvus==2.3.5
rank-bm25==0.2.2
jieba==0.42.1
```

> LangGraph 相关依赖已移除。

## 使用示例

### 1. 构建 BM25 索引（启动/上传自动做）

```python
from app.services.hybrid_retriever import hybrid_retriever
hybrid_retriever.build_bm25_index(chunks, tenant_id=tid)
```

### 2. 检索（标准 LangChain Retriever）

```python
from app.services.hybrid_retriever import hybrid_retriever

retriever = hybrid_retriever.model_copy(update={
    "k": 5,
    "tenant_id": tid,
    "document_ids": doc_ids,
    "alpha": 0.6,
})
docs = retriever.invoke("问题")
```

返回的 `docs` 为 LangChain `Document`：

- `page_content`: chunk 内容
- `metadata`: `{source, page, document_id, score, vector_score, bm25_score, ...}`

### 3. 生成（RAGEngine）

```python
from app.services.rag_engine import get_rag_engine

engine = get_rag_engine()
async for event in engine.stream_chat(
    question="问题",
    tenant_id=tid,
    document_ids=doc_ids,
):
    ...
```

事件类型保持：

- `citations`: 引用列表
- `token`: 流式 token
- `done`: 完成信号
- `error`: 错误

## 后续扩展点

- 将 `_merge_results/_weight_rerank` 抽成可配置策略（如 RRF、MMR）。
- BM25 支持增量更新（避免全量重建）。
- 切换到官方 `langchain-milvus` 包以替代社区 Milvus（不影响外部接口）。

