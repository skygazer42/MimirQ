# 参考仓库：`prompt-engineering/langchain-langgraph-V1.0` → MimirQ 后端可迁移点

本文件用于记录 `F:\pythonproject\prompt-engineering\langchain-langgraph-V1.0` 中值得借鉴的 LangChain/LangGraph 设计点，并映射到 MimirQ 当前后端（知识库/RAG）可落地的优化方向与改造顺序。

> 约束：不引入“本地模型/本地 reranker”；与“统一记忆（LangGraph 实现）”相关的改造放在最后阶段（本轮仅做 scaffold）。

## 1) LangGraph 图建模（Graph API）

参考点（目录：`graph-api/`、`时间旅行/`）：
- `MessagesState`/`add_messages`：用 reducer 管理 `messages` 列表追加，减少手写 merge。
- `context_schema`/`Runtime.context`：把 request_id、user_role、provider 等“非业务状态”通过 runtime context 传递，避免污染 graph state。
- `RetryPolicy`：节点级重试策略（尤其是外部 API、LLM、DB）。
- `recursion_limit`：防止意外循环/递归（复杂路由/子图时很有用）。
- `private_state`/input/output schema：约束输入输出字段，减少 state 漫延。
- `time travel`：基于 checkpointer 的 `get_state_history` + `update_state`，用于回放/回归调试。

MimirQ 对应现状：
- 已有 LangGraph pipeline：`backend/app/rag/pipelines/langgraph.py`（Functional API + StateGraph 兼容入口）。
- 目前 graph state 以 TypedDict 为主，runtime context / retry / cache / checkpoint 管理仍偏“手工/自定义”。

本轮计划落地点：
- 引入 runtime context（request_id / conversation_id / tenant_id / account_id / user_role）。
- 将“图执行”升级为可真正流式输出（SSE）并支持 custom stream events。
- 落地 sqlite checkpointer（为后续 time-travel/debug、以及未来 memory 做底座）。

## 2) Functional API（@entrypoint / @task）

参考点（目录：`functional(workflow)_api/`）：
- `get_stream_writer()`：在 workflow 内部写出自定义流事件（例如“开始检索/检索完成/命中数”等）。
- `CachePolicy(ttl=...)`：task 级缓存（适合检索、轻量 query rewrite 等）。

MimirQ 对应现状：
- 已有 Functional API 入口 `rag_workflow`，但自定义流事件/缓存未系统化。

本轮计划落地点：
- 在 retrieve/generate task 内发送 custom events，并由 API 端映射成 SSE 事件类型（前端可直接消费）。
- 为检索 task 增加 TTL cache（默认关闭或 TTL 很短，避免文档更新带来的 stale）。

## 3) 结构化输出（Structured Output）

参考点（目录：`结构化输出/`）：
- 用 Pydantic/TypedDict/JSON Schema 明确 response schema。
- 统一错误处理策略（strict vs fallback）。

MimirQ 对应现状：
- 支持 `structured_output` + `structured_preset`（以“format instructions”字符串为主）；
- 解析与错误元信息有，但在不同路径（engine/graph）一致性还可增强。

本轮计划落地点：
- 统一 structured parse 元信息字段，并保证 graph/engine 路径返回一致。

## 4) 记忆（短期/长期）与中断（HITL）

参考点（目录：`短期记忆/`、`长期记忆/`、`langgraph中断/`）：
- SummarizationMiddleware / trim/delete messages：短期窗口与摘要压缩。
- store（向量检索）+ checkpointer（会话级状态）：长期记忆/跨会话个性化。
- interrupt/approve/reject：关键动作前的人审节点。

MimirQ 对应现状：
- 已有 `SHORT_TERM_MEMORY_*`、`LONG_TERM_MEMORY_*` 等配置与部分实现（chat 里有 BM25 long-term recall）。

本轮策略：
- 只做“memory node scaffold（默认关闭）”，不改变现有 long-term recall 行为；
- 真正的“统一记忆（LangGraph + store）”留到后续 #19 阶段再落地。

## 5) 本轮落地清单（对应计划 20 tasks）

核心输出将覆盖：
- 更严格的 `rag_config` 类型/校验（减少前后端联调歧义）
- LangGraph 真流式输出 + 自定义事件（检索/生成阶段可观测）
- SQLite checkpointer + checkpoint 调试接口（为 time-travel/回归准备）
- RAG 调试接口（retrieve/prompt preview）
- tracing span（可选开关，复用现有 LangSmith 集成）

## 6) 已落地（本次改造）

### 新增/更新接口
- `POST /api/v1/rag/retrieve-preview`：只跑检索，返回 `citations/metrics/query_for_retrieval`（便于调参）。
- `POST /api/v1/rag/prompt-preview`：跑检索 + 返回最终 prompt（不调用 LLM），包含 `prompt_messages/prompt_text/variables`。
- `GET /api/v1/chat/conversations/{conversation_id}/checkpoints`：列出 checkpoints（time-travel/debug）。
- `GET /api/v1/chat/conversations/{conversation_id}/checkpoints/{checkpoint_id}`：读取单个 checkpoint。
- `DELETE /api/v1/chat/conversations/{conversation_id}/checkpoints`：清理该会话 checkpoints。

### LangGraph 流式事件（SSE）
- `POST /api/v1/chat/stream` 在 `rag_config.use_graph=true` 时，会额外发送 `type="graph"` 的阶段事件：`retrieve_start/retrieve_done/generate_start/generate_done`。

### 关键配置项（env）
- `LANGGRAPH_RECURSION_LIMIT`：LangGraph recursion 上限（默认 25）。
- `RAG_GRAPH_CACHE_TTL_SEC`：检索 task 缓存 TTL（默认 0 关闭）。
- `CHECKPOINT_BACKEND` / `CHECKPOINT_SQLITE_PATH`：checkpointer 选择与存储位置。
- `LANGSMITH_TRACING_ENABLED` / `LANGSMITH_API_KEY`：开启 LangSmith spans（默认关闭）。
- `LANGGRAPH_STORE_ENABLED` / `LANGGRAPH_STORE_BACKEND`：LangGraph store scaffold（默认关闭，后续用于统一记忆）。
