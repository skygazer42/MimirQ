# Agent Note: 安全、反馈与行业规则的内部值

Status: implemented

## Problem

安全匹配表、反馈候选返回值和行业规则建议在本地完成构造后，仍重复转换计数、分数或探测已有类型。阅读代码时，这些内部处理与实际的安全规则、原始反馈、YAML 和元数据边界混在一起。

## Decision

安全匹配表在每次写入时继续对传入分数执行 `float(score)`，已有表值直接参与原来的 max 计算。规则匹配参数标注实际的 `GuardRule`。OutputGuard 读取本地 RegexSafetyGuard 构造结果的 action 字段，保留原字符串转换和值回退。规则、阈值、最高三项求和、决策、异步线程调度、单例和日志顺序保持。

结果分数继续转换：`min(1.0, sum(empty))` 的空匹配路径可能产生整数 0，dataclass 注解不保证运行时值已经是浮点数。只清理实际生产者已经归一化的内部值，不按注解删除原始数值解析。

反馈 dispatcher 的直接行分支和 FeedbackService 的空行、非空行分支都调用同一候选字典构造器，因此返回时直接使用该字典。原始行反射、rating、JSON extra、引文、trace、miner 返回、lineage 和负例 payload 仍在原边界校验与复制。rating 的两次既有读取和 max_rating 解析顺序保持，JSONL 的 dry-run、append、目录创建、逐行写入和排序不变。

行业建议仅直接排序本地已经转换为整数、字符串的字段，Counter 和 `len` 直接提供计数。运行元数据直接使用本地归一化布尔值。原始 glossary、patterns、intents、名称、限额与错误仍按原规则处理。YAML 安全加载、路径约束、进程与文件锁、临时文件、权限、flush/fsync、原子替换和 canonical/generated 优先级保持。

Settings 的五个声明字段直接读取，保留数值、布尔、字符串转换和原默认值。集合接口类型从 `collections.abc` 导入；规则与领域结果类保留实际角色，不增加管理器、Context、转发器或新模块。

## Alternatives considered

依据结果类的字段注解统一删除数值转换可以进一步缩短代码，但空匹配、旧参数和原始反馈仍有实际类型与值边界，因此只清理有明确生产者证据的表值、计数和记录字段。

保留 dispatcher 的类型回退可以接收任意返回对象，但实际两个入口及服务的两个 return 分支都回到同一字典构造器。保留原始候选入口的校验即可，内部返回不再假设另一个未声明协议。

## Consequences

内部值来源更清楚，安全、召回、反馈导出和行业规则的内容及写入政策保持。若以后替换候选生产者或 guard 结果协议，需要重新审视字段保证，不能把这些内部保证应用到外部模型、插件或 YAML。

历史审计中，[共享标量转换](2026-11-03-shared-scalar-coercion-owner.md)与归一化边界原则部分重叠，双方互链；本批保留各原始输入入口既有的异常范围。命中的[算法设置操作归属](../bug-fix/2026-11-05-algorithm-settings-operation-contracts.md)持有前端草稿、请求与行业规则 API 操作规则，本批不改变该决定。其他前端和 parser 笔记属于不同链路，没有被替代。

[插件合同与内部结果](2026-11-05-plugin-contract-owned-results.md)沿用同一原始值边界原则，保留插件加载、执行与 provenance 契约，收敛同文件中的等价校验和已构造结果。

## Verification

16 个所有者的 1,477 行基线、75 个函数完整审阅。静态核对 GuardRule 与 RegexSafetyGuardResult 的实际构造、匹配表写入、候选服务的两个 return 分支、建议记录字段、写入与锁上下文、规则表达式、参数、导出和异常入口；Ruff、格式、Python 3.11 AST、diff 与笔记门禁覆盖本批。按任务限制不添加、修改或运行 Python 测试，不导入或执行应用、SDK、插件、安全扫描器、模型、网络、数据库、服务、fixture、YAML 或配置中的 regex。
