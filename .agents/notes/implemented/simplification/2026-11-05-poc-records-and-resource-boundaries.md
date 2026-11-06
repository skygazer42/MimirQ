# Agent Note: POC 内部记录与资源边界分别归属

Status: implemented

## Problem

POC 的 attribution、heatmap、延迟和 scatter 记录已经由本地构造保证字段，后续仍按 raw 字典重复读取与转换。日期解析在三个本来相互依赖的模块中维护相同实现，PNG task 的实际 Redis 资源却用 Any 表达。

## Decision

六份固定内部记录使用原模块内 TypedDict，运行时仍为原字典。只有构造完成的 example、Counter、round 无 ndigits 的整数结果、已解析浮点和 scatter 字段直接消费；原始 JSON／ORM／Pydantic、SDK／NumPy 坐标、confidence、threshold 和 bytes 输入继续在原边界转换。

telemetry 保留三份完全相同日期转换的 canonical 实现。source_builder 和 attribution 直接从本来已依赖的模块导入同名函数，保留 UTC、ISO、None、异常和调用时点。映射转换中的日志依赖各自模块 __name__，因此保留其原实现；默认长度不同的字符串转换也不合并。

query tokenizer 保留原正则，其两个无捕获分支的最小宽度均为 1，只退出非空过滤。regex 没有在验证中编译或执行。UMAP／SVD 的加载、seed、fallback、dtype 与坐标 float 转换保持；HTML 和 PNG 的原画布、文本、颜色、顺序和 SDK 调用保持。

PNG task 仅标明实际 LazyRedisClient.get 取得的 Redis 类型，TYPE_CHECKING 不提前加载 SDK；声明 Settings 字段直接读取并保留原值转换。锁、全局 slot、CAS Lua、租约／所有者／账号／tenant、TTL、四次尝试、raw JSON codec、time／UUID 调用和 bytes 副本保持。已核定的[零负反馈分母](../bug-fix/2026-11-05-png-heatmap-zero-negative-scale.md)属于独立 bugfix，不计入等价 style 对照。

## Alternatives considered

把记录改成对象或增加 Context 可以减少下标表达式，但会改变既有字典／JSON 与回调协议，所以使用 TypedDict。把所有时间、映射和字符串清理一起集中更短，却会改变日志归属或默认值，因此只复用相同且已经具有依赖关系的日期规则。

把任务改为本地缓存或统一重试包装可以压缩函数数目，但会破坏 Redis 共享状态、CAS 和租约责任，本组保留这些真实资源操作。

## Consequences

内部字段与资源来源更直接，公开参数、返回形状和现有失败策略保持。完整 103 个原函数由 101 个保留体和两份 canonical 日期 body 覆盖；14 条任务资源流程和四个关键 body 额外保持精确 AST。没有运行 renderer、PIL、NumPy、sklearn、UMAP、Redis、DB、数据集、regex、CLI、callbacks 或 Python 测试。

笔记按 POC、日期解析、PNG 与 scatter 检索；当前独立分母记录部分相关并保留，服务负责人确认共享任务与 payload 决定保持其原归属。本篇不改服务定义或既有冻结引用，也不新增 Manager、微模块、兼容 wrapper 或依赖。
