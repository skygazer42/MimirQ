# Ragvia 后端目录结构

## 目录与职责

```text
app/
├── api/                  # HTTP 请求、响应和路由装配
│   ├── schemas/          # 按领域公开的 Pydantic 契约
│   ├── v1/               # 按业务领域组织的路由普通包
│   ├── dependencies.py   # 本地账号与工作区请求依赖
│   ├── middleware/       # 请求上下文、请求体、限流、响应头
│   └── utils/            # 文件/URL/表单输入及 HTTP 错误转换
├── infrastructure/       # 应用配置与共同基础设施
├── models/               # SQLAlchemy 数据库实体及显式注册
├── types/                # 内部共享数据和元数据契约
├── parsing/              # 文档解析、推理、增强和产物统计
│   ├── parsers/          # 文件格式解析及 PDF 布局算法
│   ├── models/           # OCR、版面、表格等推理实现
│   ├── enrich/           # 图片描述、表格组装及文档增强
│   ├── utils/            # 编码、标签、分词、安全解包
│   └── resources/        # 模型、词典、NLTK 与样例资源
├── query/                # 入库/查询一致的归一化、扩展与路由规则
├── rag/                  # 检索、模型调用和生成
│   ├── retrieval/        # 召回、融合、上下文、引用与缓存
│   ├── llm/              # 模型适配、提示词和响应解析
│   ├── safety/           # 输入/输出策略、声明验证、答案质量
│   ├── kg/               # 知识图谱抽取、索引与搜索
│   ├── tracing/          # trace 数据契约、指标及可选客户端
│   ├── chunking/         # 切块策略
│   ├── preprocessing/    # 解析后的文本治理和清理
│   ├── evaluation/       # 检索/生成评估算法
│   ├── engine.py         # RAG 引擎装配
│   └── engine_support/   # 引擎的检索与生成执行步骤
├── services/             # 按业务领域组织的操作与资源所有者
├── storage/              # 向量、BM25、对象存储客户端
├── connectors/           # 数据库连通性、目录读取与画像隐私
├── tasks/                # 后台队列、worker 与作业入口
└── main.py               # 应用启动与 HTTP 装配
```

`models` 的含义取决于所属领域：顶层是数据库映射，`parsing/models` 是推理实现。Pydantic 类是否属于 API schema，要看它是否描述 HTTP 契约；内部文档对象不能因为也继承 BaseModel 就混入数据库目录。

## API v1 领域包

`app/api/v1` 根目录只保留 `__init__.py`，其中 `get_router()` 负责按既有顺序装配领域路由。实际文件归入 11 个普通包：

```text
v1/
├── __init__.py       # 缓存的统一路由装配入口
├── identity/         # 账号、组、RBAC、SCIM
├── conversations/    # 聊天、历史、记忆、反馈、提示词
├── documents/        # 文档、上传、分段、预览、版本、入库运行
├── datasets/         # 数据集、预检、画像、表与报告
├── connectors/       # 来源目录、配置、验证、运行、调度
├── pipelines/        # 解析工作台、管线、治理与切块预设
├── evaluation/       # 评估、证据工作台与证据胶囊
├── integrations/     # Dify、外部会话及专属适配
├── retrieval/        # 检索与提示词预览、配置、解释、可视化
├── system/           # 健康、元信息、指标、设置、审计与用量
└── knowledge_graph/  # 知识图谱操作与网络分析
```

文档、连接器和会话的 `routes.py` 保留实际子路由聚合；叶模块按具体能力命名，例如 `documents/upload.py`、`datasets/precheck.py`、`connectors/schedules.py`。其余领域入口不增加聚合或转发。领域目录与 HTTP URL 前缀独立维护，本次归类保留所有原有路径、标签和注册顺序；系统设置仍读写仓库根的 `.env`。

## 数据库实体、HTTP schema 与内部类型

| 用途 | 位置 | 例子 |
| --- | --- | --- |
| 数据库表、列、关系 | `app/models` | `documents/records.py`、`connectors/runs.py`、`knowledge_graph/entities.py` |
| HTTP 请求、响应和约束 | `app/api/schemas` | `documents/document.py`、`datasets/dataset.py`、`knowledge_graph/graph.py` |
| 供响应读取 ORM 属性的 Pydantic 基类 | `app/api/schemas/base.py` | `OrmModel`、`OrmTimestampModel` |
| 内部 RAG 文档与转换协议 | `app/types/rag_document.py` | `Document`、`ChildDocument` |
| 内部文档管线选项 | `app/types/pipeline_options.py` | `PipelineOptions`、`PipelineEffective` |
| 共用元数据格式及规范化 | `app/types/document_metadata.py`、`indexing.py` | 文档结构、图片 ID、索引视图键 |
| 解析统计及其返回记录 | `app/parsing/artifact_stats.py` | `DocumentAnalytics`、`compute_document_analytics` |

API schema 的十个领域是 `identity`、`conversations`、`documents`、`datasets`、`sources`、`pipelines`、`evaluation`、`integrations`、`system`、`knowledge_graph`。域外使用公开包，域内直接依赖定义模块：

```python
from app.api.schemas.documents import DocumentDetail, UrlUploadRequest
from app.api.schemas.knowledge_graph import KGSnapshotDiffRequest
from app.models.documents.records import Document, DocumentChunk
```

应用、Alembic 和拥有数据库查询的命令/worker 在自己的启动边界导入 `app.models.registry`，完整注册表和字符串关系。模型包入口只保留说明，消费实体不需要经过第二套根导出清单。

`models` 根层只保留 `__init__.py`、`registry.py` 与跨领域的 `audit_log.py`。其余按实际领域组织：

```text
models/
├── identity/          # accounts、workspaces（租户/成员/成员组）
├── conversations/     # chat（会话/消息/摘要/反馈）
├── datasets/          # records、access、scans、catalog
├── documents/         # records、access、ingestion、indexing
├── connectors/        # configs、runs，生命周期分别维护
├── pipelines/         # profiles（切块预设与治理配置）
├── templates/         # versions（提示词/RAG配置版本与A/B记录）
├── evaluation/        # results、evidence
└── knowledge_graph/   # entities（实体、关系、事件与本体）
```

实际实体模块从27份合并为19份，53张表和类分别保留。文档与索引通道、会话与摘要等同一聚合集中维护；ACL、连接器配置/运行与目录画像等独立职责继续分开。领域包标记不注册或转发全部模型。

```python
from app.models.documents.records import Document, DocumentChunk
from app.models.documents.access import DocumentPermission
from app.models.datasets.access import DatasetPermissionEnum
```

`DatasetPermissionEnum` 的唯一定义在权限模块，数据集声明直接依赖该类型。完整字符串关系仍由进程入口的registry补齐；单独导入一个叶模块不表示全部mapper已可配置。新结构没有更改表、字段、索引或默认值，也不需要数据库迁移。

## Infrastructure 的边界

`infrastructure` 直接表达应用配置和共同基础设施，按用户要求替代原来的 `core` 包名。九个根模块和七个职责包保持，导入从 `app.infrastructure` 下的实际定义模块使用。

```text
infrastructure/
├── config.py、config_validation.py、env.py  # 稳定的配置入口与校验
├── exceptions.py、hashing.py、metadata_filters.py
├── model_policy.py、tokens.py
├── security/         # 角色、密码、令牌、密钥、PII、安全随机数
├── database/         # 连接、Session、ORM Base 与运行时迁移
├── http/             # 连接池、代理环境、OpenAI 协议地址
├── observability/    # 日志、指标、遥测、探针与构建信息
├── redis/            # 延迟客户端与所有者安全的租约
├── runtime/          # 同步/异步桥接、可选依赖、上下文与限流
└── regex/            # 规则验证和有界执行
```

普通包入口只说明职责，不聚合全部基础设施；调用方直接使用具体模块，例如 `app.infrastructure.database.connection` 和 `app.infrastructure.http.client`。这样导入角色或配置默认地址不会初始化数据库、HTTP 连接池或可选模型。

| 职责 | 模块 |
| --- | --- |
| 配置、环境和启动校验 | `config.py`、`config_validation.py`、`env.py` |
| 数据库连接与运行时迁移 | `database/connection.py`、`database/migrations.py` |
| 密码、令牌签发、未验证的第三方令牌诊断 | `security/passwords.py`、`security/jwt_tokens.py`、`security/jwt_inspect.py` |
| 角色、密钥、PII 与安全随机数 | `security/roles.py`、`security/secrets.py`、`security/pii.py`、`security/random.py` |
| HTTP 连接池、代理环境与协议地址 | `http/client.py`、`http/environment.py`、`http/openai.py` |
| 请求日志、指标和遥测 | `observability/logging.py`、`metrics.py`、`opentelemetry.py`、`sentry.py` |
| 健康探针与构建信息 | `observability/health.py`、`observability/build_info.py` |
| Redis 客户端与租约 | `redis/client.py`、`redis/leases.py` |
| 执行桥接、依赖加载、请求/流上下文及限流 | `runtime/async_bridge.py`、`dependencies.py`、`request_state.py`、`stream_events.py`、`rate_limit.py` |
| 共同数据操作 | `hashing.py`、`metadata_filters.py`、`tokens.py` |
| 正则规则验证与有界执行 | `regex/validation.py`、`regex/execution.py` |

业务代码直接使用标准库 `logging.getLogger`。日志配置和日志字段上下文由 `infrastructure/observability/logging.py` 持有；迁移前的日志分类作为稳定遥测标识保留。API 限流中间件与 `infrastructure/runtime/rate_limit.py` 的计数算法职责不同。JWT 签发和未验证诊断、有界正则执行和纯规则校验、Redis 客户端和租约操作也保留各自边界。

原 `constants.py` 不再集中无关协议：角色归 `security/roles.py`，Embedding 提供方归 `model_policy.py`，Milvus 索引参数归唯一使用它的 `storage/vector/milvus.py`，默认 OpenAI 地址归 `http/openai.py`，共用日志消息归日志模块。八组无生产调用的常量类退出；活跃的五个对象保持原定义和值。

## RAG 的边界

RAG 领域不再维护第二套 `core`，也不通过它转发通用日志、HTTP 环境或异常。

| 能力 | 所有者 |
| --- | --- |
| 有状态混合检索器 | `rag/retrieval/hybrid/retriever.py` |
| 检索模式与 profile 配置 | `rag/retrieval/profiles.py` |
| 上下文去噪、摘取、排序和预算 | `rag/retrieval/context_preparation.py` |
| 模型上下文压缩 | `rag/llm/context_compression.py` |
| 引用构造、证据摘取与缺口 | `rag/retrieval/citations.py`、`evidence_text.py`、`evidence_gap.py` |
| 声明校验与答案质量 | `rag/safety/claim_verification.py`、`answer_quality.py` |
| JSON/代码围栏解析、拒答和追问 | `rag/llm/response_parsing.py` |
| 提示词 bundle、历史格式化 | `rag/llm/prompts/templates.py` |
| trace 契约及 SLI 指标 | `rag/tracing/schemas.py`、`metrics.py` |

原文件解析/分块代码已吸收进上述 RAG 所有者：`rag/chunking/factory.py` 的 `chunk_file` 是唯一文件入口，四种格式策略位于 `strategies/naive.py`、`book.py`、`laws.py`、`email.py`；章节层级、文本/图片合并与切块记录分别由 `utils/section_structure.py`、`section_merging.py`、`chunk_records.py` 持有。四份文档记录构造和四份相同默认配置各只留一个维护点。

`integrated_naive`、`integrated_book`、`integrated_laws`、`integrated_email` 继续作为已有配置值；它们接收原始文件，与预解析文本的 `book_structured`、`laws_structured`、`email_thread` 等策略保持不同输入职责。原 bridge、包聚合、Token 转出、空文件工具和未用常量退出，不保留第二套集成包。

文件解析的可选视觉描述由 `rag/llm/vision_client.py` 持有实际同步客户端；它与 VisionReader 共用图片 MIME/data URL 构造，独立的异步传输/URL/响应策略保持。来源与维护位置分别记录：吸收的 InfiniFlow 算法保留 Apache 头与 NOTICE，进入项目 RAG 检查。

词典扩展与别名替换拥有不同匹配规则，在 `app/query/expand.py` 保留明确入口。`query/normalize.py` 返回带规则记录的归一化对象；`rag/preprocessing/normalization.py` 的 `normalize_query_text` 返回清理后的字符串，两者不互换。

知识图谱的数据库表属于 `models`，HTTP 请求与响应属于 `api/schemas/knowledge_graph`，路由属于 `api/v1/knowledge_graph`；`rag/kg` 保留实际抽取、索引和搜索。checkpoint 的恢复用途与 LangGraph store 的装配契约分别保留。

## 服务领域

领域入口是普通包，不统一导出所有函数。域名已经说明业务，叶模块使用具体职责，例如 `services.documents.ingestion` 和 `services.chat.stream_orchestrator`。

| 领域 | 职责 |
| --- | --- |
| `chat` | 会话准备、执行、流交付、记忆和持久化 |
| `documents` | 入库、读取范围、权限、生命周期、预览和版本 |
| `datasets` | 数据集管理、预检、画像和扫描结果 |
| `connectors` | 来源配置、运行、调度、对账与执行 |
| `tables` | 表存储、SQL 计划、表问答和字段安全 |
| `indexing` | 索引写入、重建与一致性审计 |
| `chunking` | 统计、质量评估与切块预设 |
| `parsing` | 远端解析适配、缓存和字段提取 |
| `pipelines` | 文档管线配置、治理、来源和入库规则 |
| `retrieval` | 检索请求、范围、默认值、模板与语义缓存 |
| `identity` | 账号、组、RBAC、配额和登录 |
| `evaluation` | 回归运行、用例、引用校验及在线评估 |
| `evidence` | 证据套件、覆盖率、漂移及修复 |
| `dify` | Dify 协议适配、策略、排序和记录整形 |
| `embeddings` | 向量空间迁移、漂移与集合相似度 |
| `prompts` | 用户提示词选择与默认值 |
| `reports` | 报告聚合与 HTML 渲染 |
| `retention` | 生命周期、保留策略和 RTBF |
| `observability` | 日志、指标、审计、诊断与运维报告 |
| `runtime` | 任务交接、并发预算、就绪缓存与模型预热 |
| `security` | 共用路径约束和输出脱敏 |

`connectors` 顶层目录持有底层数据库协议，`services/connectors` 持有业务运行和事务；`parsing` 顶层持有算法，`services/parsing` 持有远端部署和缓存适配。这些是不同资源边界。

清理文档的DOCX下载由 `services/documents/docx_export.py` 持有，API直接传入Markdown和文件名标题。格式生成、首H1去重由一个服务函数顺序完成；原 `parsing/output` 只服务该下载能力，其块转换、字节渲染和无消费包装已收敛。

## 验证与维护

命名和目录迁移同时更新定义、调用方、CLI、worker、动态工厂、CI 内嵌脚本和文档。普通 Python 的 Ruff/语法检查不能替代冷导入、OpenAPI、ORM 注册和资源路径核对。

本轮不新增、修改或运行 Python 测试；真实服务和模型运行与静态契约验证分别登记。当前文件结论见 [app 清单](maintenance/style-unification/app-review.csv)，命名迁移和审核层级见 [归属清单](maintenance/style-unification/layout-review.csv)，验证结果见 [验证记录](maintenance/style-unification/verification.md)。

详细规则见 [模块职责与调用约定](development/module_boundaries.md)。
