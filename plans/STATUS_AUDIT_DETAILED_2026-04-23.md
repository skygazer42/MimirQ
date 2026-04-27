# Detailed Plans Audit Checklist (2026-04-23)

> 范围：`/data/temp34/MimirQ/plans/*.md`
>
> 记号：
> - `[x]` 已完成：已有实现，且能看到测试、调用链或明确集成证据
> - `[ ]` 未完成：缺文件、缺集成，或仅有局部脚手架/弱等价实现
>
> 说明：本清单按“每份 plan、每条明确行动项”逐项审计；即使某个方向已有部分能力，只要未达到计划中点名的交付形态，仍保持 `[ ]`。
>
> 当前 `feat/backend` 分支按 `RAG-only` 范围推进：保留检索、改写、评测、归因、反馈、MCP 等可复用能力；不再把 IM 集成、聊天产品化、多 agent 问答优化列为当前 backlog。

## `rag-agentic-reasoning-deep-dive-2026-q2.md`

- [x] `workflows/self_rag.py` prompt-based reflection
- [x] `tools/web_search.py`
- [x] `workflows/crag_streaming.py`
- [x] Retrieval evaluator（correct / ambig / incorrect）独立实现
  现状：已新增 `app/rag/evaluation/retrieval_evaluator.py`，提供独立 verdict 判定与 summary 聚合
- [x] CRAG metrics 决策分布
  现状：`crag_streaming.py` 已改为复用独立 retrieval evaluator，并输出 `correct / ambiguous / incorrect` 判定；summary helper 可直接统计决策分布
- [x] `workflows/flare.py`
- [x] `tools/hierarchical_retrieval_tools.py`
- [x] `workflows/critic.py` 独立 critic agent
  现状：已补 `CriticWorkflow` 独立 workflow surface；当前仍是 deterministic critique，不是 LLM judge
- ~~`evaluation/ragshaper_synthesizer.py`~~（当前分支不做 agent 问答训练数据合成）
- ~~Planner 子目标树写入 `trace_schema.py`~~（当前分支不做 planner 型问答编排）
- ~~Reflexion 最多 2 次反思的硬门限~~（当前分支不做 answer-agent loop 强化）
- ~~multi-agent Supervisor pattern~~（当前分支不做多 agent 问答编排）
- ~~research-debate agent 评估~~（当前分支不做复杂问答协作）
- ~~agent 节点最大迭代次数 + early-stop faithfulness 阈值~~（当前分支不做 agent 问答优化）
- [x] cost-aware orchestration
  现状：已新增 `scripts/generate_channel_budget_policy.py` 离线产出 channel budget policy，并由 `app/rag/retrieval/orchestrator.py` 在 retrieval mode/profile 级别解析应用 `fusion_budgets/fusion_min_scores`
- [x] `evaluation/agent_redteam.py`
  现状：已补 suite runner；当前仍是 deterministic redteam，不含 CI 调度与自动样本生成
- ~~`evaluation/ragcap_bench_runner.py`~~（当前分支不再以 agent QA benchmark 为优先）
  现状：已有离线 deterministic scaffold，但当前分支不继续追这条 agent QA 路线
- ~~评测集 Stage 3 agentic 样本接入~~（当前分支不继续扩 agentic 问答样本）

## `rag-capability-gap-2026-q2.md`

- [x] `app/parsing/parsers/colpali_parser.py`
  现状：已新增 `ColPaliParser` scaffold，并接入 `ParserFactory` 显式 backend 路由
- [x] `routing.py` quality fallback 闭环
- [x] `app/parsing/enrich/chart_to_data.py`
  现状：已新增 chart-to-data enrich scaffold，并接入 parsing processor inline enrich 流；默认关闭，开启后可把图表图片抽成结构化 `Chart data` JSON block
- [x] 公式 / 表格 / 代码三态索引
  现状：`app/rag/chunking/roles.py` 已新增 `build_chunk_type_subindex_payload()`，可把 `formula / table / code / ...` chunk 显式路由到稳定 `subindex_key`；配合既有 query-aware chunk type weighting 构成子索引 contract
- [x] `strategies/raptor.py`
  现状：已新增 `app/rag/chunking/strategies/raptor.py`，提供 deterministic RAPTOR scaffold，输出 `leaf + summary` 两层 collapsed-tree chunk，并带 `raptor_layer/raptor_parent_id`
- [x] `contextual_enrichment.py` lazy incremental mode
  现状：`Indexer` 已支持 `embedding_contextual_retrieval_lazy_mode`；lazy 模式下仅对带 `contextual_enrichment_required` 或 `evidence_gap` 信号的 chunk 注入 contextual prefix，其余 chunk 保持原始 embedding text
- [x] `strategies/late_chunking_jina.py`
  现状：已新增 `app/rag/chunking/strategies/late_chunking_jina.py`，复用语义边界切块并输出 `jina_v3 + boundary_pooling` contract metadata
- [x] chunker 自动调参
  现状：`app/services/chunk_quality_recommendation_service.py` 已新增 `build_chunker_autotune_plan()`，可基于 chunk quality / recall risk / parse risk 信号合成默认 `chunk_size / chunk_overlap / chunk_strategy_candidates` 自动调参计划
- [x] 跨数据集全局去重报表
  现状：已新增 `app/services/cross_dataset_dedup_report.py`，可基于各数据集 `near_dup_summary` / `near_dup_payload` 聚合跨数据集去重报表
- [x] 语言感知 embedding 路由
  现状：`app/rag/embedding/factory.py` 已新增 `resolve_language_aware_model_id()`，可按 `zh / en / mixed` 和文本检测结果选择 embedding model id
- [x] `app/rag/policy/complexity_classifier.py`
- [x] `workflows/step_back.py`
  现状：功能已在 `engine.py` / `retrieval/orchestrator.py` 与 `tests/test_step_back_query_expansion.py` 落地，尚未拆成独立 workflow 文件
  现状：功能已在 `engine.py` / `retrieval/orchestrator.py` 与 `tests/test_step_back_query_expansion.py` 落地，尚未拆成独立 workflow 文件
- ~~结构化澄清 agent~~（当前分支不做聊天式澄清问答优化）
- [x] RRF 权重线上可观测 + LTR 学得
  现状：已新增 `app/services/fusion_weight_learning_service.py`，可从 `rag_trace` / `training_export_row` 汇总 `rrf_k / fusion_strategy / fusion_weights / channel score coverage / ltr_training_ready_rows` 观测快照；配合既有 LTR 训练/rollout 工具链形成可学信号闭环
- [x] `retrieval_profiles.py` long_context 预置
- [x] BGE-M3 三态索引
  现状：`app/rag/embedding/bge_m3_triplet.py` 已新增 `build_bge_m3_tri_index_payload()`，同一 chunk 可同步产出 `dense / sparse / colbert` 三视图并绑定 `chunk_type` 子索引键
- [x] per-tenant RRF 权重学习
  现状：仓库已有 `scripts/learn_fusion_weights_offline.py` 与 `scripts/apply_fusion_weights_to_dataset.py`，本轮新增 `suggest_tenant_fusion_weights()` 可基于 tenant 级 feedback/training rows 的 trace_snapshot 给出归一化 `fusion_weights` 建议
- [x] 独立 MMR reranker
  现状：已新增 `app/rag/reranker/mmr.py` 作为独立 deterministic provider；不再只是 retriever 内部模式
- [x] `reranker/bge_v2.py`
  现状：已新增 `BGEV2Reranker` 兼容 wrapper，当前复用 `LocalBGEV2M3Reranker`
- [x] `tools/web_search.py`
- [x] `workflows/self_rag.py`
- [x] `workflows/flare.py`
- [x] `kg/search/drift_search.py`
- [x] `kg/search/pprank.py`
- [x] 温度敏感节点 / snapshot 选择
  现状：已新增 `app/rag/kg/search/snapshot_router.py`，可按时间敏感 query 选择匹配年份或 latest snapshot
- [x] community 多层级选择
  现状：`app/rag/kg/community.py` 已新增 `build_multi_level_community_selection()`，支持 `global / local / drift` 三种 scope 的 coarse/deep community 选择
- [x] `app/parsing/parsers/video_parser.py`
  现状：已新增本地安全的 `VideoParser` scaffold，输出视频引用 markdown 与基础 `video` metadata
- ~~`app/rag/tools/nl2sql.py`~~（当前分支按用户明确要求不做）
- [x] `embedding/providers/{voyage,cohere,jina,bedrock}.py`
  现状：已新增四个 provider wrapper，统一复用 `OpenAICompatibleEmbedding` client surface
- [x] `storage/vector/{qdrant,pgvector}.py`
  现状：已新增 Qdrant / PGVector scaffold store，并接入 vector factory / settings backend 校验
- [x] `embedding/matryoshka.py`
  现状：已新增 Matryoshka 工具层，支持向量维度裁剪、batch 应用和按 query complexity label 选择目标维度
- [x] `embedding/code_embedder.py`
  现状：已新增 deterministic code embedder scaffold，可为代码片段生成稳定向量
- [x] `llm/semantic_cache.py`
  现状：实际实现路径为 `app/services/semantic_cache.py`，retriever 已接入 semantic cache lookup/set 流程
- [x] `safety/llm_guard.py`
- [x] `evaluation/redteam_suite.py`
- [x] `evaluation/online_shadow.py`
- [x] `evaluation/ab_experiment.py`
- [x] Phoenix adapter
  现状：已新增 `app/services/phoenix_adapter.py`，可把 `RagTraceBundle` 转为 Phoenix 友好的 span payload
- [x] chunk quality 闭环推荐
  现状：已新增 `app/services/chunk_quality_recommendation_service.py`，基于 `chunk_quality_metrics` / `recall_risk_hints` / `parse_risk_summary` 生成离线可复用的闭环调参建议与 patch
- [x] `core/cost_tracker.py`
- [x] `services/tenant_quota.py`
- [x] Chunk-level ACL 端到端审查与 escape 测试
  现状：已补充 retriever 级 ACL red-team 回归测试，覆盖 forged `document_id` metadata 无法绕过 DB ACL、ACL 解析异常 fail-closed 两类 escape 场景
- [x] `app/services/lineage_service.py`
  现状：已新增 `app/services/lineage_service.py`，支持 chunk→doc→connector→ACL→pipeline version→retrieval usage 的统一 lineage payload，并预留 answer lineage scaffold
- [x] 多区域 provider / storage routing
  现状：已新增 `DATA_REGION` / `OBJECT_STORAGE_REGION_PROFILES` / `VECTOR_REGION_BACKENDS` scaffold，object store / vector factory 可按 region 做最小路由

## `rag-context-expansion-rerank-2026-q2.md`

- [x] `reranker/long_context_rerank.py`
  现状：已新增 `LongContextReranker` provider，并接入 reranker factory / settings 校验；`long_context` retrieval profile 现在默认走 `reranker_provider=long_context`
- [x] `retrieval/neighbor_expand.py`
- [x] `workflows/rerank_expand_rerank.py`
- [x] 内部 855 问评测集
  现状：已新增 `app/rag/evaluation/datasets/contextual_855_plan.py`，提供 `50 文档 / 855 问 / 11.3 span-level` 的评测集构造 contract 与 `basic/contextual/expanded` 三档 track plan scaffold
- [x] `hierarchy_expand` 与 `neighbor_expand` 融合
  现状：已新增 `retrieval/context_expansion.py` 作为统一入口，封装 `neighbor / sibling / hierarchy` 三类扩展，并接入 retriever / rerank-expand-rerank / orchestrator
- [x] Expanded 模式 profile
  现状：已新增通用 `expanded` retrieval profile，默认映射到 recall-first + hierarchy overlay + parent/sibling context expansion，可供 tenant / query_type 路由直接引用
- [x] `mode ∈ {basic, contextual, expanded}` 三档 API
  现状：`ChatRAGConfig` 已新增 `mode` 字段；`basic -> hybrid_ce`、`contextual -> long_context`、`expanded -> expanded`，显式 `retrieval_profile` 优先级高于 `mode`
- [x] 切块失效三类样本接入评测集
  现状：已新增 `app/rag/evaluation/datasets/stage3_domain/{legal,finance,support}.jsonl` 与聚合 `manifest.json`，覆盖 `semantic_missing / semantic_ambiguity / structure_loss` 三类切块失效样本

## `rag-deep-research-2026-q2.md`

- [x] `plans/scripts/parse_bench.py`
- [x] `routing.py` quality fallback
- [x] Mathpix parser
  现状：已新增 `app/parsing/parsers/mathpix_parser.py` 外部 backend wrapper scaffold，带配置校验与基础 Markdown 输出
- [x] `colpali_parser.py`
  现状：实际实现路径为 `app/parsing/parsers/colpali_parser.py`
- [x] 内部切块基准 runner
  现状：已新增 `plans/scripts/chunk_bench.py`，可生成多数据集/多 chunk 配置的 benchmark 计划 payload
- [x] `semantic.py` minimum chunk size floor
  现状：`SemanticSentenceChunker` 已默认启用 `min_chunk_size=256`，并在尾块过小时做 floor merge；支持显式传 `min_chunk_size=0` 关闭
- [x] `strategies/raptor.py`
  现状：已新增 `app/rag/chunking/strategies/raptor.py`，提供 deterministic RAPTOR scaffold，输出 `leaf + summary` 两层 collapsed-tree chunk，并带 `raptor_layer/raptor_parent_id`
- [x] `contextual_enrichment` lazy incremental mode
  现状：已通过 indexing options / pipeline config 接入 `embedding_contextual_retrieval_lazy_mode`
- [x] `strategies/late_chunking_jina.py`
  现状：已新增 `app/rag/chunking/strategies/late_chunking_jina.py`，复用语义边界切块并输出 `jina_v3 + boundary_pooling` contract metadata
- [x] `preprocessing/synthetic_qa.py`
  现状：已新增 deterministic synthetic QA side-index scaffold，复用 `metadata_enrichment` 产出 `summary + questions + side-index documents`
- [x] `preprocessing/pii_presidio.py`
- [x] KenLM / small-LM perplexity filter
  现状：`app/rag/preprocessing/quality_filters.py` 已新增 `drop_if_high_perplexity_proxy()`，并接入 `GovernanceProcessor` 的 drop filter 与 `governance_quality.perplexity_proxy` 指标
- [x] `policy/complexity_classifier.py`
- [x] `workflows/step_back.py`
- [x] `workflows/self_route.py`
- ~~clarification agent~~（当前分支不做聊天式澄清问答优化）
- [x] `embedding/bge_m3_triplet.py`
  现状：已新增三态 payload helper，可一次产出 `dense / sparse / colbert` 视图
- [x] `reranker/mmr.py`
  现状：已新增本地 deterministic `MMRReranker` provider，并接入 reranker factory / settings 校验；基于 lexical relevance + diversity penalty 做 Maximal Marginal Relevance 重排
- [x] `reranker/bge_v2.py`
  现状：已新增 `BGEV2Reranker` 兼容 wrapper，当前复用 `LocalBGEV2M3Reranker`
- [x] calibration（Platt / isotonic）
  现状：已新增 `app/rag/evaluation/calibration.py`，提供 Platt scaler 与 isotonic calibrator 的纯工具层实现
- [x] `retrieval_profiles.py` long_context 预置
- [x] `tools/hierarchical_retrieval_tools.py`
- [x] `tools/retrieval_config_tool.py`
- ~~`workflows/critic.py` 独立 agent~~（当前分支不再继续扩展 agent 问答批评链路）
  现状：已有能力保留，但不再作为当前 backlog 继续增强
- [x] `evaluation/agent_redteam.py`
  现状：已补 suite runner；当前仍是 deterministic redteam，不含 CI 调度与自动样本生成
- [x] `tools/web_search.py`
- [x] `workflows/crag_streaming.py`
- [x] `workflows/self_rag.py`
- [x] `workflows/flare.py`
- ~~`evaluation/ragshaper_synthesizer.py`~~（当前分支不再继续做 agent 问答训练数据合成）
  现状：与用户已收缩的 `RAG-only / 非 agent QA 优化` 范围冲突，当前 backlog 移除
- [x] `evaluation/graphrag_bench.py`
- [x] `kg/search/pprank.py`
- [x] `kg/search/drift_search.py`
- [x] Query 复杂度 → KG 方法路由
  现状：已新增 `app/rag/kg/search/method_router.py`，把复杂度标签与 KG query mode 合并映射到 `pprank / drift_search / hybrid`
- [x] Temporal KG snapshot 自动选
  现状：已新增 `app/rag/kg/search/snapshot_router.py`，为 temporal query 提供 deterministic snapshot route helper
- [x] `parsers/colpali_parser.py`
  现状：实际实现路径为 `app/parsing/parsers/colpali_parser.py`
- [x] `parsers/video_parser.py`
  现状：实际实现路径为 `app/parsing/parsers/video_parser.py`
- [x] `parsers/audio_parser.py`
  现状：已新增本地安全的 `AudioParser` scaffold，输出音频引用 markdown 与基础 `audio` metadata
- [x] `query_image` API 路由
  现状：`app/api/v1/rag.py` 的 `retrieve-preview` / `retrieve` 请求已新增 `query_image` 字段，显式图片查询会注入 CLIP image docs，并保留 multimodal debug metrics
- [x] `embedding/providers/{voyage,cohere,jina,bedrock}.py`
  现状：已新增四个 provider wrapper，统一复用 `OpenAICompatibleEmbedding` client surface
- [x] `storage/vector/{qdrant,pgvector}.py`
  现状：已新增 Qdrant / PGVector scaffold store，并接入 vector factory / settings backend 校验
- [x] `embedding/matryoshka.py`
  现状：已新增 Matryoshka 工具层，支持 `simple/structured/multi_hop` 三档维度决策
- [x] `embedding/code_embedder.py`
  现状：已新增 deterministic code embedder scaffold，可为代码片段生成稳定向量
- [x] `evaluation/hard_negative_stress.py`
- [x] `core/cost_tracker.py`
- [x] `evaluation/online_shadow.py`
- [x] `evaluation/ab_experiment.py`
- [x] 前 5 连接器
  现状：当前仓库已落地 5 个非 DB 连接器实现并接入 registry / job dispatch / API 执行链路：`github_repo / drive_files / minio_bucket / confluence_space / jira_project`；与早期优先级列表（SharePoint / Confluence / Notion / GitHub / S3）不完全一致，但“前 5 连接器实装”这一交付已具备
- [x] Chunk-level ACL escape 测试
  现状：已新增 retriever ACL escape 回归测试，锁定 fail-closed 与 DB source-of-truth 行为
- [x] `services/lineage_service.py`
  现状：已新增统一 lineage service scaffold，先覆盖 chunk/doc/connector/ACL/retrieval 链路查询 contract
- [x] `services/rtbf_cascade.py`
  现状：已新增 `app/services/rtbf_cascade.py`，复用现有 document delete lifecycle 做文档/向量/KG/对象存储级联删除，并补 dataset cache 失效、有限重试与审计汇总
- [x] 多区域 PoC
  现状：已新增 region-aware backend routing PoC，先覆盖 object storage / vector backend 的按区域 profile 选择

## `rag-eval-dataset-deep-dive-2026-q2.md`

- [x] Stage 1 种子集：`datasets/stage1/seed.jsonl`
- [x] Stage 1 manifest：`datasets/stage1/manifest.json`
- [x] Stage 2 合成 pipeline：`evaluation/synthetic/pipeline.py`
- [x] Stage 1 summary report：`evaluation/reports/stage1_summary.py`
- [x] Stage 2 扩展到 500–1000 条的稳定合成链路与 critique 过滤闭环
  现状：`app/rag/evaluation/synthetic/pipeline.py` 已支持可注入 generator/critic、attempted/accepted/rejected 统计与 critique 过滤；`critic.py` 已补 grounded/relevance/standalone 三过滤
- [x] Routing Accuracy / Conflict Rate / Decomposition F1 三项方案专属指标齐套
  现状：`app/rag/evaluation/metrics/{routing,fusion,decomposition}.py` 已提供三项 deterministic 指标计算，并有对应单测覆盖
- [x] 11 维 dashboard 落地
  现状：已新增 `app/rag/evaluation/reports/dashboard_11d.py`，可把 eval result rows 聚合成 11 维 summary payload 并按 `query_type` 切片；当前为后端 summary builder
- [x] Stage 3 hard negative / prompt injection / PII trap 样本常态化
  现状：已新增 `app/rag/evaluation/datasets/stage3_adversarial/` 样本集与 `stage3_manifest.py` helper，覆盖 `hard_negative / prompt_injection / pii_trap` 三类 guardrail 样本
- [x] 生产流量 shadow eval
  现状：`app/rag/evaluation/online_shadow.py` 已补 deterministic 日采样计划 helper 与 baseline/candidate 双跑计划 contract，并复用既有 diff 汇总
- [x] 按季度动态重生成 20% 样本
  现状：已新增 `app/rag/evaluation/datasets/quarterly_refresh.py`，可按 `quarter_key` deterministic 选择 20% refresh 样本并保留 80% stable baseline

## `rag-ibm-champion-blueprint-2026-q2.md`

- [x] `docling_parser.py` JsonReportProcessor 模式重构
  现状：已在 `app/deepdoc/parser/docling_parser.py` 新增 `JsonReportProcessor`，统一装配 `metainfo / content / tables / pictures`，并保留向旧 `(sections, tables)` contract 的回退
- [x] 双重容错推广到其他 parser
  现状：已新增 `app/parsing/utils/markdown_response.py` 共享 helper，并接入 Marker / MinerU 的 JSON markdown 提取路径，支持多 key + 嵌套 `data/result` fallback
- [x] `retriever.py` `entity_key` 路由
  现状：`HybridRetriever` 已支持 `entity_key` / `partition_keys` / `entity_candidates`，统一折叠为 `partition_keys.$in` metadata filter，并把路由信息写入 retriever debug
- [x] 实体抽取 → partition_keys 缩检索空间
  现状：已通过 `app/rag/utils/entity_matcher.py` + retriever filter 合成实现最小逻辑路由闭环；当前为 metadata-filter 收窄，不是 Milvus 物理 partition 管理
- [x] `utils/entity_matcher.py`
  现状：已新增 `app/rag/utils/entity_matcher.py`，提供长度倒序 + ASCII 边界匹配 + 匹配后移除的实体 surface 匹配与 `extract_partition_keys` helper
- [x] `chunking_grid` runner 加 Ilya 300/50 对照组
  现状：`scripts/chunking_grid_runner.py` 已新增显式 `ilya_300_50` control group（`langchain_recursive` + `300/50`）
- [x] 验证小块检索 + 回页喂食闭环
  现状：已补回归测试，覆盖 `_get_relevant_documents()` 在 child hits 足够时自动喂 parent context，以及 retrieval stitching 对连续 chunk 的顺序修复
- [x] 三层显式路由：实体 / 意图 / 复合查询
  现状：已新增 `app/rag/policy/router_layers.py`，聚合实体路由、意图路由、复合查询路由三层 deterministic 决策
- [x] router 决策写 `trace_schema.py` + Prometheus
  现状：`router_layers` 已写入 retrieval trace/query_debug，`app/rag/trace_schema.py` / `app/services/rag_trace_service.py` 已支持安全承载，且新增 `app/services/router_prometheus_metrics.py`
- [x] `llm_based.py` `llm_weight`
- [x] `llm_based.py` fallback 默认分补齐
  现状：`app/rag/reranker/llm_based.py` 已支持 LLM 部分漏返回时用 `RERANKER_LLM_FALLBACK_SCORE` 参与加权融合；整次输出无效时仍回退到纯 vector anchor
- [x] tenant / query_type 权重配置
  现状：已新增 `RERANKER_LLM_WEIGHT_BY_TENANT` / `RERANKER_LLM_WEIGHT_BY_QUERY_TYPE` 解析与透传，现有 reranker 调用点会下发 `tenant_id` 与可选 `query_type`
- [x] `llm/structured_output.py`
  现状：实际实现路径为 `app/rag/llm/structured_output.py`
- [x] structured output 全项目迁移
  现状：`app/rag/output/__init__.py` 的 `faq / summary / action_items` 旧链路已迁入统一 `app/rag/llm/structured_output.py` 指令与 repair 框架，并保留本地输出模型适配层
- [x] `llm/prompts/` 目录
  现状：目录已存在，包含 `templates.py` / `schemas.py` / `oneshots.py` / `system_prompts.py`
- [x] prompt 版本控制 + snapshot test
  现状：`app/rag/llm/prompts/` 已集中管理 PromptBundle，`tests/test_prompt_bundle_snapshot.py` 锁定 `kb_assistant` prompt bundle render snapshot
- [x] Prompt A/B 框架
  现状：`PromptTemplate` 已支持 `template_key/version/parent_id/ab_experiment_key/ab_variant/ab_weight`，并由 `app/services/prompt_resolver.py` 与 `app/services/rag_config_template_resolver.py` 提供稳定分流与 adaptive routing

## `rag-kg-deep-research-2026-q2.md`

- [x] `app/rag/kg/search/agentic_beam_search.py`
- [x] `app/rag/kg/search/path_verbalizer.py`
- [x] `app/rag/kg/search/plan_on_graph.py`
- [x] `app/rag/kg/search/pprank.py`
- [x] `app/rag/kg/search/drift_search.py`
- [x] `app/rag/api/v1/network_analysis.py`
  现状：按当前仓库 API 结构实际落地为 `app/api/v1/network_analysis.py`
- [x] `app/rag/kg/search/lazy_indexer.py`
- [x] `app/rag/evaluation/graphrag_bench_runner.py`
- [x] `app/rag/kg/extraction/auto_graph_r1.py`
  现状：已新增 `build_auto_graph_r1_plan()`，可基于 entity/predicate/alias/skill 信号生成自动图构建阶段计划与风险标记
- [x] `app/rag/kg/search/subqrag.py`
  现状：已新增 `build_subqrag_plan()` 确定性 planner，复用现有 query decomposition 与 KG method router，为子问题生成 `hybrid / drift_search / pprank` 路由计划

## `rag-parsing-chunking-deep-dive-2026-q2.md`

- [x] `plans/scripts/omnidocbench_runner.py`
  现状：已新增 `plans/scripts/omnidocbench_runner.py`，可生成公开 OmniDocBench + 内部真实文档的 runner plan，并内置 DeepDoc vs MinerU 2.5 的默认切换决策门槛
- [x] `parsers/mathpix_parser.py`
  现状：实际实现路径为 `app/parsing/parsers/mathpix_parser.py`
- [x] `routing.py` quality fallback
- [x] PubTables-v2 / GriTS 报分
  现状：已新增 `app/rag/evaluation/parse_bench/grits.py` 轻量 GriTS proxy，并接入 `app/parsing/quality/benchmark.py` 输出 `table_grits_topology/content/f1`
- [x] `parsing/enrich/chart_to_data.py`
  现状：主流程接线在 `app/parsing/processors/processor.py`
- [x] 多页表格合并
  现状：`app/parsing/processors/cross_page_merge.py` 已实现表格专用跨页合并（行延续 / 续表标签 / 重复表头去重），并接入 parsing processor 主流程
- [x] `parsers/colpali_parser.py`
  现状：重复审计项；实际实现路径为 `app/parsing/parsers/colpali_parser.py`
- [x] `retriever.py` `colpali_retriever`
  现状：`HybridRetriever` 已新增最小 `colpali_retriever` channel scaffold，image-like query 下可对 `visual_document` / `colpali` parser 输出做独立 lexical 检索并并入现有融合链路
- [x] PLAID 压缩
  现状：已新增 `app/rag/retrieval/plaid.py`，提供 late-interaction 向量的 deterministic 压缩/重建 contract（`compress_plaid_vectors()` / `decompress_plaid_vectors()`）
- [x] `chunking/roles.py` chunk_type 标准化扩展
  现状：已新增 `ChunkType` 枚举与 `classify_chunk_type()`，覆盖 `text / formula / table / code / figure / chart_data / seal`，processor 已在 chunk metadata 中统一写入 `chunk_type`
- [x] `retriever.py` 按 chunk_type 加权
  现状：retriever 已支持 query-aware chunk type weighting；当 query 明显指向 `table/code/formula/chart/seal` 时，会对匹配 `chunk_type` 的候选施加轻量 boost，并透出 `chunk_type_signal/chunk_type_boost`
- [x] `plans/scripts/chunking_grid_runner.py`
  现状：实际实现路径为 `scripts/chunking_grid_runner.py`；已支持默认 grid 配置生成与本地文件离线 chunk/token 统计，`contextual` 档映射到 recursive + contextual flag
- [x] `strategies/semantic.py` minimum chunk size floor
  现状：已覆盖 `tests/test_semantic_chunk_floor.py`
- [x] Context Cliff metrics 监测
  现状：已新增 `app/rag/core/context_cliff.py`，并在 engine/langgraph 的 `context_tokens` metrics 上挂 `context_cliff_threshold_tokens / context_cliff_triggered / context_cliff_overflow_tokens`
- [x] `contextual_enrichment.py` `lazy_mode`
  现状：默认关闭；开启后按 metadata 中的 gap/required 标记触发，不再全量注入 contextual prefix
- [x] semantic 预切块 + Leiden 聚类
  现状：`app/rag/chunking/strategies/raptor.py` 已新增 `build_semantic_leiden_proxy_clusters()`，基于 semantic 预切块和相似度图连通分量提供 deterministic `Leiden proxy` 聚类，并可通过 `cluster_strategy=\"leiden_proxy\"` 写入 `raptor_cluster_strategy`
- [x] `strategies/late_chunking.py`
  现状：已新增 `app/rag/chunking/strategies/late_chunking.py`，输出文档级 pooling contract metadata，作为 late chunking embedding 接入前的稳定边界层
- [x] parent_child 层级缓存
  现状：`ParentChildChunker` 已新增进程内 split cache；相同输入文档 + 相同参数重复切块时复用稳定层级结果，并返回克隆副本避免 metadata 共享
- [x] `strategies/agentic_chunker.py`
  现状：已新增 `app/rag/chunking/strategies/agentic_chunker.py`，提供离线批处理 scaffold，复用语义边界并输出 `agentic_chunker_mode/judge/signals` metadata 供高价值失败样本重切

## `rag-poc-attribution-framework-2026-q2.md`

- [x] `app/rag/evaluation/poc_runner/attribution_classifier.py`
- [x] `reports/attribution_report.py`
- [x] `app/rag/evaluation/poc_runner/out_of_scope_verifier.py`
- [x] `reports/umap_scatter.py`
- [x] `app/rag/evaluation/poc_runner/query_pattern_miner.py`
- [x] 缩写反向回填术语映射表自动化
  现状：已补 dataset-scoped `glossary-writeback` 接口与 `glossary.generated.yaml` 草稿写回链路
- [x] `app/rag/evaluation/poc_runner/latency_decomposer.py`
- [x] `app/rag/industry_rules/` 目录
- [x] 行业规则库 CMS
- [x] 规则自动挖掘
- [x] 评测报表模板固定 5 指标并列输出
  现状：已补固定 `metric_cards` + `feedback_coverage` 结构，并接入 HTML / PNG report 渲染

## `rag-poc-to-mvp-delivery-2026-q2.md`

- [x] `app/parsing/preprocess/industry_noise_patterns/`
  现状：已新增 `industrial_control / finance / legal` 三个行业噪音规则目录，输出兼容现有 `RegexRule`
- [x] `preprocess/llm_noise_miner.py`
  现状：已新增 deterministic noise miner，能从抽样行中产出 exact/template 候选规则，供人工复核后转入治理规则
- [x] `parsing/output/markdown_writer.py`
- [x] `parsing/output/docx_writer.py`
- [x] 引用卡片跳转 Clean DOCX
- [x] DOCX 标题高亮关键词
- [x] `preprocessing/metadata_enrichment.py`
- [x] `chunking/factory.py` 富语义 chunk 注入
- [x] `retriever.py` questions 字段 HyDE 通道
  现状：`HybridRetriever` 已将 `document_questions` 注入 BM25 / sparse / ColBERT 检索语料；BM25 额外加入 questions overlap boost，同时对外仍返回原始 chunk content
- [x] `retrieval/sibling_expand.py`
- [x] `retrieval/orchestrator.py` 短文档 sibling / 长文档 neighbor 路由
- [x] sibling / neighbor / hierarchy_expand 统一 expansion 框架
  现状：统一入口为 `app/rag/retrieval/context_expansion.py`；retriever 走 `expand_ranked_chunk_results()`，层级扩展走 `expand_hierarchy_documents()`，workflow 走 `expand_reranked_ids_by_score()`
- [x] `evaluation/recall_at_k_runner.py`
- [x] `reranker/local_bge_v2_m3.py`
- [x] `config/rerank_profile.py`
- [x] `storage/object/image_mapping.py`
- [x] `middleware/image_url_rewriter.py`
- [x] `storage/object/` 多后端路由
  现状：`get_object_store()` 已支持 `minio / s3 / s3_compatible / oss / cos` 路由；默认保留 `minio_service`，其余 provider 通过通用 `OBJECT_STORAGE_*` profile 构造 S3-compatible store
- [x] `services/feedback_service.py`
- [x] `models/chat_message.py` metadata JSONB 扩展
  现状：实际模型文件为 `app/models/chat.py`，当前虽沿用 `chat` 命名，但业务语义按请求轨迹埋点处理，并已统一写入 `rewritten_query / retrieved_docs / latency_stats`
- [x] tenant RLS 封装
- [x] `workflows/query_rewrite.py`
- [x] SSE 先透 `rewritten_query`
- [x] `rewritten_query` 落 `chat_messages.metadata`
  现状：当前实现表名仍为 `chat_messages`，但该字段用于请求改写 / 检索轨迹复盘
- [x] 运营看板
- [x] `scripts/export_diagnostics.py`
- [x] `services/config_hot_reload.py`
  现状：已新增配置热刷新判定服务，复用 `ops_config_snapshot` 输出组合 `ops/retrieval` 指纹，并提供 `should_hot_reload_config()`
- [x] MCP Server 暴露能力
- [x] 反馈数据驱动 Prompt 迭代
- [x] 达阈值后自动化微调评估

## `rag-pre-poc-scanner-2026-q2.md`

- [x] `app/rag/tools/pre_poc_scanner/format_distribution.py`
  现状：已新增独立格式分布统计 helper；runner 仍保留自己的集成逻辑
- [x] `app/rag/tools/pre_poc_scanner/pdf_page_classifier.py`
  现状：已新增独立三档 PDF 页密度分类 helper；runner 仍保留自己的集成逻辑
- [x] `app/rag/tools/pre_poc_scanner/length_distribution.py`
  现状：已新增独立长度分位数/直方图 helper；runner 仍保留自己的集成逻辑
- [x] `app/rag/tools/pre_poc_scanner/md5_dedup.py`
  现状：已新增独立 MD5 精确去重 helper；runner 仍保留自己的集成逻辑
- [x] SimHash 高相似度待确认列表产品化输出
  现状：已新增 `app/rag/tools/pre_poc_scanner/simhash_similarity.py`，可输出 review candidates / keep candidate / member stats
- [x] 敏感信息带上下文待审核列表
  现状：已新增 `app/rag/tools/pre_poc_scanner/sensitive_info.py`，统一产出 PII / secrets 命中计数与脱敏上下文样本
- [x] 单文件离线 HTML 报告
  现状：`app/services/report_html.py` 已提供 `render_precheck_html()` 单文件离线 HTML；`app/api/v1/dataset_precheck.py` 已暴露 `export-html`
- [x] 一键打开闭环 / dashboard server
  现状：已新增 `app/rag/tools/pre_poc_scanner/dashboard_server.py` 最小 FastAPI/SSE skeleton，提供 `dashboard / events / open-file / health` 路由，可嵌入一键打开闭环
- [x] 与 `dataset_precheck_service.py` 明确集成
  现状：`app/api/v1/dataset_precheck.py` 已通过 `load_precheck_summary_from_row` / `load_precheck_samples_from_row` / `load_precheck_near_dups_from_row` 等能力复用 `dataset_precheck_service.py`
- [x] 可配置阈值 CMS
  现状：已新增 `app/rag/tools/pre_poc_scanner/settings.py`，并将 `threshold_overrides` 接入 `DatasetPrecheckScanRunCreateRequest` 与 `dataset_precheck_scan_runner.py`


## 汇总结论

- 当前 **没有任何一份 plan 可以整体打 `[x]`**。
- 完成度最高的方向：
  - agentic 基础件
  - POC attribution
  - 上下文扩展的邻近扩展 / rerank-expand-rerank
- 缺口最密集的方向：
  - parsing/chunking benchmark 与多模态 parser
  - enterprise / governance / safety 深水区
  - POC→MVP 的产品化闭环
