# Agent Note: 运行时服务区分资源与内部结果

Status: implemented

## Problem

运行时指标、lineage、追踪与缓存服务重复探测完整实体和已构造记录的字段；指标桶仍用宽泛字典表示，已归一化的计数被再次转换。另一方面，线程队列、租约、任务、缓存与可选 SDK 适配承担真实生命周期，不能因为它们看起来复杂就拆成无状态包装。

## Decision

14 个 owner 沿用原模块函数、真实领域记录与资源。Lineage 使用实际查询返回的 Document、DocumentChunk、DocumentPermission 和 TenantMember；Phoenix、trace diff、warmup 使用实际 RagTraceBundle、RagTrace 和 RerankResult 声明字段。可选 enrichment、原始 JSON、引用、Redis／向量数值、未知 task factory、embedding 方法与 OTel 插件边界继续保留原适配。

两个私有 TypedDict 只表达本模块实际构造的四字段指标桶与五字段分析桶。局部零值加一、显式 int／float 生产者、len／enumerate、实际时间函数及归一化 helper 的结果直接传递；原始值转换、真正的 int 到 float 运算、分位数、异常阈值、NaN／finite 规则与输出副本均保持。dataclass 的数字注解本身不用于证明转换多余。

MetricsWriter 继续拥有 Queue、Thread、Event 和锁，队列元素明确为字典或关闭 sentinel None。Limiter 保留全部信号量、thread-local、lease、心跳、取消与 Session 顺序；真实 multi-agent 调用传 None，因此 request_db 明确为 Session 或 None，并用同一 best-effort suppress 包围非空 Session.rollback，替换未知对象的 getattr／callable 探测，不增加回退或事务。

迁移资源类型引用仅在 TYPE_CHECKING 导入，真实 embedding、Milvus、Redis、ArqRedis 与 PIIRedactor 创建阶段不变。ArqRedis 来自 create_pool／get_queue 和 worker ctx 的真实 pool；观测 helper 既有五字段返回值有一致注解。缓存签名函数与哈希、查找／写入顺序、失效与清理预算、迭代器 close、轮询器 Event／Task／锁／缓存寿命、Prometheus 和 SLO 回退政策保持。

Incident ZIP 与通用 JSONL tail 两个 owner 逐字节保留。另两套 JSONL reader 的失败截断标记与通用 reader 不同，保持各自边界。已授权的[新鲜度两列 Row 修复](../bug-fix/2026-11-05-periodic-freshness-two-column-row.md)前置且独立于本风格提交。

## Alternatives considered

- 按注解批量去掉转换或反射可以减少更多行，但原始 JSON、SDK、可选插件和动态线程状态确实缺少统一运行时保证；只收窄有实际生产者的字段与内部记录。
- 合并三个相似 JSONL reader 可以减少重复，却会改变读取失败时的 truncated 政策。这里保留各个业务 owner，避免把接口差异藏进新框架。
- 将客户端和任务状态包装成统一 Manager／Context 可以集中类型，却会增加调度层。原资源已经有明确锁、关闭、缓存和错误归属，只需表达现有契约。

## Consequences

内部类型与原始边界更明确；代价是必要的 SDK／JSON 数值转换仍与原生值并存，不能据此推断整个链都无需校验。新增输入路径时需重新核对生产者，而不是把非标准对象悄悄交给收窄后的内部函数。没有新增配置、重试、兼容层、默认成功或静默错误政策。

按具体模块名检索活跃笔记，没有同一运行时 owner 的既有决定需要吸收或归档。[标准流计划投影](../bug-fix/2026-11-05-standard-stream-plan-projections.md)持有上游 Engine 的事件与会话次序，本篇只消费其现有契约，不迁移上游所有者。缓存与实际资源的既有政策继续保持。

全文读取 14 个 owner 和实际生产者／调用方，完整复核 12 份差异。357 个完整函数 AST 仅在显式列出的原生表达式、声明字段、类型、纯真值与可空 Session 投影后相等；raw exact 计数另列。Ruff、格式、固定 Git、静态签名绑定与笔记校验提供有界证据；没有添加、扩展或执行 Python 测试，也没有运行应用、SDK、模型、数据库、服务、回调或业务正则，不声称运行时回归。
