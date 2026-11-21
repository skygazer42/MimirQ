# RAG 目录与执行入口

`app/rag` 按实际职责导航。运行入口只负责组装步骤；算法、配置、状态和资源由各自模块持有，调用方直接导入定义。

## 从哪里开始读

| 要处理的事情 | 入口 |
| --- | --- |
| 流式检索对话 | `app/rag/runtime/engine.py` → `runtime/streaming/executor.py` |
| LangGraph 对话 | `runtime/graph/state.py` 构造 state；`workflow.py` 装配图；`tasks.py` 执行任务 |
| 单独检索证据 | `retrieval/orchestrator.py` → `retrieval/stages/` |
| 多通道召回 | `retrieval/recall/retriever.py` → vector／Milvus BM25／PostgreSQL lexical |
| 融合与排序 | `retrieval/ranking/channels.py`、`queries.py`、`diversity.py` |
| 模型重排 | `retrieval/reranking/factory.py`；证据重排阶段为 `retrieval/stages/post_rerank.py` |
| 原始文件解析并分块 | `ingestion/parsing/files/` → `ingestion/chunking/factory.py:chunk_file` |
| 已解析 Document 分块 | `ingestion/chunking/factory.py` → `ingestion/chunking/registry.py` → 对应策略 |
| 解析后内容治理 | `ingestion/governance/processor.py`，输入与统计契约在 `ingestion/governance/contracts.py` |
| 完整入库流程 | `ingestion/pipeline.py` → `ingestion/indexing/` |
| 智能体调用 | `agents/rag_agent.py`、`agents/multi_agent.py` |

## 运行时与检索

```text
runtime/
  engine.py                 会话引擎与模型资源
  contracts.py              请求上下文、提示词选择和响应选项
  context.py                检索文档去噪、压缩、生成顺序与 token 预算
  model_routing.py          引擎模型路由
  query_models.py           查询展开的模型适配
  streaming/                setup/query/retrieval/evidence/generation/finalization
  graph/                    state/context/generation/answers/metrics/tasks/workflow
  checkpoints/              恢复检查点与 SQLite 连接生命周期
  store.py                  LangGraph store 的既有配置和装配

retrieval/
  orchestrator.py           顺序执行检索阶段
  planning/                 请求归一化、查询路由与展开、数据集计划
  corpus.py                 Milvus BM25 生命周期、回填及 corpus 版本
  recall/                   向量、Milvus BM25 和 PostgreSQL 词法召回
  ranking/                  通道/查询融合、插件评分、去重、多样性与元数据排序
  reranking/                重排模型适配、轻量算法、provider 注册与工厂
  expansion/                父子、邻居、兄弟及上下文扩展
  evidence/                 引用、证据包、质量、缺口、来源标签、结构和证据指标
  configuration/            检索选项、profile、契约、预算与配置指纹
  cache/                    候选和重排缓存
  stages/                   查询执行、融合、补召回、诊断和结果组装
  results.py                检索结果的共同字段与诊断值
```

`orchestrator.py` 原先的 3,854 行实现按上述实际阶段拆开，入口为 88 行。LangGraph 原先 1,852 行的模块拆为七个职责模块：持久 state 与运行 context、上下文准备、生成、答案处理、指标、任务及图装配。checkpoint 和 store 保留各自生命周期，不为目录一致合并资源。

Document 身份统一由 `results.py:document_key` 提供；RRF 及择优规则使用 `ranking/fusion.py`，通道融合归 `ranking/channels.py`，查询融合归 `ranking/queries.py`。阶段调用同一查询融合实现，避免再维护一份层级/多查询配额算法。候选 metadata views 和 Document 根字段的范围分别保留，共用 `ranking/metadata.py` 的筛选和匹配规则。

插件策略的纯规则、候选预算和压缩归 `ranking/policy_rules.py`；候选记录适配、锚点绑定与原 Mixin 执行归 `ranking/policy.py`。数据集路由计划归 `planning/dataset_routes.py`，模型查询展开归 `planning/model_expansion.py`；仅供黄金样例评估使用的 KG 摘要收回对应脚本。`configuration/options.py` 只处理搜索参数；缓存指纹和最终配置快照归 `configuration/fingerprint.py`，dataset scope 判断归 `recall/runtime_scope.py`。文档活动 pipeline 的 SQL 过滤归已有 `services/documents/pipeline_versions.py`，运行时直接调用真实所有者。

`recall/retriever.py` 保留 LangChain 请求协议与权限裁剪，实际召回直接调用通道函数与共享 `CorpusIndex`。已被这些函数替代的 Lexical/Sparse/ColBERT Mixin、独占旧缓存和影子搜索方法退出；索引 writer 和 query reader 使用同一资源所有者。

`recall/results.py` 合并通道结果、候选字段与向量结果规范化；具有 SQL/session 的补全由 `recall/enrichment.py:CandidateEnrichmentMixin` 持有。`stages/preparation.py` 集中初始化与查询展开阶段，`stages/search.py` 同时持有查询执行及其专属记录构造；`refinement.py` 表达重排后的层级扩展，`requirements.py` 表达 must-recall 补召回。编排入口的 23 个阶段名称与顺序保持。

模型/API/轻量重排统一归 `retrieval/reranking`，后置重排阶段只负责预算、缓存、校准和流程状态。ColBERT 的确定性哈希占位与注册、配置、脚本及专属 CI 已退出，`colbert`／`late_interaction` 执行选择明确报退役。历史 trace 的分数仍可读取，前端不会自动把已保存的选择换成另一个模型。

`reranking/api.py` 保留 OpenAI 与 DashScope 各自的请求/响应协议，`providers.py` 集中 provider 注册和能力元数据；算法、模型生命周期、工厂与惰性导出保持独立。重排缓存直接复用 `services/retrieval/corpus_tokens.py` 的真实版本；没有版本 token 时跳过缓存，继续执行重排。缓存未命中会正常创建 reranker，不再进入未赋值变量路径。

后置重排管线的环境 JSON 由 Settings 一次解析为 `model_policy.PostRerankStageConfig` 列表，校验失败作为配置错误报告。执行直接读模型字段，结果/trace/leaderboard 直接序列化相同阶段；三个摘要解析器退出。空配置、关闭标识、四个有效阶段上限及 `top_n=0` 的预算继承保持。

## Ingestion：解析、治理、分块与入库

`ingestion/parsing` 接收来源文件并持有解析器、模型资源、质量和增强。原始文件适配位于 `ingestion/parsing/files`，包含解析、位置、图像与回调语义。`contracts.py` 持有每文件状态和默认值，`pdf_backends.py` 持有 PDF 适配，`markdown.py` 持有 Markdown 读取与图片处理；`general.py` 负责格式调度和分块，book、laws、email 保留自己的真实算法。

`ingestion/governance` 接收解析后的文档，负责清理、去重、标签、脱敏和丢弃规则。`ingestion/chunking/strategies` 接收已治理的 Document，按以下内容归类。auto 与 manuscript 留在根层，负责实际的策略组合。动态注册使用 `capabilities.py` 的明确目标，保留 83 个标识的顺序、别名与可选依赖标志。

| 策略子包 | 内容 |
| --- | --- |
| `text` | 递归、Token、分隔符、句窗及文本层级 |
| `markup` | Markdown、HTML、RST、LaTeX 等标记内容 |
| `documents` | 书籍、论文、法规、SOP、简历、幻灯片等文档结构 |
| `records` | 表格、日志、邮件线程、对话、字幕等记录 |
| `code` | JSON、源码、SQL、API/schema 与 diff；JSON 和源码分别实现 |
| `config` | YAML、TOML、容器、CI、构建与基础设施配置 |
| `model_based` | 语义及已有实验性模型策略 |

四种 `integrated_*` 标识保持原含义。原始文件与预解析文本不是同一契约，不能因名称相似把 book 与 book_structured、laws 与 laws_structured 或 email 与 email_thread 相互替换。章节树、文本／图片／DOCX 合并及切块记录仍由各自实际工具持有，来源许可继续保留。

`ingestion/indexing` 将治理后的文档块、表格旁路和 metadata 映射交给现有 SQL、对象存储、向量和全文客户端；客户端生命周期仍由 `models`、`storage` 和 `infrastructure` 持有。解析、治理、分块和入库由同一 ingestion pipeline 顺序编排，不通过 API 路由相互调用。

## 其他领域

- `agents` 持有智能体及其专属 tools／middleware；包入口不导入 runner。离线预检 scanner 位于 `evaluation/scanning`。
- `evaluation` 按 regression、judging、generation、benchmarks、agents 等职责归类；已有 datasets、metrics、runners 与报告保持实际边界，资源位置不变。
- `llm/factory.py` 负责聊天模型选择与装配，`llm/client.py` 负责具体聊天客户端；异步向量适配在 `embedding/client.py`。
- `tracing` 持有 trace 契约、构造与诊断裁剪；`safety` 持有输入／输出保护、声明验证与答案质量。
- `kg`、`policy`、`workflows`、`pipeline_plugins`、`industry_rules`、`feedback_loop` 各有当前独立职责，不为统一外观合并。

迁移不保留旧私有导入的转发壳。生产调用方、动态目标与 CI 内嵌引用同步更新；冻结的 Python 测试不在本次范围，不据静态检查声称测试套件通过。验证与运行限制见 [验收记录](../maintenance/style-unification/rag-structure-verification.json)。

BM25 运维和 guard 调用直接使用 CorpusIndex，不经过 Retriever Mixin。写入、删除、回填和版本缓存由同一所有者持有；共享分词归 ingestion/governance/text/tokenization.py，使用 LEXICAL_TOKENIZE_* 配置。ColPali 和确定性 SPARSE 实验及其运行状态/派生索引退出，普通图像、OCR 和视觉模型服务保留。

分块目录不再保留 agentic_chunker、late_chunking、late_chunking_jina、raptor 实验实现。普通句子、命题、父子和其他真实策略继续由原模块维护；请求、默认规则、插件和缓存/checkpoint 的实际策略必须经过同一退休检查，历史元数据读取不改写。Milvus 为生产向量存储，memory 为显式开发后端；Qdrant/PGVector 占位实现退出。

证据文件使用 `source_labels.py`、`document_structure.py`、`excerpts.py` 表达实际职责；citation/TAG、quality/repair、gaps 和 capsule 继续保持各自契约。生成上下文归 `runtime/context.py`，SQL 元数据补全归 `recall/enrichment.py`。范围 verdict 共用 `policy/out_of_scope_verifier.py`，检索与流式存储适配分别归 `policy/out_of_scope_retrieval.py`、`out_of_scope_streaming.py`，保留各自的分数和失败政策；旧 evaluation 叶源码退出。结构树使用真实 ORM 字段，来源识别使用 Document metadata；capsule 的签名、哈希与白名单边界独立保留。
