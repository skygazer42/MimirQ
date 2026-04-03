---
sidebar_label: "RAG 数据流"
sidebar_position: 1
---

# RAG 端到端数据流

从文档入库到对话检索与生成的完整数据流，帮助理解 MimirQ 各组件如何协作。

## 全流程总览

```mermaid
flowchart LR
    subgraph 入库阶段
        A[文档上传] --> B[解析]
        B --> C[切块]
        C --> D[Embedding]
        D --> E[向量索引]
        C --> F[BM25 索引]
    end

    subgraph 可选增强
        C --> G[KG 抽取]
        G --> H[图谱存储]
    end

    subgraph 检索阶段
        I[用户提问] --> J[Query 改写]
        J --> K[混合检索]
        K --> L[向量检索]
        K --> M[BM25 检索]
        K --> N[KG 检索]
        L --> O[结果合并]
        M --> O
        N --> O
        O --> P[重排序]
    end

    subgraph 生成阶段
        P --> Q[Prompt 组装]
        Q --> R[LLM 生成]
        R --> S[流式输出 + 引用]
    end
```

## 入库阶段详解

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Store as 对象存储
    participant Parser as 解析服务
    participant Pipeline as Pipeline Worker
    participant VecDB as Milvus
    participant DB as PostgreSQL

    Client->>API: POST /documents/upload
    API->>Store: 存储原始文件
    API->>DB: 创建文档记录 (pending)
    API-->>Client: document_id

    Parser->>Store: 读取文件
    Parser->>Parser: 解析为结构化文本
    Parser->>DB: 更新状态 (parsing)

    Pipeline->>DB: 读取解析结果
    Pipeline->>Pipeline: 切块 + 清洗
    Pipeline->>Pipeline: Embedding (BAAI/bge-m3 等)
    Pipeline->>VecDB: 写入向量索引
    Pipeline->>DB: 写入切块记录 + 更新状态 (completed)
```

### 各阶段说明

| 阶段 | 组件 | 输入 | 输出 |
|------|------|------|------|
| 上传 | API Server | 原始文件 | document_id + 对象存储路径 |
| 解析 | Parser Service | 原始文件 | 结构化文本 + 元数据 |
| 切块 | Pipeline Worker | 结构化文本 | 文本片段列表 |
| Embedding | Pipeline Worker | 文本片段 | 向量表示 |
| 索引 | Milvus + PostgreSQL | 向量 + 文本 | 可检索的索引 |

## 检索阶段详解

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Retriever as HybridRetriever
    participant Vec as 向量检索
    participant BM25 as BM25 检索
    participant KG as KG 检索
    participant Reranker as 重排序

    Client->>API: POST /chat/completions
    API->>Retriever: 查询分发

    par 并行检索
        Retriever->>Vec: 向量相似度搜索
        Vec-->>Retriever: top-K 结果
    and
        Retriever->>BM25: 关键词匹配
        BM25-->>Retriever: top-K 结果
    and
        Retriever->>KG: 图谱扩展
        KG-->>Retriever: 关联实体/片段
    end

    Retriever->>Retriever: 结果合并 + 去重
    Retriever->>Reranker: 候选片段
    Reranker-->>Retriever: 重排序后的片段
    Retriever-->>API: 最终检索结果
```

### 混合检索策略

MimirQ 采用 HybridRetriever，支持多路召回：

| 检索路 | 方法 | 擅长场景 |
|--------|------|----------|
| 向量检索 | 语义相似度（ANN） | 语义匹配、同义表达 |
| BM25 | 关键词匹配 | 精确术语、专有名词 |
| SPLADE | 稀疏向量 | 兼顾语义与关键词 |
| KG | 图谱关系扩展 | 实体关联、多跳推理 |

## 生成阶段详解

```mermaid
sequenceDiagram
    participant API
    participant LLM
    participant Client

    API->>API: 组装 Prompt (系统指令 + 检索片段 + 用户问题)
    API->>LLM: 发送 Prompt

    loop SSE 流式输出
        LLM-->>API: token chunk
        API-->>Client: data: {"content": "..."}\n\n
    end

    API-->>Client: data: [DONE] (含 citations)
```

## 关键配置参数

| 参数 | 影响阶段 | 说明 |
|------|----------|------|
| `chunk_size` | 切块 | 片段大小，影响检索粒度 |
| `embedding_model` | Embedding | 向量模型选择 |
| `top_k` | 检索 | 各路召回数量 |
| `rerank_model` | 重排序 | 重排模型选择 |
| `temperature` | 生成 | LLM 生成随机性 |

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [场景: 上传后对话](../scenarios/s01-upload-chat.md) | [场景: 检索调试](../scenarios/s04-retrieval-debug.md)
- [认证流程](./auth-flow.md)
