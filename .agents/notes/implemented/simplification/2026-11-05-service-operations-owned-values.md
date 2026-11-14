# Agent Note: 运维审计服务直接表达自有记录

Status: implemented

## Problem

目录文档、证据审计、索引核对与保留作业把实际完整 ORM 实体再次当成未知对象探测。内部已经归一化的去重记录、计数器和迁移配置重复转型，掩盖了原始 SQL Row、JSON、Redis 与向量 SDK 的真实边界。部分字段只写成 Any，也使延迟导入和资源所有权难以判断。

## Decision

17 个运维审计 owner 保持原模块函数。完整 Document、EvidenceItem、DbCatalogTable／Column／Profile、DocumentIndexChannel 与 IndexDriftItem 直接读取声明字段；陈旧报告读取同一查询明确标记的十列 Row。原始引用、UUID、聚合值、metadata、向量和 Redis 载荷的清理、转换与失败政策继续在原边界执行。

五份私有 TypedDict 只描述实际构造的去重行、引用指针、五字段迁移配置、索引分类和版本累计状态，不建立新运行时框架。计数与数值简化以显式 int／float 归一化、局部零值加一、builtin len、datetime 和 perf_counter 的生产者为依据。dataclass 或数字注解本身不构成删除转换的理由，公开序列化和原始输入转换继续保留。

索引核对的 readiness 字典由实际 DocumentIndexChannelSummary.to_dict 完整构造；状态与计划直接读取其必需字段，按分类器的五种固定状态累计计数。查无文档时仍在状态生产者返回空；消费者不再为已存在状态重复猜测文档缺失。外部 marker、UUID、SDK 与历史通道边界继续按原策略处理。

死信错误文本与来源按原顺序截断、将空文本归空，来源规则在新建和复用分支前只写一处。Document.processing_attempts 来自实际 Integer 字段，保留原 int、非负修正与加一，退出读取／转换异常后直接写 1 的兜底；异常交给既有调用方的 DLQ 日志边界。提交、刷新降级、开放记录复用、重放和租户条件保持。索引任务标识、处理人、说明及通道哈希使用顺序归一化，原上限和空值含义保持。

目录模型、Indexer、embedding factory、向量 adapter、Redis 与 BackgroundTasks 的新类型依赖仅在 TYPE_CHECKING 下导入。实际 lazy import、Session 门、初始化失败阶段、两个迁移运行时、死信落盘与刷新、PNG 任务的 Session／Thread／Event 所有权不变。删除回调沿用同一个真实异步生命周期。

保留策略仅在原三处位置直接调用 db.commit，退出无政策的私有转发函数；RTBF 退出无引用的 _safe_int。索引通道解析退出两支都返回同一值的 has_rows 参数和唯一调用方实参。逐项删除、整个数据集缓存失效重试组、回滚、版本保护、审计与错误映射仍由原 owner 负责。

2026-11-07 索引规则增量：旧通道状态由 document_index_channel_service 的 legacy_document_index_channel_status 持有，索引审计退出整份重复实现。审计取得新构造的状态字典后移除 attempt_count，保持原六字段投影和默认值仍逐通道计算的时点；通道摘要继续保留原计数字段。两个写入分支使用同一个私有错误文本规则，仍先 strip、截断 2000 字符，再把空文本归空，不把历史行读取一并截断。

两个文档适配器复制 ORM 元数据后，直接使用既有 get_active_pipeline_hash，保留 active/current 字段优先级和空白规则。显式空白 override 仍直接返回空，不合并为 get_selected_pipeline_hash 的另一种空白回退。core 使用显式缺省判断，只在参数为 None 时选择默认映射或字符串，保留非空但布尔值为假的映射。复杂条件中的单次求值改成有业务含义的局部语句，没有恢复 or-None 写法。

持久化通道状态的五个共同字段由 document_index_channel_status 构造新字典，按原顺序读取 channel、required、enabled、status 和 error。详情随后添加原计数、时间和 legacy 字段；审计只添加原 legacy 字段，不读取详情专属属性。历史错误文本的读取不套用写入的 2000 字符限制，空文本仍显式归空。退出审计里的 _row_index_channel_status 副本，保留完整 ORM 查询、版本匹配与赋值前的失败边界。

五个开关由 document_index_channel_flags 映射实际 PipelineEffective。真实构造器的 _resolve_flag 和 BM25 条件已经产生原生 bool，审计退出第二份映射和重复 bool 包装。各模块仍在原位置通过各自 resolve_pipeline_effective 绑定解析配置，再传入已构造结果；没有移动解析依赖、缓存或已有注入入口。只在类型检查时引用 PipelineEffective，不增加运行时初始化。

会话契约增量：SessionLocal 通过绑定 engine 的 sessionmaker 构造真实 SQLAlchemy Session，get_db 和检索会话工厂沿用该资源。安装版本的 get_bind 返回 Engine／Connection 或抛错，begin_nested 提供事务上下文，dialect.name 是字符串。索引通道写入直接打开保存点、选择原 PostgreSQL／通用 SQL 分支、统一执行 upsert，再按原位置提交和刷新。退出单次转发的 _persist、dialect 与错误日志辅助函数，保留异常级别、格式化日志消息和真实 Session 的失败处理；缺少框架方法的对象不再走另一条直接写入路径。

Dify HTTP 锁适配器和两处检索数据库判断直接读取相同的 SDK 属性，保留原调用绑定、PostgreSQL advisory 锁键及 SQL、非 PostgreSQL 提前返回、检索过滤／排序和 finally 关闭。API 适配器仍持有原回调入口，未引入新的服务导入时点或通用数据库包装层。

Connector execution 的 active run 查询、running 转换、cancelled 收尾和 best-effort failed 记录由 `app.services.connector_execution.shared.runtime` 持有。各 connector 以原私有名导入同一函数，保留 tenant 谓词、documents eager-load、终态过滤、commit/refresh、stats finalize、错误截断以及 config sync 的原顺序；不同的 connector 业务循环和非同体失败流程继续留在各模块。

Connector 执行链直接传递自身构造的认证头、来源引用和 provenance 字段，不再把空字典或空文本改写成 `None`。Confluence 的页面信息由 listing parser 产生，Jira 的 `JiraIssueInfo` 明确区分三个必有字符串和一个真实可空的更新时间；消费端按键读取必有字段。第三方 listing、时间戳提取和 SDK prefix 仍保留各自真实的可空边界。

## Alternatives considered

- 统一删除反射和转型能得到更整齐的代码，但 SQL Row、raw JSON、SDK 数值和混合异常确实有不同来源；仅收窄已经证明的完整实体与内部记录。
- 把目录和迁移依赖提前导入可以缩短私有签名，却会改变首次访问模型、Indexer 和 SDK 的阶段；TYPE_CHECKING 表达类型，真实依赖仍按原时间创建。
- 增加 Context／兼容包装能够集中参数，但会建立第二层调度与回退。原函数已经拥有业务顺序，只需表达具体字段、回调和自有结果。

- 计数出错时写 1 能让死信流程继续，但它会把失效对象或内部错误变成一个可提交的次数，掩盖问题；已有处理器会记录非关键死信写入失败，因此不再伪造计数。
## Consequences

内部记录和资源边界更明确，未添加空值分支、重试、配置或默认成功。evidence_drift_audit 的原始边界保持；db_catalog_observability 后续已按真实执行 wrapper 收窄必有 ID／耗时／result 输入，真正可空 catalog metadata 仍保留转换，见[服务输入实际所有者](2026-11-14-service-input-owners.md)。数字转换仍可出现在同一个调用链中，维护者应根据实际生产者判断，而不能按外观或注解批量删除。

本记录与[配置服务内部值](2026-11-05-service-configuration-owned-values.md)部分相邻，各自持有独立类别；[缓存失效事务](../bug-fix/2026-11-03-corpus-cache-invalidation-transaction.md)继续持有原重试与事务规则。[引用未扫描后缀修复](../bug-fix/2026-11-05-evidence-repair-preserves-unscanned-references.md)和[周期审计单列 Row 修复](../bug-fix/2026-11-05-periodic-audit-single-column-rows.md)是前置的独立行为提交，不归入本次风格差异。活跃笔记检索未发现需吸收或归档的同一运维决定。

全文读取整组 17 个 owner 及实际生产者和调用方，复核 15 份完整差异。Ruff、Python 3.11 AST、固定源码／签名绑定、SQL／资源／错误／字典形状和笔记校验提供有界证据；没有添加、扩展或执行 Python 测试，也没有运行应用、SDK、数据库、服务、回调或业务正则。静态结果不代表运行时回归。

本次有界增量的源码记录位于 channel-error-normalization-20261107。三个模块相对开始快照共减少 49 行，完整 AST 对照限定规则内联、局部绑定、明确的四处缺省表达式、重复函数退出和真实调用迁移；未触及的函数、SQL、事务、测试与模型保持。Python 3.11、Ruff 和格式检查通过，未运行 Python 测试或业务函数；缺少 TruffleHog 的自动模型审查限制沿用既有记录。

后续状态投影记录位于 index-channel-state-projection-20261107。两模块完整 AST 对照核对共用字段、详情追加字段及键序、原生 bool 的实际生产者、解析调用绑定、逐列读取顺序与赋值顺序；八个模型、生产者、API 和既有测试文件的哈希保持。Ruff、格式、Python 3.11 与记录门禁提供静态证据，未运行 Python 测试、业务函数或外部服务。

会话契约记录位于 bound-session-contracts-20261107，保存三个 owner、十二个实际调用／工厂／测试来源及安装 SDK 的源码哈希和方法契约。完整 AST 投影限定直接 SDK 读取、真实 Session 保存点分支内联、相同 kwargs／upsert／finish 顺序及日志消息归约；另外代码、签名、SQL 和调用者保持。共退出 12 处字段存在性 getattr。验证仅使用源码、Python 3.11、Ruff、格式与记录门禁；未执行测试、SDK、业务函数、数据库或服务，未启动缺少 TruffleHog 的模型审查。

索引与失败记录契约的源码证据保存在 `E:/MimirQ/.superpowers/audit-failure-record-contracts-20261107/`。实际模型、完整状态生产者、唯一计数调用者和错误日志入口均已核对；完整源码、AST、部分暂存区补丁以及 Ruff／格式／笔记校验给出有界证据。未运行或修改 Python 测试，未执行应用、SDK、模型、数据库或外部服务；静态证据不证明运行时回归。
