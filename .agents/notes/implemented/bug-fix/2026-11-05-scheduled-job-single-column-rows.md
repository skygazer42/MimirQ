# Agent Note: 定时任务按单列 Row 发现租户和数据集

Status: implemented

## Problem

stale report 和 DB maintenance 的 all-tenants 路径从 Tenant.id 查询租户，nightly ablations 的 all-datasets 路径从 Dataset.id 查询数据集。三处消费者都只接收 Python tuple；真实 SQLAlchemy 单列查询返回可迭代的 Row，导致范围被清空。前两者可能输出空成功，后者误报 No datasets found。

## Decision

三处仅改为直接解包已知的一列并保留原 UUID 过滤。实际模型列、ORM column entity 的非 scalar 契约、Query.all 以及 Python／Cython BaseRow 的迭代定义均按源码核对，不导入或创建 SDK 对象。

保留原 SQL、租户条件、排序、上限、默认、dry-run／execute、结果字段、exit、事务和会话关闭。真实缺陷与后续等价风格整理分开提交；不扩展到未知 adapter 或 raw JSON。

## Alternatives considered

- 增加 Row 类型判断再保留 tuple 分支，需要把 SDK 表现写进消费者；固定的一列可以直接解包。
- 更换查询 API 或要求显式 ID 会扩大 SQL 或 CLI 契约变化，因此保持现有查询和调用链。

## Consequences

真实 UUID 可以进入原有有界任务链；非 UUID 仍跳过。查询未来若更改列数，必须同步修改明确的解包契约。

完整三个模块只允许指定三行文本／AST 投影，95 个原函数的参数、默认和装饰器保持；验证使用 Ruff 和静态源码分析。没有执行 CLI、SDK、DB、应用、业务函数或 Python 测试。

活跃笔记中的[周期审计决定](2026-11-05-periodic-audit-single-column-rows.md)记录另一个已接受的所有者；本篇沿用其单列约定，保留已有 periodic audit 修复，不替代或重计该决定。
