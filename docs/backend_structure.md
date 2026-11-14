# Ragvia Backend 目录结构

## 概览

```
app/
├── api/              # API 路由层
├── core/             # 核心配置
├── connectors/       # 数据库连通性、目录与行快照、持久化及画像隐私
├── models/           # 数据库模型
├── api/schemas/      # API 请求/响应 Schema
├── api/dependencies.py # FastAPI 请求依赖
├── api/middleware/    # 请求上下文、响应头、限流与请求体限制
├── api/utils/         # HTTP 输入、响应头、文件与 URL 边界
├── parsing/          # 文档解析模块
├── governance/       # 数据治理（Markdown 清洗/规则）
├── storage/          # 存储模块
├── rag/              # RAG 引擎模块
│   └── kg/           # 知识图谱模块（事件/实体/关系）
├── evaluation/       # 评估模块
├── services/         # 业务服务
└── main.py           # 应用入口
```

## API 工具

`app/api/` 与 `app/api/utils/` 使用普通包。utils 保留五个实际职责模块，包入口显式发布公共文件与响应工具，URL 与管线输入通过具名子模块使用；普通文件工具导入不会加载应用配置或管线服务。

```python
from app.api.utils import file_response_headers, save_upload_file
from app.api.utils.document_pipeline_input import to_pipeline_options
from app.api.utils.url_ingest import download_url_to_path
```

| 模块 | 职责 |
| --- | --- |
| document_pipeline_input.py | 管线 JSON、覆盖参数与 HTTP 输入错误转换 |
| file_io.py | 上传保存、文件名／来源路径、哈希与未完成文件清理 |
| url_ingest.py | URL／DNS 校验、Host／SNI 固定、重定向及有界下载 |
| response_headers.py | 安全文件响应头与 Content-Disposition |
| http_exception_responses.py | 被多个路由共用的错误响应说明 |

## 数据库连接器

`app/connectors/` 保留四个职责模块，直接从定义模块导入；沿用项目已有的命名空间包方式，不设置注册副作用或聚合入口。

```text
connectors/
├── connectivity.py    # 异步连接探针与权限警告，驱动按需加载
├── catalog.py         # 目录 SQL、表列读取、同步与有界行快照
├── store.py           # 持有 Session 的 SQLAlchemy 存储，不提交事务
└── profile_privacy.py # 存储和读取共用的画像隐私过滤
```

## 模块说明

### 1. api/ - API 路由层

FastAPI 路由定义，处理 HTTP 请求。

```python
from app.api.v1 import get_router

app.include_router(get_router(), prefix="/api/v1")
```

**文件：**
- `v1/chat.py` - 对话接口
- `v1/documents.py` - 文档管理
- `v1/datasets.py` - 数据集管理
- `v1/pipeline.py` - 解析流水线
- `v1/evaluations.py` - 评估接口
- `v1/__init__.py` - 路由聚合（包含 `/kg/*`）

### 2. core/ - 核心配置

应用核心配置和基础设施。

```python
from app.core.config import settings
from app.core.database import get_db
```

**文件：**
- `config.py` - 配置管理（Settings）
- `database.py` - 数据库连接
- `migrations.py` - 运行时迁移

### 3. models/ - 数据库模型

SQLAlchemy ORM 模型定义。

```python
from app.models.document import Document, DocumentChunk
```

**文件：**
- `document.py` - 文档模型
- `chat.py` - 对话模型
- `dataset.py` - 数据集模型
- `evaluation.py` - 评估模型

### 4. api/schemas/ - API Schema

API 请求/响应的数据验证模型。

Schema 按业务领域组织为普通包，每个领域通过 __init__.py 显式导出已承诺的模型、类型和常量，并用 __all__ 标记公开范围。域外消费者依赖领域入口，域内继续依赖定义模块；共享 ORM 基类由 base.py 持有，schemas 根入口不聚合全部领域。

```text
schemas/
├── __init__.py          # 领域包容器，不全量导出业务模型
├── base.py              # 共享 ORM 响应基类
├── identity/            # 账号、成员权限、组和字段访问策略
├── conversations/       # 聊天、检索、反馈及提示词/RAG 模板
├── documents/           # 文档、入库、目录、健康状态、问答和时间线
├── datasets/            # 数据集、分类、统计、预检、数据库目录和表格
├── sources/             # 连接器、来源 ACL、入库策略和运行清单
├── pipelines/           # 解析预览、治理规则、行业规则和切块预设
├── evaluation/          # 会话评估、回归、证据、引用治理、诊断和报告
├── integrations/        # Dify 与外部会话协议
└── system/              # 审计、设置、健康检查和元信息
```

九个领域的包入口只发布当前有域外使用方的 418 个名称，实际类和校验器仍定义在原模块中，没有转发函数或动态查找。数据集健康模型与统计摘要同归 datasets/profile.py，证据漂移和修复同归 evaluation/references.py。

```python
from app.api.schemas.documents import DocumentDetail, UrlUploadRequest
from app.api.schemas.identity import LoginRequest
```

普通领域入口会加载该领域公开契约所需的模型依赖；conversations 与 evaluation 可经 datasets 初始化已有 ORM 注册和 SQLAlchemy engine，构造时不建立连接。文件与响应公共工具保持配置隔离，包导入不启动路由、任务或网络请求。

### 5. api/dependencies.py - FastAPI 依赖

依赖注入函数（鉴权、租户等）。

```python
from app.api.dependencies import get_current_account_id, get_tenant_id
```

请求依赖集中在 `app.api.dependencies`；原依赖目录及其 `auth.py`、`tenant.py` 和 `logging.py` 已删除。HTTP 中间件按实际协议组织：

- `middleware/request_context.py` - 请求 ID、日志上下文和耗时
- `middleware/response_headers.py` - 安全响应头和服务指纹清理
- `middleware/body_size_limit.py` - 请求体大小限制
- `middleware/rate_limit.py` - API 与聊天限流

### 6. parsing/ - 文档解析模块 📦

负责文档解析、质量评估、文本切块（原始 Markdown 生产）。

### 6.5 governance/ - 数据治理 📦

负责将 Markdown 做“清洗/规范化”（正则规则、空白规范化等），为人工调整与后续分块做准备。

**开关：** `GOVERNANCE_ENABLED` 控制治理流程是否启用（默认 false）。

**预览 API：**
- `POST /api/v1/pipeline/clean-preview`
- `GET  /api/v1/pipeline/clean-rules`
- `POST /api/v1/pipeline/llm-clean-preview`（大模型清洗：支持 `prompt_template_id/template_key/ab_experiment_key` 选择 PromptTemplate）

**关键词 API：**
- `POST /api/v1/pipeline/extract-keywords`（`provider=auto/jieba/jieba_tfidf/jieba_textrank/hanlp/simple`；HanLP 可用 `HANLP_TOKENIZER_MODEL` 指定 tokenizer 模型）
  - 停用词：`app/rag/preprocessing/stopwords.py`

#### 使用示例

```python
# 质量评估
from app.parsing.quality.scorer import score_pdf_quality
quality = score_pdf_quality(pdf_path, sample_pages=3, use_ocr_validation=True)

# 解析文档
from app.parsing.factory import parser_factory
documents, backend = parser_factory.parse(file_path, parser_backend="auto")

# 文本切块
from app.parsing.chunking.factory import chunker_factory
chunker = chunker_factory.get_chunker("langchain_recursive")
chunks = chunker.split_documents(documents)

# 分层切块
from app.parsing.chunking.hierarchical import hierarchical_chunk_markdown
result = hierarchical_chunk_markdown(markdown_text)

# 完整流程
from app.parsing.processors.support.process_document_flow import process_document
await process_document(file_path, doc_id, tenant_id)
```

**可选 pipeline 参数（每文档覆盖默认配置）：**
- `governance_enabled` / `chunk_size` / `chunk_overlap`
- `chunk_vector_enabled` / `bm25_index_enabled`
- `kg_enabled` / `event_vector_enabled` / `entity_vector_enabled`

**子模块：**
- `quality/` - PDF 质量评估、OCR 验证
- `parsers/` - 各类解析器实现
- `chunking/` - 切块策略
- `processors/` - 处理流程编排
- `utils/` - 工具函数（ZIP 处理等）

### 7. storage/ - 存储模块 📦

负责向量存储、对象存储、混合检索。

#### 使用示例

```python
# 向量存储
from app.storage.vector.factory import get_vector_store
vector_store = get_vector_store()
vector_ids = vector_store.add_documents(docs, doc_id, tenant_id)

# 对象存储（MinIO）
from app.storage.object.minio import minio_service
img_id = minio_service.upload_image(image_data, tenant_id, dataset_id, document_id, chunk_key)
url = minio_service.get_image_url(img_id)

# 混合检索
from app.storage.search.hybrid_retriever import hybrid_retriever
docs = hybrid_retriever.retrieve(query, doc_ids, tenant_id, top_k=5)
```

**子模块：**
- `vector/` - 向量数据库（Milvus、Qdrant、pgvector）与进程内 memory 测试索引
- `object/` - 对象存储（MinIO）
- `search/` - 混合检索（BM25 + 向量）

### 8. rag/ - RAG 引擎模块 📦

负责检索增强生成核心逻辑。

#### 使用示例

```python
# RAG 引擎
from app.rag.engine import get_rag_engine
rag_engine = get_rag_engine()
async for event in rag_engine.stream_chat(query, document_ids=document_ids, tenant_id=tenant_id):
    print(event)

# LangGraph 编排
from app.rag.pipelines.langgraph import run_rag_graph
result = run_rag_graph(question, history, document_ids, tenant_id=tenant_id)

# Agentic RAG
from app.rag.agents.rag_agent import get_agentic_runner
runner = get_agentic_runner(engine=rag_engine)
async for event in runner.stream(question=query, document_ids=document_ids, tenant_id=tenant_id):
    print(event)
```

**子模块：**
- `engine.py` - 核心 RAG 引擎
- `pipelines/langgraph.py` - LangGraph 编排
- `agents/rag_agent.py` - Agentic RAG 执行
- `tools/` - RAG 工具函数
- `reranker/` - 重排序策略

### 9. evaluation/ - 评估模块 📦

负责 RAG 系统评估。

#### 使用示例

```python
from app.rag.evaluation.ragas import evaluate_rag_with_ragas

result = await evaluate_rag_with_ragas(
    questions=questions,
    answers=answers,
    contexts=contexts,
    ground_truths=ground_truths
)
```

### 10. services/ - 业务服务

高层业务逻辑服务。

```python
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids
from app.services.prompt_resolver import resolve_prompt_template
```

**保留的服务：**
- `dataset_service.py` - 数据集管理
- `document_access.py` - 文档权限
- `prompt_resolver.py` - 提示词解析/选择
- `metrics_logger.py` - 指标日志
- `mineru_service.py` - MinerU API 客户端
- `indexer.py` - 统一索引器（chunk/event 入库、重建、删除）
- `pipeline_config.py` - 文档级 pipeline 配置解析/合并

### 11. rag/kg/ - 知识图谱模块

知识图谱（KG）功能：从文档 chunks 抽取事件/实体，并提供图谱检索能力。

## 依赖关系

```
┌─────────────────────────────────────────────┐
│           api/ (FastAPI 路由)               │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│        services/ (业务服务层)               │
└─────────────────┬───────────────────────────┘
                  │
        ┌─────────┼─────────┬─────────┐
        │         │         │         │
┌───────▼───┐ ┌──▼────┐ ┌──▼────┐ ┌─▼──────┐
│ parsing/  │ │storage│ │  rag/ │ │evaluat │
│   解析    │ │ 存储  │ │  引擎 │ │  评估  │
└───────┬───┘ └──┬────┘ └──┬────┘ └─┬──────┘
        │        │         │         │
        └────────┴─────────┴─────────┘
                  │
┌─────────────────▼───────────────────────────┐
│   models/ + api/schemas/ (数据层)           │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│           core/ (核心配置)                  │
└─────────────────────────────────────────────┘
```

## 导入路径对照表

| 旧路径 | 新路径 |
|--------|--------|
| `app.services.pdf_quality` | `app.parsing.quality.scorer` |
| `app.services.rapid_ocr_service` | `app.parsing.quality.ocr_validator` |
| `app.services.parsers` | `app.parsing.factory` |
| `app.services.chunkers` | `app.parsing.chunking.factory` |
| `app.services.hierarchical_chunking` | `app.parsing.chunking.hierarchical` |
| `app.services.document_processor` | `app.parsing.processors.support.process_document_flow`（入口）；`app.parsing.processors.processor`（持久化与图像助手） |
| `app.services.document_parser_service` | `app.parsing.processors.parser_service` |
| `app.services.zip_image_processor` | `app.parsing.utils.zip_processor` |
| `app.services.vector_router` | `app.storage.vector.factory` |
| `app.services.milvus_store` | `app.storage.vector.milvus` |
| `app.services.minio_service` | `app.storage.object.minio` |
| `app.services.hybrid_retriever` | `app.storage.search.hybrid_retriever` |
| `app.services.rag_engine` | `app.rag.engine` |
| `app.services.rag_graph` | `app.rag.pipelines.langgraph` |
| `app.services.rag_agent` | `app.rag.agents.rag_agent` |
| `app.services.rag_tools` | `app.rag.tools` |
| `app.services.llm_reranker` | `app.rag.reranking.llm_reranker` |
| `app.services.ragas_evaluator` | `app.rag.evaluation.ragas` |

## 设计原则

### 1. 单一职责

每个模块只负责一类功能：
- `parsing/` 只管解析
- `storage/` 只管存储
- `rag/` 只管检索生成和评估

### 2. 低耦合

模块间通过清晰的接口交互，避免循环依赖。

### 3. 高内聚

相关功能集中在同一模块内，便于维护。

### 4. 易扩展

新功能有明确的归属位置。

## 开发指南

### 添加新解析器

在 `parsing/parsers/` 下创建新文件，然后在 `parsing/factory.py` 中注册。

### 添加新切块策略

在 `parsing/chunking/` 下实现，然后在 `factory.py` 中注册。

### 添加新向量数据库

在 `storage/vector/` 下实现，遵循 `router.py` 的接口。

### 添加新 RAG 策略

在 `rag/` 下扩展 `engine.py` 或添加新的编排文件。

### 添加新 API 路由

在 `api/v1/` 下创建路由文件，然后在 `api/v1/__init__.py` 中 `include_router(...)` 注册。

**认证约定（务必遵守）**：后端没有全局强制认证中间件——认证由**每个路由显式声明依赖**实现。新增任何路由都必须带认证依赖：

- 函数级：访问租户数据时同时声明 `tenant_id: Annotated[UUID, Depends(get_tenant_id)]` 和 `account_id: Annotated[str, Depends(get_current_account_id)]`；只需确认身份、不涉及租户数据时声明 `Depends(get_current_account_id)`；
- 路由级：`APIRouter(dependencies=[Depends(get_current_account_id)])`（整组路由统一鉴权，适合一组无租户数据但仍需认证的端点）。

即使是**纯计算、不访问数据库**的端点（如图算法工具）也必须认证，否则会成为未认证的计算/DoS 面；同时对客户端提供的列表/数组输入用 `Field(..., max_length=...)` 设上限，避免无界输入导致 CPU/内存耗尽。参考 `api/v1/network_analysis.py`（用路由级 `Depends(get_current_account_id)` + `edges` 上限）。

## 测试

按模块运行测试：

```bash
pytest tests/parsing/
pytest tests/storage/
pytest tests/rag/
pytest tests/evaluation/
```

## 迁移完成 ✅

所有文件已按功能域重新组织，导入路径已更新，结构更清晰！
