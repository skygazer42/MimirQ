# Agent Note: 数据集与管线 API 消费实际生产者

Status: implemented

## Problem

数据集、扫描、解析、入库和运维 API 的部分消费者把当前 ORM 查询和本地构造的结果重新当作未知对象探测。固定内部记录仍用宽泛字典或 object 表达，清理预览也重复转换同一调用链已产生的计数，使真实校验边界难以辨认。

## Decision

API 直接读取实际 Dataset、Document、扫描运行、IngestionRun、入库响应、治理配置、回归运行和 IndexDriftItem 的声明字段。读取依据包括真实查询、关系和返回构造；原始 JSON 的 isinstance、可空值、or 默认、复制和 int／float／str／bool 转换保留。

血缘依赖与中心性结果用同模块 TypedDict 表达既有固定键。中心性排序直接消费其本地字符串和浮点分数，原权重解析、零权重回退、迭代算式、舍入及排序次序保持。内建 len 与 re.Match 偏移直接传递；解析质量读取当前 scorer 实际构造的 TextQualityScore，原始 bool／NaN 转换仍归既有解析函数。

清理预览使用真实 CleaningResult 和诊断结果；其计数仍在三个原有清理 helper 中转换，下游不再重复转换。前处理预览仅直接读取 PreprocessStepLog 的三个声明字段，继续保留五字段摘要、动态 effective 选项和原默认策略。配额四个端点的返回注解与既有显式 response_model 和实际构造器一致。

能力探测的动态设置名、插件兼容字段、parser／SDK 原始字典和请求构造不满足相同的封闭生产者条件，继续按原边界处理。设置仍可变，因此声明字段的读取继续保留原数值转换和默认值。手工 UUID 校验保留原有 400／404，所有权限、事务、队列、SSE 事件及资源清理保持。

## Alternatives considered

统一删除所有 getattr 和数值转换能得到更短的 API，但会跨越原始请求、可变配置和外部解析结果的真实边界。本轮只清理经过生产者核对的内部消费，不统一未知值的失败策略。

为全部结果新增模型和通用 Context 可以把更多值约束在类型里，但会增加新的层次和迁移职责。现有 ORM、dataclass、响应模型及两个局部 TypedDict 已能表达当前消费者的契约。

## Consequences

内部对象的归属和实际返回类型更明确，原始值的校验继续位于现有边界。直接读取依赖当前真实生产者；将来引入其他对象、动态扩展字段或绕过模型构造时必须重新核对，不能把这项决定扩展到未知数据。

验证只涵盖完整源码与实际生产者／调用者、Ruff、格式、Python 3.11 AST 和固定范围静态契约比较。不添加、修改或运行 Python 测试，不执行应用、SDK、模型、数组、图像、OCR、数据库、服务、网络、配置正则或业务 CLI。

活跃笔记检索中的[会话与检索 API](2026-11-05-api-session-retrieval-owned-values.md)和[预览数据校验归属](2026-11-05-preview-owned-values.md)部分重叠，继续分别持有原范围的决定，本记录只覆盖剩余 API 消费者。[完整数据集默认范围](../bug-fix/2026-11-03-dataset-default-complete-scope.md)与[融合参数校验](2026-11-03-dataset-fusion-map-validation-owner.md)属于相邻权限及 schema 决定，保持原归属。同步 Golden 导入的修复记录在[对应笔记](../bug-fix/2026-11-05-pipeline-golden-sync-import.md)。
