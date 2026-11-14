# Agent Note: Embedding主结果与批次任务有明确所有者

Status: implemented

## Problem

缓存写入器在创建Redis pipeline之后才把已算向量填入out。pipeline创建失败会被原可选缓存边界捕获，主结果槽却仍为空，最终被空向量替代。

batch gather首个失败后可以让兄弟任务继续运行，finally却已删除embed_state；晚到任务写进度触发KeyError。两个实际shadow调用方没有传已有空间指纹，adapter默认取主模型配置，可能把相同文本的不同模型向量视为同一缓存身份。

## Decision

先按原zip顺序把computed向量写入out，再进入现有缓存pipeline／payload／execute旁路。命中、TTL、失效和可观测日志保持；缓存失败不能改写已计算的主结果。

abatch_encode显式持有按原输入顺序创建的Task。失败或取消后只取消尚未进入取消流程的owned任务，等待它们结束清理，再删除状态，原异常或CancelledError继续传播。部分创建失败关闭未提交的coroutine。只有原来的Exception失败分支标记failed，不引入ExceptionGroup、新timeout、shield或重试。

shadow迁移和向量writer把实际已有shadow_space_hash传给adapter。writer先计算纯指纹，再按原embedding→Milvus顺序构造资源；三种失败保原warning和sig→None缓存政策。指纹算法、provider别名、URL规范化、长度、密钥排除规则与数据集runtime的显式指纹保持。

两个调用方是既有pending文件的必要局部修复，分别绑定首写前原文和SHA，不把它们算作全文完成。migration原有or链格式差异保留并单列，不宣称17文件格式全部通过。[既有归一化与空间指纹](../simplification/2026-11-04-embedding-rules-owner.md)继续持有实际规则。

## Alternatives considered

- 给缓存创建再加默认pipeline或重试可以绕过异常，但会掩盖旁路与主结果的错误顺序，因此先交付主结果。
- 只在finally pop之前判断key存在可以少见KeyError，但兄弟任务仍脱离拥有者；等待任务收尾才能修真实原因。
- 改用TaskGroup能自动管理兄弟任务，但会改变异常组包装；在既有asyncio边界保原异常身份。
- 把shadow默认全局指纹改为另一个猜测规则会影响其他正常调用方；两处实际配置已有指纹，直接传入。

## Consequences

Redis故障不再抹掉计算成功的向量，失败／取消不遗留仍写已清状态的协程，不同模型的shadow缓存身份分开。取消协程Task不等于强制停止SDK在线程池里的阻塞函数，未作该承诺。

原失败与修后使用有限FakeRedis／provider／受控async任务核对，独立复核覆盖乱序完成、失败／取消／部分创建、状态删除时点、同异常对象、hash与资源顺序。没有真实Embedding、Redis、HTTP、NumPy、SDK、线程或应用测试，不能据此证明真实供应商、向量质量或并发运行通过。
