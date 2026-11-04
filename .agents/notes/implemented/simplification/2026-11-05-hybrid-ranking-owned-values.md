# Agent Note: 混合检索排名的内部记录与输入边界

Status: implemented

## Problem

候选排名在 Settings、固定的融合配置字典和本地生成的元数据锚点之间重复转换标量。记录字段没有明确类型，阅读排序规则时需要反复追查 `.get()` 的默认值。请求内排名状态还通过一个只写字典的私有方法转发四处指标赋值。

## Decision

融合配置、元数据锚点和短语匹配结果使用对应字段的 TypedDict，运行时继续返回原字典。Settings 字段直接读取；本地记录、计数器和已经完成转换的分数直接参与原有计算。请求内 `_RankingRun` 直接更新自己的指标字典，保留独立的请求状态和全部框架、缓存及领域对象。

元数据锚点仍按原长度、分数、字段顺序过滤与排序，保留字段去重、聚合系数、截断和公开结果字段。混合候选和 orchestration 两条入口复用 `metadata_anchor_ranking.py` 的同一聚合函数；两者原始元数据遍历与 Unicode 失败规则不同，仍分别保留在入口。新所有者只依赖标准库，避免 orchestration 通过 hybrid common 进入已有的 preprocessing 包初始化。融合渠道顺序、归一化公式、RRF 与预算前缀、浮点运算顺序、权重指纹、MMR、排序并列规则和重排加分上限保持原样。

`HybridSearchOptions` 的旧参数入口允许直接使用 overrides 构造 dataclass，因此相关输入转换继续保留。原始 provider 分数、插件策略、元数据、ID 和预算字典仍在原边界校验；类型注解不替代这些校验。重排工厂的调用位置、禁用别名、失败降级、异常记录和事件顺序保持。

## Alternatives considered

把运行配置和返回结果全部换成 dataclass 可以通过属性访问表达字段，但需要迁移当前字典协议。本改动选择 TypedDict，在表达固定字段的同时保留对象形状。把两条元数据入口整体合并可以删掉更多代码，但会改变元数据视图和异常处理；只收敛构造完成后的重复聚合。把聚合留在 hybrid common 可以少一个模块，但会让 orchestration 新进入 preprocessing 的初始化链，因此采用只依赖标准库的叶子模块。统一删除数值转换可以进一步缩短代码，但旧参数、provider 和元数据仍有实际解析职责，所以仅移除生产者已经保证的内部转换。

## Consequences

内部数据来源和排序依据更直接，调用者继续使用原参数、字典、顺序与失败策略。验证使用源码、生产者和调用约定、完整限定的 AST 对照与 Ruff；Python 测试、检索、模型、数据库、网络和服务运行时未执行。

本次笔记检索中，[共享标量转换](2026-11-03-shared-scalar-coercion-owner.md) 与原始数值边界部分重叠，沿用其边界原则；本模块 `_float_or_default` 仅捕获 TypeError/ValueError 的既有区别保留。[重排 provider 回退](../bug-fix/2026-11-03-reranker-provider-fallback-boundary.md) 与工厂错误政策部分重叠，沿用其结论。KG 查询扩展所有者属于另一条查询构造链，与本次内部排名记录无关；这些决定均未被替代。
