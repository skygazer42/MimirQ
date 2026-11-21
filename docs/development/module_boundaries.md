# 模块职责与调用约定

维护目标是让一个业务改动集中在明确的位置，并能通过模块本身验证。

- API 路由处理请求解析、身份与权限入口、状态码和响应模型。
- `api/v1` 的业务路由归入 identity、conversations、documents、datasets、connectors、pipelines、evaluation、integrations、retrieval、system、knowledge_graph 十一个普通包。根 `__init__.py` 只持有 `get_router()` 装配入口；文档、连接器、会话的 `routes.py` 保留实际子路由聚合。域内导入实际叶模块，领域包不靠转发暴露旧路径；目录归类不改变 HTTP 前缀或注册顺序。
- 请求模型按领域放在 `app/api/schemas/{identity,conversations,documents,datasets,sources,pipelines,evaluation,integrations,system,knowledge_graph}/`，各领域是具有显式公开入口的普通包。域外消费者从所属领域包导入，域内继续从定义模块导入；共享 Pydantic 响应基类保留在 `schemas/base.py`。schemas 根入口不聚合所有领域。表单转换与 HTTP 输入约束放在 `app/api/utils/`。
- 业务操作放在对应服务模块，使用已声明的参数和返回类型；直接导入真实依赖。
- RAG ingestion 持有完整知识生命周期：来源、文档解析、治理、分块和入库编排归 `app/rag/ingestion/`。解析实现位于 `parsing`，治理位于 `governance`，已解析 Document 的分块位于 `chunking`；吸收的 DeepDoc 算法分别融入 `parsing/parsers`、`models`、`enrich` 和 `utils`，重复功能只保留一份。模型与词典资源位于 `app/rag/ingestion/parsing/resources`，保留原作者和许可声明，调用方直接导入实际实现。
- 用户文档的下载格式由文档服务持有：清理Markdown转DOCX位于 `services/documents/docx_export.py`，集中执行格式构造和首标题去重；API继续负责读取权限、缺内容404及文件响应。`parsing` 处理输入解析和自身产物规范化，旧output导出包源码退出。
- 路由装配模块只供入口组成路由，业务代码不反向导入它。不把整个模块通过 `Any` 参数层层传递。
- 内部数据沿用其确定类型；HTTP、JSON、Redis、插件等外部值在实际边界校验。
- 同一组业务选项只有一个映射位置。真实语义差异由调用方明确给出，例如切块预览关闭跨页公共行过滤。
- 跨页处理保留两种实际契约：Document碎片按页码metadata和连续编号合并；Markdown页按相邻顺序和递增编号拼接。重复表头不一致时页式入口保留原页；工作台的字典产物入口直接读写必需page_content，不适配未知对象形态。
- 不为拆文件增加代理、运行时属性转发、注册器或无实际变化的兼容层。只保留当前仓库确有调用者的旧入口，并让它引用实际所有者。

API schema 和 utils 等具有公开契约的包入口直接导入实际公开对象并显式声明 __all__，新增或调整公共契约在此维护，不新增转发函数、动态 getattr 或全局模型入口。普通业务/基础设施领域包的标记只说明职责，消费者从实际叶模块导入。utils 根入口发布基础文件和响应工具；管线及 URL 保留具名公共子模块，避免普通文件工具引入应用配置。包标记和公开入口承担导入契约，不按减少文件数量删除。

后端目录按实际职责维护：`api` 负责 HTTP，`services` 持有 HTTP/应用层操作门面，`models` 持有数据库映射，`types` 放跨模块内部数据契约；`rag/ingestion` 持有知识生命周期，`rag/retrieval` 和 `rag/runtime` 持有检索生成，`storage` 持有存储客户端，`connectors` 持有外部数据源接入，`tasks` 负责后台任务入口，`infrastructure` 放应用配置与共同基础设施。新增通用能力先检查这些实际所有者，不再为同一职责另开一个顶层目录。来源许可保留在代码头和 NOTICE，不用一套第三方转发目录代替实际维护位置。`services` 与 `rag` 的后续归类需沿调用链处理定义和消费者，不把文件改名或搬入子目录当作职责整理完成。

`models` 只放 SQLAlchemy 实体，包括 `knowledge_graph/entities.py` 的知识图谱定义。`registry.py` 是完整表注册的唯一清单，应用、Alembic、使用 ORM 的 CLI 和后台 worker 在自己的数据库启动边界显式导入；普通模型包入口不重复维护导出清单。`api/schemas/base.py` 的 `OrmModel` 是将 ORM 属性转换为 API 数据的 Pydantic 基类，不是数据库 Base；后者由 `infrastructure/database/connection.py` 持有。

ORM实际定义按九个领域持有：identity、conversations、datasets、documents、connectors、pipelines、templates、evaluation、knowledge_graph。知识图谱实体当前位于 `models/knowledge_graph/entities.py`，原具名根文件只作历史来源。租户与组、会话与摘要、文档与索引通道、扫描运行和版本模板按同一聚合合并；跨领域AuditLog保留 `models/audit_log.py`，不为目录对称建立单叶system包。

数据集枚举/授权实体归 `models/datasets/access.py`，文档授权实体归 `models/documents/access.py`。records可直接依赖其必需枚举；不通过反向导入所有实体、包聚合或数据库基础设施隐式补齐mapper。CLI/worker在查询前明确导入registry，根main/API启动继续拥有全量注册。

内部文档对象及转换协议位于 `types/rag_document.py`，文档管线选项位于 `types/pipeline_options.py`。解析、索引和检索共用的元数据格式与规范化位于 `types/document_metadata.py`，索引视图键位于 `types/indexing.py`；这些模块不从 HTTP 模型转发名称，也不加载 RAG 引擎。

`services` 按实际业务归到普通应用包：聊天、文档 HTTP 门面、数据集、连接器、提示词、报告、身份、评估和运行资源。知识生命周期的解析、治理、分块和索引编排归 `rag/ingestion`；事务写入、缓存、模型适配及存储连接继续保留独立资源所有者。领域包入口不聚合全部实现。使用明确叶模块，例如 `services.documents.ingestion`、`services.chat.stream_orchestrator` 和 `services.tables.store`。事务写入、缓存、模型适配及存储连接继续保留独立资源所有者。

RAG 不另设一套全局 `core`：会话引擎、流式阶段、LangGraph 装配及持久资源归 `rag/runtime`；检索分别由 `retrieval/planning`、`corpus.py`、`expansion`、`recall`、`ranking`、`reranking`、`evidence`、`configuration`、`cache` 和 `stages` 持有。recall 召回候选，ranking 融合、去重及排序，reranking 持有模型/API 重排，stages 只编排阶段及其专属记录。`retrieval/orchestrator.py` 只组装执行阶段。模型调用和响应解析归 `rag/llm`，异步向量适配归 `rag/embedding`，声明验证和答案质量归 `rag/safety`，指标与 trace 契约归 `rag/tracing`。查询的入库一致性归一化、词典扩展和路由规则统一在 `app/query`；两种扩展匹配规则保留各自明确入口。checkpoint 具有实际恢复用途，LangGraph store 保留已公开的配置与装配契约，二者在 runtime 内保持独立生命周期。目录与入口见 [RAG 结构说明](rag_structure.md)。

| 共同能力 | 实际所有者 |
| --- | --- |
| 日志对象 | 标准库 `logging.getLogger`；显式及迁移前的日志分类保持稳定 |
| 项目日志配置、日志字段上下文、解析子进程格式 | `app/infrastructure/observability/logging.py` |
| HTTP 代理环境与本地绕过设置 | `app/infrastructure/http/environment.py` |
| 错误定义与统一异常转换 | `app/infrastructure/exceptions.py` |
| 稳定哈希、HMAC、JSON 指纹 | `app/infrastructure/hashing.py` |
| 元数据过滤 | `app/infrastructure/metadata_filters.py` |
| 密码哈希、令牌签发、未验证诊断读取 | `infrastructure/security/passwords.py`、`jwt_tokens.py`、`jwt_inspect.py`，各自职责独立 |
| Token 计数与估算 | `app/infrastructure/tokens.py` |

`infrastructure` 表示应用配置与共同基础设施，内部按 security、database、http、observability、redis、runtime、regex 七组归类。根 `config.py` 保持现有 Settings 字段与启动校验顺序；`config_validation.py` 和 `env.py` 不为了分类再套会提前加载 Settings 的公共包。包入口不启动连接或聚合可选依赖。共享常量归真实所有者，旧 constants 模块不保留转发；未验证 JWT 诊断不能用于认证。原 `app/core` 已整包更名，不设置兼容包。

迁移时同步普通、局部、相对和动态引用，也核对 CI 内嵌 Python、资源根目录、队列函数身份与日志类别。退役路径不保留转发模块；逐文件的新位置和处理理由见 [命名与归属清单](../maintenance/style-unification/layout-review.csv)。

来源与维护位置分别记录。已经吸收的解析算法和原始文件适配由 `rag/ingestion/parsing` 维护；已解析 Document 的策略和章节工具由 `rag/ingestion/chunking` 维护，并接受项目检查。文件入口直接使用 `app.rag.ingestion.chunking.factory.chunk_file`；通用调度、PDF 后端、Markdown 读取和每文件契约分别持有实现。`strategies` 只组织接收已解析 Document 的文本策略，按 text、markup、documents、records、code、config、model_based 分类；JSON 与源码分块分别持有实现。章节结构、段落合并和记录构造各有单一所有者。原 third_party 集成包的转发、无调用常量和空工具退出。清理重复时核对数据形状与失败策略：JSON 结构分块与普通 JSON 展示、OCR 表格组装与 TATR 几何检测、Trie／NLTK 与 Jieba 分词各有实际职责，保留不同算法，合并相同实现。解析库不反向依赖检索执行；文件分块流程直接调用 ingestion parsing。

`rag/ingestion/chunking` 根入口只说明职责，实际工厂和层级工具分别从定义模块导入；轻量 NLP 模块不因包导入加载工厂/治理链。四种 `integrated_*` 标识保留已有配置含义，不能直接用名称相似的预解析文本切块器替换。可选同步视觉客户端使用 `VisionCaptionClient(model_name=...)`，共享图片编码供 VisionReader 使用；两者实际传输和错误策略不同，不假定等价合并。

文档模块的首批落点：

| 职责 | 位置 |
| --- | --- |
| URL / HTML 入库请求与覆盖参数 | `app/api/schemas/documents/ingestion.py` |
| 文件保存、文件名和来源路径规范 | `app/api/utils/file_io.py` |
| pipeline 表单验证与类型转换 | `app/api/utils/document_pipeline_input.py` |
| 治理选项统一映射 | `app/services/document_governance.py` |
| 分段访问、索引操作结果与一致性处理 | `app/services/document_chunk_operations.py` |
| 上传/重试调度、队列交接与本地源清理 | `app/services/document_processing_dispatch.py` |
| 文档状态、取消、重试与pending可重配策略 | `app/services/document_processing_operations.py` |
| 解析 / 切块预览 HTTP 流程 | `app/api/v1/documents/preview.py`、`documents/chunk_preview.py` |

重构验证既包括行为回归，也包括依赖方向：子模块可先于路由装配器导入，独立执行时不加载装配器，原有 OpenAPI 保持一致。不要为了通过测试重新加入模块查找；将测试依赖替换指向实际所有者。

文件与 URL 工具的边界：

- `app.api.utils.file_io` 持有上传、文件哈希、来源路径和部分文件清理。上传与 URL 下载共用 cleanup_partial_file；关闭／清理仍使用五秒的有界取消屏蔽，清理 OSError 记录来源操作后保留原传输失败。
- 包外从 app.api.utils 导入 normalize_upload_key、normalize_upload_path_parts、sanitize_upload_filename 等已公开基础工具，不通过私有名别名或转发函数组装依赖。URL 的 ValidatedFetchTarget、validate_fetch_target 与 build_pinned_http_clients 从具名 url_ingest 子模块导入，管线转换由 document_pipeline_input 子模块发布。
- URL 下载继续逐跳验证 DNS 与目标地址、固定 Host／SNI，并在跨 origin 时去掉敏感头。管线输入、URL 默认参数和响应头保留各自实际职责；真实的 None／0／False 语义不为统一外观改写。
- URL 模块先展示公共记录和校验／下载入口，再展示内部策略。下载主循环区分正常响应和跳转；状态检查、实际字节限额、写入、关闭文件和元数据构造由同一个响应保存函数顺序完成。正常结果在响应／客户端关闭后返回，跳转目标在旧客户端退出后重新校验。普通格式错误在入口统一为 400 Invalid URL；系统解析与传输异常直接交统一异常入口，下载只负责清理后原样抛出。
- 下载大小、超时和跳转设置由 document_ingestion_sources 直接提供必填参数，不经过可空选项对象或第二次默认值回填；只有实际可选的 User-Agent 与额外请求头保留可空语义。普通响应和跳转按状态码分流，跳转解析返回确定的网址。
- 初始网址在 document_ingestion.ingest_url 中校验为冻结的 ValidatedFetchTarget，经过文档来源服务直接传到下载器；下载使用同一个已验证 IP，不再丢弃目标后重复解析。数据集权限检查与来源原始 URL 语义保持；每个新跳转仍完整校验。跳转预算只使用剩余次数，文件与响应关闭仍由原来的拥有者负责。
- 下载数值在 Settings 加载时校验，工具不重复处理无效配置或超时回填。实际保存的解码字节在写入前按 max_bytes 检查，Content-Length 不单独触发应用级拒绝；传输协议有效性仍由 HTTPX／h11 负责，该限额不代表网络接收量或解码峰值。
- 文件响应使用 file_response_headers 和 set_content_disposition；attachment 是已有默认行为，下载调用不再另设相同默认值的包装。

数据库连接器的边界：

- HTTP 验证入口将已解析的配置交给 `app.connectors.connectivity.check_database_connection`；同步驱动在线程执行，连接失败和无法读取权限继续使用既有检查结果与警告格式。
- 保存配置与调度任务保留原始配置字典，交给 `app.connectors.catalog.run_catalog_sync`。不能用 HTTP 模型的默认值替换这条路径原有的画像开关、额外 ODBC 配置及权限哈希内容。目录 SQL 返回的 Mapping 只在读取边界转换成 CatalogTableInput／CatalogColumnInput，存储和快照直接使用这些对象。
- `app.connectors.store.SQLAlchemyCatalogStore` 持有调用方的 Session，只 flush，不 commit。任务层继续负责状态、审计、提交和失败处理。
- 画像隐私过滤由 `app.connectors.profile_privacy.sanitize_db_profile_snapshot` 持有，供存储与 API 读取共同使用，保留原始 JSON 的必要校验。同步查询失败继续传播；可选行快照只跳过明确的 SQLAlchemy 查询错误并记录警告，其他错误交给已有任务入口处理。

全文检索的索引/评分由 Milvus 执行，应用的 CorpusIndex 持有写入、回填、范围与版本缓存。Retriever 不再承担 BM25 运维转发。PostgreSQL lexical 分别提供正文全文/模糊与元数据精确匹配，保护候选和既有降级顺序保持；它不冒充额外的向量模型。共享词法分词使用 LEXICAL_TOKENIZE_* 参数。SPARSE/ColPali 实验不再注册或执行。

向量工厂只发布 Milvus 与明确的 memory 开发后端，区域选择与健康状态复用同一后端解析。Qdrant/PGVector 占位实现、四种实验分块和虚构 RTBF 状态查询已退出；真实层级切块、普通策略和 RTBF 清理 POST 保留。旧策略在实际写入/执行边界拒绝，历史响应只展示旧名称；不通过包转发或默认映射恢复能力。

`retrieval/configuration` 保留搜索参数、模式/预设、证据契约、预算、指纹与配置快照。候选插件规则、预算和压缩归 `retrieval/ranking/policy_rules.py`，记录适配和 Mixin 执行归 `policy.py`；数据集路由归 `planning/dataset_routes.py`。scope 检测归 `retrieval/recall/runtime_scope.py`，活动文档版本 SQL 归 `services/documents/pipeline_versions.py`。配置入口不反向加载业务执行器，也不以旧路径转发隐藏实际所有者。

`retrieval/evidence` 保留引用、片段、来源标签、质量、缺口、结构、证据包和证据指标；SQL 元数据补全归 `recall/enrichment.py`，生成上下文归 `runtime/context.py`。引用构造复用已解析的 TAG，诊断收回单次转发，内部 Document/ORM 使用确定字段；外部 metadata 和证据包继续在边界验证。共享 scope verdict 由 `policy/out_of_scope_verifier.py` 持有，检索与 streaming 的适配器归 `policy/out_of_scope_retrieval.py`、`out_of_scope_streaming.py`，分别保留其返回形状和失败政策。

通道结果、候选字段和向量规范化集中到 `recall/results.py`；Document 身份只由 `retrieval/results.py:document_key` 持有。OpenAI/DashScope 适配同属 `reranking/api.py`，provider 注册和能力说明同属 `providers.py`，具体算法和资源生命周期仍分别维护。重排缓存使用 `services/retrieval/corpus_tokens.py` 的真实语料版本；无法取得版本时明确 bypass 缓存，不另建只含 scope 的占位版本。

后置重排管线由 `Settings.EVIDENCE_POST_RERANK_PIPELINE` 持有已验证的 `PostRerankStageConfig` 列表；环境 JSON 只在该配置入口解析。执行层使用模型字段，证据结果、流式 trace 和 leaderboard 序列化相同对象；不在业务层重新解析字符串或把解析失败返回为空数组。空配置和空数组继续表示未配置。
