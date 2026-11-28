# Agent Note: Query preparation ownership

Status: implemented

## Problem

The synchronous retrieval orchestrator parsed rewrite, sparse, industry-rule and temporal options and executed those stages inline. Query option parsing also mixed request fields with runtime objects, while the typed query preparation owner had no production caller.

## Decision

`_build_retrieval_request` selects only keys in `QUERY_PLANNING_OPTION_KEYS`, converts numeric rewrite overrides, validates the expansion budget and builds the typed request. The synchronous bootstrap calls `prepare_query_plan` once with engine-backed model ports. Ordered retrieval phases read query preparation, routing and expansion results from that plan; retrieval execution builds its plan directly from `QueryPlan.queries` instead of copying the list into mutable runtime state. Other runtime fields remain output projections for trace and result compatibility.

The request adapter rejects malformed numeric rewrite and budget values before model execution. Valid inputs continue to use the configured defaults and strategy limits. `RetrievalRuntimeState` and `RetrievalTraceStageInput` type the plan as `QueryPlan`; accessing it before bootstrap raises the existing state-order error.

`QueryVariantStageInput` carries optional int/float budget fields. Missing values retain the zero/unbounded contract; the variant stage trusts this typed boundary instead of converting malformed values into an unlimited budget.

Retrieval config snapshot normalization treats malformed optional template versions as absent only for standard integer conversion failures.

## Alternatives considered

- Keep flattened runtime fields as the authoritative query state: this minimizes each individual phase change, but allows phases to disagree about the prepared query and expansion results; not selected.
- Change every phase contract in the original extraction: it would remove the projections sooner, but make that initial ownership migration much harder to review; the migration was completed in separate batches.

## Consequences

Query preparation, routing and query expansion have one typed owner. The orchestrator retains request conversion and output mapping for trace/result fields, while retrieval behavior reads the plan directly without duplicating its query list. For malformed internal numeric overrides, failure occurs at request construction instead of silently substituting zero.

[检索编排内部记录](../simplification/2026-11-05-retrieval-orchestration-owned-values.md)保留本篇查询计划与运行阶段顺序，只收窄已构造记录和声明字段的访问，注入回调继续保留原始值解析。

[Engine 查询与模型端口](../simplification/2026-11-05-engine-ports-owned-values.md)保留本篇实际准备端口、同步/异步调用及旧参数解析边界，只清理已构造值和声明字段的访问。

[标准流诊断投影](../bug-fix/2026-11-05-standard-stream-plan-projections.md)修复 pending stream caller 的旧字段读取与遗漏的 step-back 配置投影，继续以本篇查询计划为唯一生产者，保留事件键和阶段顺序。

## Verification

- Ruff check and format checks pass for the modified retrieval modules.
- `py_compile` and import smoke checks pass for the three modified retrieval modules.
- All three agent-note tree, format and archive verifiers pass.
- Python tests were not run per user instruction.
- Ruff check and format checks pass for the query contract normalizer; Python tests were not run.
