# Agent Note: 检索语料与索引内部值的所有权

Status: implemented

## Problem

语料、稀疏索引与 ColBERT 索引在本地构造的记录上重复探测字段、转换已经确定的标量。BM25 首次构建还复制了增量更新已有的 chunk ID 映射循环。沿调用链阅读时，这些写法混淆了本地记录与原始元数据、持久化文件和模型结果的解析边界。

## Decision

本地 ColBERT 缓存标注实际的 `ColbertAnnIndex`，直接读取该记录声明的字段。记录来自当前构造器或 `ColbertAnnIndexStore.load`；文件加载继续校验 JSON、schema、指纹、NumPy 形状与 ID 数量。可空值判断、容器复制、可选模型导入、工厂回调和原有异常策略保留。`CorpusBuildLock`、缓存锁、缓存所有者与活动 mixin 保持原生命周期。

Settings 已声明字段使用属性访问。Settings 不启用赋值验证，旧 `HybridSearchOptions` 也允许直接接收 overrides，因此数值、字符串与布尔转换、`or` 默认值及原有转换异常处理继续保留。仅字段存在性的备用读取被移除。

BM25 首次构建复用现有 `_build_chunk_id_lookup`；调用仍位于 retriever 构造之后、缓存锁和写入之前。文档 ID 与 pipeline key 的双重映射、缺失值跳过、遍历顺序和覆盖规则相同。本地布尔值、`len` 计数与已计算的浮点分数直接传递。

PLAID 的公开压缩入口继续将原始向量转换为浮点数，并解析 centroid 数量。私有距离、去重与 centroid 选择直接处理这些归一化值；输出仍复制每行 centroid 和 cluster sizes。解压入口的原始 payload 解析不变。

两条活动 ColBERT 路径保留各自指纹：旧 mixin 按 ID 与 pipeline 标记逐行哈希；`CorpusArtifacts` 使用包含内容哈希的排序 JSON。它们的资源所有者和失效策略不同，不能仅因名称相近而合并。

## Alternatives considered

统一索引与指纹可以减少重复，但会改变仍在使用的缓存兼容和失效策略。当前只收窄已知记录的访问，保留两条路径。

依据类型注解移除全部转换可以进一步缩短代码，但 Settings 的运行时赋值、旧参数、持久化文件、provider 分数和元数据没有统一的已验证输入保证，仍承担实际解析职责。

为全部索引返回值增加新协议或通用管理器可以集中描述工厂，但当前实际缓存记录已经存在；新增抽象会扩大迁移范围，且不能替代外部数据校验。

## Consequences

内部值的生产者与使用者更直接，公开参数、返回字典、排序、过滤、指纹、指标和资源顺序保持。外部数据仍需要现有解析；以后若缓存引入另一种记录实现，必须重新检查字段契约。

本次历史笔记审计中，[共享标量转换](2026-11-03-shared-scalar-coercion-owner.md)与原始数值边界部分重叠，[混合检索排名](2026-11-05-hybrid-ranking-owned-values.md)与内部值规则部分重叠，[语料缓存失效事务](../bug-fix/2026-11-03-corpus-cache-invalidation-transaction.md)与资源时序部分重叠；三者保持原决定并互链，没有被替代。检索命中的重排 provider 回退记录属于不同工厂错误政策，本次不修改。

[检索编排内部记录](2026-11-05-retrieval-orchestration-owned-values.md)沿用可变 Settings 的值边界，并明确插件配置、后重排校准和层级 ORM 记录；本篇语料与双指纹决定保持。

## Verification

19 个语料与混合渠道所有者完整审阅。Python 3.11 AST 对照保留 325 个函数的参数名、默认值和装饰器，保留数据库语句调用、with 上下文、异常类型及导出。Ruff 检查、格式检查与 diff 检查覆盖该组文件。验证限于静态源码和真实生产者、调用方契约；按任务限制不运行 Python 测试、应用、模型、检索、数据库、网络或服务。
