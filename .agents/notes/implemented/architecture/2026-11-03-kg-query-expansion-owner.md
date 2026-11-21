# Agent Note: KG query expansion ownership

Status: implemented

## Problem

`_run_retrieval_kg_query_expansion_phase` assembled the tenant/document/dataset scope, called KG search, filtered and ranked entities, and built query variants inline. The existing KG expansion module was not used by production retrieval, so its sync/async behavior and stricter response contract did not govern the actual phase.

## Decision

The orchestrator builds a typed `KGQueryRequest` from the current retrieval scope and resolved expansion settings. `app.rag.retrieval.orchestration.kg_query_expansion` owns KG search, entity validation, filtering, ranking and expanded query construction. The phase copies the typed outcome into the existing diagnostics fields and raises only rejected top-level response contracts through `raise_for_rejected_response`.

The separate KG chunk-injection sync bridge returns the pipeline result directly. It does not convert a non-object response to `{}`, so a broken result cannot masquerade as an empty KG search.

The existing `_run_kg_search_sync` bridge remains for the separate KG chunk-injection path, which fetches candidate documents rather than query variants. This is separate from model-based query expansion.

KGQueryScope 由真实计划构造器用两个原生 tuple 创建，且记录冻结。搜索适配器直接按范围是否为空选择列表副本或 None，去掉两处只用于条件表达式的赋值绑定；空范围仍是未指定，参数顺序和服务端范围／鉴权政策保持。

同步与异步 KG 扩展的全部返回路径用零值或 len 生成计数、用计时器差值生成耗时，used 属性返回原生 bool。指标和 trace 直接传递这些值，查询列表仍创建副本，小数精度保持。enabled 继续来自可变配置及原始覆盖，因此保留其布尔转换；原始服务响应和实体内容仍在现有边界校验。

## Alternatives considered

- Keep KG search and entity processing in the orchestrator: it avoids adapting the current phase, but leaves scope and entity policy duplicated and bypasses the tested sync/async owner; not selected.
- Route chunk injection through the query-expansion owner: it would provide one KG entry point, but query expansion returns text variants while injection needs scoped document candidates; not selected.

## Consequences

The KG query phase and native async expansion now share one scope and entity policy. A non-object KG response becomes an explicit contract error; malformed entities and optional service failures remain in `kg_query_expansion_error` and produce no expansion queries. The separate chunk-injection sync bridge remains until that operation receives its own owner.

## Verification

- `ruff check .` passes.
- `ruff format --check app/rag/retrieval/orchestrator.py` passes.
- `py_compile` passes for `app/rag/retrieval/orchestrator.py`.
- Import smoke check for `app.rag.retrieval.orchestrator` passes.
- Python tests were not run per user instruction.
- The KG sync bridge contract was statically checked against `KGEngine.search` and `pipeline.kg_search`; Python tests were not run.

本次范围与原生结果增量的证据位于 `E:/MimirQ/.superpowers/kg-query-scope-output-contracts-20261107/`，记录冻结 tuple 的实际构造、六条扩展返回路径、唯一结果写入、完整当前／提交 AST 和 23 阶段顺序。Ruff、格式、Python 3.11 与笔记门禁提供静态证据；本增量未运行或修改 Python 测试，未执行导入 smoke、KG、SDK、模型、检索、数据库或服务。上方历史验证记录不作为本增量的运行时证据。
