# MimirQ 技术架构

## 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户界面 (Next.js 14)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ 文档管理     │  │ 智能对话     │  │ 引用展示     │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ RESTful API / SSE
┌──────────────────────────▼──────────────────────────────────────┐
│                   FastAPI 后端服务                                │
│  ┌────────────────────────────────────────────────────────┐     │
│  │           LangChain RAG 编排引擎                       │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │     │
│  │  │ Chat Model   │  │ Hybrid       │  │ Runnable     │ │     │
│  │  │ (OpenAI/...) │  │ Retriever    │  │ (Prompt)     │ │     │
│  │  └──────────────┘  └──────────────┘  └──────────────┘ │     │
│  └────────────────────────────────────────────────────────┘     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ 文档解析     │  │ 混合检索     │  │ Embedding    │           │
│  │ (PyMuPDF)    │  │ (Vector+BM25)│  │ (BGE/OpenAI) │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  PostgreSQL  │  │    Milvus    │  │  BM25 Index  │
│ (对话/文档)   │  │ (向量检索)    │  │ (关键词检索)  │
└──────────────┘  └──────────────┘  └──────────────┘
                   │
            ┌──────┴──────┐
            ▼             ▼
       ┌────────┐    ┌────────┐
       │  Etcd  │    │ MinIO  │
       │(元数据) │    │(对象)   │
       └────────┘    └────────┘
```

## 技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| **前端** | Next.js 14 (App Router) + TypeScript | 现代化 React 框架 |
| **UI 组件** | Tailwind CSS + Shadcn/ui | 极简设计系统 |
| **后端** | FastAPI 0.109 + Python 3.11 | 高性能异步框架 |
| **AI 编排** | LangChain 1.x (Runnable + Retriever) | 纯 LangChain RAG 链路 |
| **向量数据库** | Milvus 2.3 + Etcd + MinIO | 十亿级向量检索 |
| **关系数据库** | PostgreSQL 15 | 文档/对话持久化 |
| **Embedding** | BGE-large-zh-v1.5 (本地) | 中文向量模型 |
| **LLM** | OpenAI 兼容接口 | GPT-4 / 自部署模型 |
| **检索策略** | Hybrid Search (Vector + BM25) | 混合检索算法 |
| **分词器** | Jieba | 中文分词支持 |
| **任务队列** | Arq + Redis | 异步文档处理 |
| **对象存储** | MinIO | S3 兼容存储 |

## 项目结构

```bash
MimirQ/
├── app/                 # FastAPI 后端服务（核心代码）
│   ├── api/             # API 路由
│   │   ├── v1/          # v1 版本 API
│   │   ├── schemas/     # Pydantic 请求/响应模型
│   │   ├── dependencies/# 认证、租户、错误处理
│   │   └── middleware/  # 请求ID、速率限制
│   ├── core/            # 核心配置与数据库
│   ├── models/          # 数据模型 (Pydantic/SQLModel)
│   ├── services/        # 业务逻辑
│   ├── parsing/         # 文档解析模块
│   │   ├── parsers/     # 解析器实现
│   │   ├── processors/  # 文本处理器
│   │   └── chunking/    # 分块策略
│   ├── rag/             # RAG 编排引擎
│   │   ├── engine.py    # 对话引擎
│   │   ├── retriever.py # 混合检索器
│   │   ├── embedding/   # 向量嵌入
│   │   ├── reranker/    # 重排序
│   │   ├── kg/          # 知识图谱
│   │   └── evaluation/  # RAGAS 评测
│   ├── storage/         # 存储层
│   │   ├── vector/      # Milvus
│   │   └── object/      # MinIO
│   ├── tasks/           # 后台任务队列
│   └── deepdoc/         # 深度文档解析模块
├── docker/              # Docker 部署文件
│   ├── .env.example
│   ├── docker-compose.yml
│   ├── docker-compose.infra.yml
│   ├── Dockerfile
│   └── start_backend.sh
├── config/              # 项目级配置清单（如解析小模型 manifest）
├── web/                 # Next.js 前端界面
│   ├── app/             # 页面路由
│   ├── components/      # UI 组件
│   ├── lib/             # 工具函数与 API 客户端
│   ├── store/           # Zustand 状态管理
│   └── public/          # 静态资源
├── docs/                # 项目文档
├── tests/               # 测试
├── scripts/             # 工具脚本
├── Makefile             # 常用命令
└── requirements.txt     # 后端依赖
```

## 环境变量配置

根目录 `.env.example` 是完整环境变量模板；本地启动可复制为 `.env`，部署时按需覆盖其中的数据库、模型、解析、RAG、KG 与可观测性配置。

### LLM 配置

```bash
LLM_API_KEY=sk-your-api-key
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo-preview
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=60
LLM_MAX_RETRIES=3
```

### Embedding 配置

```bash
EMBEDDING_PROVIDER=local  # local | openai_compatible
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DEVICE=cuda  # cpu | cuda
EMBEDDING_API_KEY=  # 留空则使用 LLM_API_KEY
EMBEDDING_API_BASE=  # 留空则使用 LLM_API_BASE
```

### 数据库配置

```bash
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/mimirq
```

### Milvus 配置

```bash
MILVUS_HOST=milvus
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=knowledge_base
```

### RAG 参数

```bash
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
RETRIEVAL_TOP_K=5
SIMILARITY_THRESHOLD=0.7
```

### 索引开关

```bash
CHUNK_VECTOR_ENABLED=true
BM25_INDEX_ENABLED=true
EVENT_VECTOR_ENABLED=true
ENTITY_VECTOR_ENABLED=true
```

### 解析/切块能力开关

| 变量 | 说明 | 默认 |
|------|------|------|
| `DEFAULT_PARSER_BACKEND` | 控制未指定时使用的解析器 | `auto` |
| `DEEPDOC_ENABLED` | 启用 DeepDoc 解析 | `false` |
| `MARKITDOWN_ENABLED` | 开启微软 MarkItDown 解析 | `false` |
| `MINERU_ENABLED` | 开启 MinerU 在线解析 | `false` |
| `GOVERNANCE_ENABLED` | 启用治理清洗流程 | `false` |
| `DEFAULT_CHUNK_STRATEGY` | 默认切块策略 | `langchain_recursive` |
| `LLAMA_INDEX_ENABLED` | 允许调用 LlamaIndex | `false` |

### 应用配置

```bash
UPLOAD_DIR=/app/uploads
MAX_FILE_SIZE=10485760  # 10MB
ALLOWED_EXTENSIONS=.pdf,.txt,.md,.rst,.adoc,.asciidoc,.tex,.yaml,.yml,.toml,.sql,.log,.conf,.ini,.cfg,.env,.properties,.patch,.diff,.srt,.vtt,.mk,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.html,.htm,.json,.jsonl,.ndjson,.xml,.rss,.atom,.graphql,.gql,.proto,.tf,.hcl
```

## 性能基准

| 指标 | 数值 | 说明 |
|------|------|------|
| **文档处理速度** | ~100 页/分钟 | PDF 解析 + 分块 + Embedding |
| **检索延迟** | <100ms | Milvus 向量检索 (IVF_FLAT) |
| **LLM 首字延迟** | ~500ms | 包含检索 + LLM 初始化 |
| **流式输出速度** | ~50 tokens/s | GPT-4 Turbo 平均速度 |
| **并发支持** | 100+ QPS | 单机 FastAPI + Milvus |
| **向量容量** | 10 亿+ | Milvus 集群模式 |

**测试环境**: 4 vCPU / 16 GB RAM / SSD

## 数据流

### 文档上传流程

```
用户上传文件 → API 接收 → 解析文档 → 分块处理 → 生成 Embedding
→ 存入 Milvus → 构建 BM25 索引 → 更新数据库 → 完成
```

### 对话流程

```
用户提问 → API 接收 → 混合检索（向量+BM25） → 获取相关文档
→ RAG 引擎编排 → LLM 流式生成 → SSE 返回 → 保存对话记录
```

## 相关文档

- [快速入门](./quickstart.md)
- [Docker Compose 部署](./deployment/docker_compose.md)
- [Milvus 向量数据库指南](./guides/milvus_guide.md)
- [RAG 优化指南](./guides/rag_optimization.md)
- [LangChain RAG 架构](./guides/langchain_agent_migration.md)
