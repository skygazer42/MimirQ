# Agent Note: 评测质量规则使用实际内部类型

Status: implemented

## Problem

质量场景和校准计算重复转换已经构造好的本地计数、布尔值、浮点拟合块与规范化 trace rank。dict／Pydantic 的相同原始边界还在 multihop 与 regression sample 两处维护。

## Decision

拟合块、claim 计数和规范化 trace row 使用原模块内 TypedDict，运行时对象形状不变。只消费实际 float／len／enumerate／整数累加和已解析结果生成的值；PlattScaler、IsotonicCalibrator 仍是实际拟合模型，公开 predict 输入的模型字段和 score 转换保持。

Guard 仍使用原资源对象、构造和 await 顺序。RegexSafetyGuardResult、LLMGuardResult 和 OutputGuardResult 由实际 callee 构造，直接读取其声明字段，保留原 or 默认、字符串清理、None 列表与 action 判断。所有 regex、阈值、公式、算术顺序、NaN／inf、整数转浮点分母和舍入保持。

multihop 的既有 _coerce_dict 持有两份完全相同的边界规则。regression sample 原来已导入该模块，现在直接导入同名函数并退出自己的重复实现；原 None、model_dump、dict copy 和异常政策保持，不增加包装或新模块。regression_sample_builder 这里只记录必要 partial 增量，后续模型评测类别才完成其完整 owner closure。

原始 JSONL、raw score、record stats 与 public payload 的解析仍在原边界。已授权的[每 query 加载上限](../bug-fix/2026-11-05-hard-negative-per-query-load-cap.md)保留为独立 bugfix；style 对照以包含该修复的冻结前序为基础，不把行为修复写成等价清理。

## Alternatives considered

把所有标量转换统一到一个通用 helper 可以减少重复，但这些入口对 bool、NaN、异常和默认值有真实差异，因此只处理已保证的本地值。把规范化 trace 与 raw JSONL row 当成同一种类型更省注解，却会丢掉文件输入校验，所以只给构造完成的 trace row 明确字段。

新建 common／Context 模块可以集中规则，但现有 multihop 已提供完全相同的轻量函数，regression sample 本来也依赖它，因此只直接复用既有所有者。

## Consequences

内部计数和数据来源更清楚，真实输入解析、资源、API、排序、预算与失败政策保持。验证覆盖 84 个完整函数 AST、两个拟合模型、公开参数和静态绑定，以及 partial consumer 的整个模块 AST；没有运行业务、模型、SDK、DB、数据、regex、CLI、callbacks 或 Python 测试。

已有[批处理记录](2026-11-05-evaluation-batch-native-records.md)和[已接受的评测协议记录](2026-11-05-evaluation-contract-native-values.md)分别拥有其他文件范围；本篇沿用实际生产者原则，不改它们的决定或重复计数。原始映射规则的直接复用不替代 regression sample 的引用匹配和指标政策。
