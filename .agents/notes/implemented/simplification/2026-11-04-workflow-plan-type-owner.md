# Agent Note: Workflow 计划步骤类型归属

Status: implemented

## Problem

`WorkflowState.plan` 只声明字符串列表，但现有 planner 写入包含 `id`、`description` 和 `dependencies` 的步骤字典。输入类型与实际输出不一致，调用方无法从共同状态定义理解结构化计划。

## Decision

`app.rag.workflows.base.WorkflowPlanStep` 是结构化计划步骤的类型所有者，与 `WorkflowState` 位于同一模块。`WorkflowState.plan` 接受原字符串列表、现有结构化步骤列表及原来的 `None`；planner 直接使用共同步骤类型描述其已有载荷。

状态键、`total=False`、运行载荷与依赖顺序保持现状。当前仓库没有其他 `WorkflowState` 引用，也没有使用它生成 LangGraph、Pydantic 或 API schema；这些记录沿用状态所有者的注解型 `typing.TypedDict`，不增加运行时校验。后续若引入验证边界，需按目标 Python／Pydantic 版本核对类型适配。

## Alternatives considered

- 把实际计划载荷改回字符串列表，能匹配原注解，但会丢失已有步骤 ID 和依赖信息，因此保留运行结构。
- 将步骤类型仅放在 planner 私有模块，能局部描述输出，但共同状态声明仍会遗漏有效形状，因此由既有状态模块统一持有。

## Consequences

旧字符串计划仍受支持，结构化计划由真实所有者表达。没有引入通用上下文、状态管理器或模型依赖；只拓宽注解以覆盖已有形状。Python 测试、应用与模型导入、图执行及外部服务不运行；本批通过 Ruff、Python 3.11 AST 和状态键／调用／载荷源码契约核对。
