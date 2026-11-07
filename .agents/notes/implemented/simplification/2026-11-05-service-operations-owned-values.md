# Agent Note: 运维审计服务直接表达自有记录

Status: implemented

## Problem

目录文档、证据审计、索引核对与保留作业把实际完整 ORM 实体再次当成未知对象探测。内部已经归一化的去重记录、计数器和迁移配置重复转型，掩盖了原始 SQL Row、JSON、Redis 与向量 SDK 的真实边界。部分字段只写成 Any，也使延迟导入和资源所有权难以判断。

## Decision

17 个运维审计 owner 保持原模块函数。完整 Document、EvidenceItem、DbCatalogTable／Column／Profile、DocumentIndexChannel 与 IndexDriftItem 直接读取声明字段；陈旧报告读取同一查询明确标记的十列 Row。原始引用、UUID、聚合值、metadata、向量和 Redis 载荷的清理、转换与失败政策继续在原边界执行。

五份私有 TypedDict 只描述实际构造的去重行、引用指针、五字段迁移配置、索引分类和版本累计状态，不建立新运行时框架。计数与数值简化以显式 int／float 归一化、局部零值加一、builtin len、datetime 和 perf_counter 的生产者为依据。dataclass 或数字注解本身不构成删除转换的理由，公开序列化和原始输入转换继续保留。

目录模型、Indexer、embedding factory、向量 adapter、Redis 与 BackgroundTasks 的新类型依赖仅在 TYPE_CHECKING 下导入。实际 lazy import、Session 门、初始化失败阶段、两个迁移运行时、死信落盘与刷新、PNG 任务的 Session／Thread／Event 所有权不变。删除回调沿用同一个真实异步生命周期。

保留策略仅在原三处位置直接调用 db.commit，退出无政策的私有转发函数；RTBF 退出无引用的 _safe_int。索引通道解析退出两支都返回同一值的 has_rows 参数和唯一调用方实参。逐项删除、整个数据集缓存失效重试组、回滚、版本保护、审计与错误映射仍由原 owner 负责。

2026-11-07 索引规则增量：旧通道状态由 document_index_channel_service 的 legacy_document_index_channel_status 持有，索引审计退出整份重复实现。审计取得新构造的状态字典后移除 attempt_count，保持原六字段投影和默认值仍逐通道计算的时点；通道摘要继续保留原计数字段。两个写入分支使用同一个私有错误文本规则，仍先 strip、截断 2000 字符，再把空文本归空，不把历史行读取一并截断。

两个文档适配器复制 ORM 元数据后，直接使用既有 get_active_pipeline_hash，保留 active/current 字段优先级和空白规则。显式空白 override 仍直接返回空，不合并为 get_selected_pipeline_hash 的另一种空白回退。core 使用显式缺省判断，只在参数为 None 时选择默认映射或字符串，保留非空但布尔值为假的映射。复杂条件中的单次求值改成有业务含义的局部语句，没有恢复 or-None 写法。

## Alternatives considered

- 统一删除反射和转型能得到更整齐的代码，但 SQL Row、raw JSON、SDK 数值和混合异常确实有不同来源；仅收窄已经证明的完整实体与内部记录。
- 把目录和迁移依赖提前导入可以缩短私有签名，却会改变首次访问模型、Indexer 和 SDK 的阶段；TYPE_CHECKING 表达类型，真实依赖仍按原时间创建。
- 增加 Context／兼容包装能够集中参数，但会建立第二层调度与回退。原函数已经拥有业务顺序，只需表达具体字段、回调和自有结果。

## Consequences

内部记录和资源边界更明确，未添加空值分支、重试、配置或默认成功。两个真正的原始边界模块 db_catalog_observability 与 evidence_drift_audit 逐字节保留。数字转换仍可出现在同一个调用链中，维护者应根据实际生产者判断，而不能按外观或注解批量删除。

本记录与[配置服务内部值](2026-11-05-service-configuration-owned-values.md)部分相邻，各自持有独立类别；[缓存失效事务](../bug-fix/2026-11-03-corpus-cache-invalidation-transaction.md)继续持有原重试与事务规则。[引用未扫描后缀修复](../bug-fix/2026-11-05-evidence-repair-preserves-unscanned-references.md)和[周期审计单列 Row 修复](../bug-fix/2026-11-05-periodic-audit-single-column-rows.md)是前置的独立行为提交，不归入本次风格差异。活跃笔记检索未发现需吸收或归档的同一运维决定。

全文读取整组 17 个 owner 及实际生产者和调用方，复核 15 份完整差异。Ruff、Python 3.11 AST、固定源码／签名绑定、SQL／资源／错误／字典形状和笔记校验提供有界证据；没有添加、扩展或执行 Python 测试，也没有运行应用、SDK、数据库、服务、回调或业务正则。静态结果不代表运行时回归。

本次有界增量的源码记录位于 channel-error-normalization-20261107。三个模块相对开始快照共减少 49 行，完整 AST 对照限定规则内联、局部绑定、明确的四处缺省表达式、重复函数退出和真实调用迁移；未触及的函数、SQL、事务、测试与模型保持。Python 3.11、Ruff 和格式检查通过，未运行 Python 测试或业务函数；缺少 TruffleHog 的自动模型审查限制沿用既有记录。
