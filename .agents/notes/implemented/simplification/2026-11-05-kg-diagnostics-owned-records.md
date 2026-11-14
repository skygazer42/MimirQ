# Agent Note: KG 诊断内部记录与原始边界

Status: implemented

## Problem

KG 诊断重复转换已构造的指标、计数和布尔值，preflight 与线索计数仍以任意字典表示。确定性 hardcase 与原本已依赖的生成模块还各自维护同一份空白清理规则。

## Decision

preflight、提取错误与线索计数用原模块内 TypedDict 描述，运行时仍使用原字典。只有本地构造、整数累加、len／enumerate、浮点运算和实际 KGSearchRunMetrics 构造已经保证的值直接消费。preflight 的两个累加 key 和 errors 列表由唯一构造入口建立，不再为内部记录补造第二种形状。请求与 raw search、JSON、引用、UUID、score、错误和关系调试仍在原边界处理。

确定性 hardcase 直接使用既有 kg_hardcase_generator 的 _collapse_ws。两份完整函数和 regex 字面量相同，原模块已经依赖生成模块；不增加模块或 wrapper。诊断自己的同名函数保留 None 专用分支，不能把它与 falsey 值归空的 hardcase 规则合并。LLM 生成入口的 Any 仍表达真实结构兼容协议，保留 prompt、schema、预算、失败返回和 sanitize 规则，全文原文 conforms。

现有请求 Session、独立提取 Session、preflight semaphore／gather／rollback、LLM 工厂时点、调用内数据类与可注入搜索 callable 保持。所有查询、tenant／ACL、case／hardcase 顺序、上限、归因优先序与四位／六位舍入保持。本篇等价整理不改变指标公式；重复 chunk 的额外 DCG／AP 收益由后续[独立修复](../bug-fix/2026-11-14-kg-diagnostic-duplicate-gain.md)持有，原事件位置、检索范围与其余契约继续成立。

## Alternatives considered

统一三个空白清理函数可以减少更多代码，但诊断对 0 等 falsey 输入的保留规则不同，所以只共享完全相同的两个实现。把所有数字转换都删掉会更短，但原始输入、bool 到计数和整数到浮点分母仍是真实转换，只清理有实际生产者证据的内部值。

新增统一 Context 可以集中参数，却会掩盖真实 Session、诊断状态和搜索依赖，因此沿用既有记录和明确参数。

## Consequences

诊断内记录和数据来源更清楚，外部协议、资源、异常、预算与排名政策保持。完整模块 AST 投影验证覆盖 79 个原函数、一个完整相同规则的直接引用以及所有原类字段/default、导入时点和公开签名；静态调用绑定、Ruff、格式与笔记门禁另行核对。不运行业务函数、模型、SDK、DB、regex、数据、callback、renderer、CLI 或 Python 测试。

历史检索中的[KG 搜索归属](2026-11-05-kg-search-function-ownership.md)只持有前序搜索 callable 迁移，本篇完成诊断 owner 的完整审查；[评测质量](2026-11-05-evaluation-quality-native-rules.md)持有其他场景与 raw 映射规则，均保留原决定与计数范围，没有被本篇替代。
