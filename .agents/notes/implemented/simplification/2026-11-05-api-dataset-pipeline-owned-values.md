# Agent Note: 数据集与管线 API 消费实际生产者

Status: implemented

## Problem

数据集、扫描、解析、入库和运维 API 的部分消费者把当前 ORM 查询和本地构造的结果重新当作未知对象探测。固定内部记录仍用宽泛字典或 object 表达，清理预览也重复转换同一调用链已产生的计数，使真实校验边界难以辨认。

## Decision

API 直接读取实际 Dataset、Document、扫描运行、IngestionRun、入库响应、治理配置、回归运行和 IndexDriftItem 的声明字段。读取依据包括真实查询、关系和返回构造；原始 JSON 的 isinstance、可空值、or 默认、复制和 int／float／str／bool 转换保留。

血缘依赖与中心性结果用同模块 TypedDict 表达既有固定键。中心性排序直接消费其本地字符串和浮点分数，原权重解析、零权重回退、迭代算式、舍入及排序次序保持。内建 len 与 re.Match 偏移直接传递；解析质量读取当前 scorer 实际构造的 TextQualityScore，原始 bool／NaN 转换仍归既有解析函数。

分块血缘服务要求显式提供权限列表和使用统计：API 的 _ChunkLineageDependencies 和服务查询入口都已生成这两个字段。权限哈希 helper 直接迭代实际列表，使用统计仍复制后写入响应；答复血缘的可选 enrichment 与原始 trace／metadata 解析继续保留。命中排序直接读取同模块 _chunk_hit_payload 生成的整数时间戳和 enumerate 索引，真实可空 request_id 的原排序处理不变。租户、ACL、权限哈希／排序及未找到时的响应保持。

入库运行创建要求显式提供 config 字典与 expected_documents 整数，四个上传／批量／重放调用点已经给出这些值，创建入口直接复制配置并写入原非负上限。两个运行结束分支共用 _finished_run_metrics，只在状态与 finished_at 写入后生成可选耗时；开始时间缺失或时区不兼容时仍省略耗时。结束元数据仍由原调用者在提交后用于指标上报，不提前触发资源操作。

关闭 intake 时的状态字典已经由 _normalize_status 构造为非空字符串，直接用 Counter 汇总后转回原字典输出，不再为单次内部调用维护可空列表 helper。原始 stats／config／doc_meta 的解析、文档去重、行锁、完成目标、回滚与 best_effort／required 错误政策保持。
清理预览使用真实 CleaningResult 和诊断结果；其计数仍在三个原有清理 helper 中转换，下游不再重复转换。前处理预览仅直接读取 PreprocessStepLog 的三个声明字段，继续保留五字段摘要、动态 effective 选项和原默认策略。配额四个端点的返回注解与既有显式 response_model 和实际构造器一致。

用量 API 直接读取配额服务在全部返回路径中给出的固定字段。聊天 token 配额复用现有六字段 ChatAssistantTokenQuota，并把完整结果交给原 Pydantic 响应模型；文档、存储与 embedding 状态按业务顺序获取并组装各自模型，不重新用 get、bool、int 或默认值隐藏字段缺失。QPS 配置直接展开到原响应模型。配额禁用时的文档／存储／embedding 零值展示、服务端故障策略、模式和时间窗口归一化继续由原规则决定，聊天 token 配额的生产者仅删除无读取用途的 used 初值。

两条统计查询继续在读取 SQL 聚合结果时保留原始数值转换和可空 dataset_id。循环先构造现有 Pydantic 行，再用明确字段累加总量，替代 m／p／c／t 等中间缩写。浮点费用仍逐行按原顺序相加，不切换到不同求和算法；查询、分组、排序、时间范围及响应模型不变。

能力探测的动态设置名、插件兼容字段、parser／SDK 原始字典和请求构造不满足相同的封闭生产者条件，继续按原边界处理。设置仍可变，因此声明字段的读取继续保留原数值转换和默认值。手工 UUID 校验保留原有 400／404，所有权限、事务、队列、SSE 事件及资源清理保持。

## Alternatives considered

统一删除所有 getattr 和数值转换能得到更短的 API，但会跨越原始请求、可变配置和外部解析结果的真实边界。本轮只清理经过生产者核对的内部消费，不统一未知值的失败策略。

为全部结果新增模型和通用 Context 可以把更多值约束在类型里，但会增加新的层次和迁移职责。现有 ORM、dataclass、响应模型及两个局部 TypedDict 已能表达当前消费者的契约。

## Consequences

内部对象的归属和实际返回类型更明确，原始值的校验继续位于现有边界。直接读取依赖当前真实生产者；将来引入其他对象、动态扩展字段或绕过模型构造时必须重新核对，不能把这项决定扩展到未知数据。

验证只涵盖完整源码与实际生产者／调用者、Ruff、格式、Python 3.11 AST 和固定范围静态契约比较。不添加、修改或运行 Python 测试，不执行应用、SDK、模型、数组、图像、OCR、数据库、服务、网络、配置正则或业务 CLI。

配额与统计的源码证据位于 E:/MimirQ/.superpowers/quota-usage-readability-20261106/。核对响应模型与路由声明、管理员检查、SQL 查询、生产者三个返回分支的完整六字段、两种行模型的原始输入转换及有序累计。配额数值映射按真实生产者的 enabled／limit／exceeded 约束审阅；静态证据不替代真实请求和数据库验收。

分块血缘增量的源码证据位于 E:/MimirQ/.superpowers/extraction-lineage-inputs-20261107/。完整模块 AST 只允许已供给参数和本地命中整数取值变化，两个真实服务调用点都明确提供权限和统计。原 API、授权、外部 trace 与测试源码保持；Ruff、格式和语法检查不构成真实权限集成验收，Python 测试不运行。

入库清单增量的证据位于 E:/MimirQ/.superpowers/ingestion-manifest-input-contracts-20261107/。完整模块 AST 对照限定创建契约、相同耗时策略复用及已归一化计数；四个创建调用点、原模型、上传与重放入口、指标所有者和并发测试源码保持。静态检查不执行数据库、锁、指标或 Python 测试；已知 autoreview 仍因本机缺少 TruffleHog 无法进入模型审查。

活跃笔记检索中的[会话与检索 API](2026-11-05-api-session-retrieval-owned-values.md)和[预览数据校验归属](2026-11-05-preview-owned-values.md)部分重叠，继续分别持有原范围的决定，本记录只覆盖剩余 API 消费者。[完整数据集默认范围](../bug-fix/2026-11-03-dataset-default-complete-scope.md)与[融合参数校验](2026-11-03-dataset-fusion-map-validation-owner.md)属于相邻权限及 schema 决定，保持原归属。同步 Golden 导入的修复记录在[对应笔记](../bug-fix/2026-11-05-pipeline-golden-sync-import.md)。
