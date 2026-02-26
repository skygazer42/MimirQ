# Top-tier RAG 100-Task Execution Plan (MimirQ)

> **Goal:** 把 MimirQ 打造成企业级「顶尖」RAG 平台：更强召回、更稳重排、更可控 KG/GraphRAG、更工业化 chunk/ingest、更可视化诊断、更可评估回归、更可合规交付。
>
> **Date:** 2026-02-26
>
> **PII-safe 原则（强制）：** 任何 trace / 指纹 / 导出默认不得包含原始 query、真实文档内容、tenant/dataset/document 真实标识符或 metadata_filter 明文；必须使用哈希/摘要/计数/采样（有权限的审计日志单独处理）。

本文把现有的 50-project roadmap 进一步拆成 **100 个“可落地、可验收”的任务**，并按工业直觉排序（先补“质量闭环 + 可观测 + 合规交付”底座，再强化 retrieval/rerank/kg/chunk，最后做体验与规模化）。

---

## 0) 任务格式

每个任务用 `T###` 标识：
- **Priority**：P0（必须/阻断交付）→ P3（长期）
- **Deliverables**：代码/API/文档/测试/可视化
- **Acceptance**：可验证的验收点（必须可测/可回归）
- **Deps**：可选依赖（按任务号）

> **Wave discipline（建议）：** 每 5–12 个任务为一个 wave；每 wave 只做 **一次** commit（包含代码+测试+bd+文档），并 push。

---

## 1) Track A — Retrieval & Indexing (T001–T020)

- **T001 [P0] Hybrid retrieval 诊断结构化**：把每路召回通道（vector/keyword/kg/filters）贡献、截断原因、预算信息结构化进入 retriever_debug（PII-safe）。
  - Acceptance：trace 中可解释“为何返回这些候选/为何丢失候选”；单测覆盖关键字段。
- **T002 [P0] 搜索预算统一器**：每次检索强制走统一 budget 计算（top_k/search_k/overfetch）并在 trace 输出。
  - Acceptance：不同 retriever 预算口径一致；回归不降质。
- **T003 [P0] Metadata filter explain**：对 metadata filter 的命中/拦截做计数与示例（哈希/摘要），用于诊断“过滤过严”。
  - Acceptance：不泄露 filter 明文；能定位 ACL/filter 导致召回 0 的原因。
- **T004 [P0] Vector store selective delete contract**：抽象出“按 doc_pipeline_key 删除”的能力契约与降级策略（已部分实现，补齐后端一致性与测试）。
  - Acceptance：version delete 不误删 active 版本；后端不支持时可观测告警。
- **T005 [P0] Retrieval cache（query 指纹）**：对 retrieval candidates 做短 TTL 缓存（PII-safe hash key + ACL-aware），避免重复检索浪费。
  - Acceptance：缓存命中不改变正确性；默认关闭可开关；包含 hit/miss 指标。

- **T006 [P1] Multi-vector / late interaction（ColBERT-lite）原型**：引入轻量 late-interaction 检索路径（可选依赖 torch/transformers），先做离线评估。
  - Acceptance：在 hardcases 切片上可量化提升；可开关；成本可控。
- **T007 [P1] SPLADE / sparse expansion**：提供稀疏增强召回（SPLADE 或 BM25 扩展）与融合策略。
  - Acceptance：召回提升可测；对噪声/重复有抑制。
- **T008 [P1] 语义去重（embedding-level）**：候选去重从 doc_id 升级为“近重复 chunk”聚类（PII-safe）。
  - Acceptance：减少重复引用；不降低覆盖率。
- **T009 [P1] Cross-dataset routing**：基于 query 意图/实体/历史，动态路由 dataset（但默认仍显式 dataset_id；企业场景可开关）。
  - Acceptance：路由决策可解释；误路由可回滚。
- **T010 [P1] Retrieval feature store**：把召回阶段的稳定特征（rank/score/channel/budget/filter counters）标准化写入 LTR 特征输入。
  - Acceptance：LTR 离线/在线一致，特征版本化。

- **T011 [P1] “空召回”恢复策略**：当 ACL/filter 导致空召回时，触发备用通道（keyword-only / relax threshold）并写明原因。
  - Acceptance：减少无证据回答；trace 清晰。
- **T012 [P1] 候选覆盖率指标（coverage proxy）**：把“候选覆盖”代理指标加入 metrics（不含原文）。
  - Acceptance：可用于 gate 阈值。
- **T013 [P2] Ingest-time field normalization**：对标题/路径/段落层级等字段标准化，供检索字段提升。
  - Acceptance：索引字段一致；迁移可回滚。
- **T014 [P2] Fast embed batching**：Embedding 批量与并发自适应（多 provider）。
  - Acceptance：吞吐提升；不触发 provider rate limit。
- **T015 [P2] Query intent classifier (cheap)**：用规则+小模型做意图分类（FAQ/SQL/Policy/HowTo/Debug），驱动检索策略。
  - Acceptance：可解释、可禁用；准确率在标注集达标。

- **T016 [P2] 结构化索引（标题树/section）**：为 chunk 建立 section_path 索引，支持“限定章节检索”。
  - Acceptance：对手册类明显提升。
- **T017 [P2] Source freshness / version bias**：引入文档新鲜度、版本优先级信号，避免引用过期。
  - Acceptance：可配置；可审计。
- **T018 [P3] ANN 参数自调优**：根据数据规模/维度自调 IVF/HNSW 参数（离线建议）。
  - Acceptance：QPS 提升且召回不降。
- **T019 [P3] 近实时索引一致性检查**：补齐 index-audit 与告警。
  - Acceptance：发现向量孤儿/缺失并可定位。
- **T020 [P3] 检索端“回放一致性”**：同一 retrieval_config_hash + 固定 seed 可复现候选排序（在不含 PII 前提下）。

---

## 2) Track B — Reranking & Learning (T021–T035)

- **T021 [P0] Rerank 预算治理**：统一 reranker_top_n、timeout、fallback；trace 输出原因。
- **T022 [P0] Reranker cache（输入指纹）**：对 rerank 输入（候选指纹）做缓存，避免重复 cross-encoder 成本。
- **T023 [P0] LTR 特征版本化**：特征 schema + feature_version；训练/推理一致性校验。
- **T024 [P0] Hard negative mining 自动化**：从线上 trace/feedback 生成 hard negatives（PII-safe）。
- **T025 [P0] LTR regression gate**：在 CI/预发加入 LTR gate，失败报告可读。

- **T026 [P1] Pairwise / listwise 训练管线**：支持 pairwise/listwise 多目标训练。
- **T027 [P1] 解释型 rerank 诊断**：输出 rerank 主要因素（不泄露原文）。
- **T028 [P1] 轻量本地 reranker 备份**：torch + sentence-transformers/cross-encoder fallback（可选）。
- **T029 [P1] Rerank 模型 A/B**：按 tenant/dataset 实验开关，带 lineage。
- **T030 [P1] Rerank 对 KG 特征融合**：把 KG ranking features 纳入 LTR/Rerank（已部分贯通，补齐训练侧）。

- **T031 [P2] Long-context rerank**：对长 chunk 做摘要后 rerank（减少 token）。
- **T032 [P2] De-bias 多样性重排**：避免 topN 全来自同一 doc/section。
- **T033 [P2] Multi-objective rerank**：同时优化覆盖率/新鲜度/权威性。
- **T034 [P3] 在线学习（安全模式）**：仅在 approved hardcases 上做小步更新（HITL gating）。
- **T035 [P3] 模型供应链（签名/校验）**：模型文件哈希、加载可审计。

---

## 3) Track C — KG / GraphRAG (T036–T055)

- **T036 [P0] KG extraction 质量门禁**：抽取前后质量信号（噪声率、实体覆盖、孤儿边）与回归。
- **T037 [P0] KG 事件→证据对齐**：每条 KG 事件必须能落回 chunk citation（已部分；补齐 UI/导出）。
- **T038 [P0] Graph query planner**：根据 query 实体与关系类型选择 expand 策略（深度/宽度/预算）。
- **T039 [P0] KG 权重学习**：把 path confidence / pagerank / evidence_anchored 组合成可训练权重（离线）。
- **T040 [P0] KG 安全裁剪**：KG 的 recall/expand 必须完全遵守 document ACL trimming（强测）。

- **T041 [P1] GraphRAG community detection**：对图做社区划分与摘要（PII-safe），用于“概览式回答”。
- **T042 [P1] GraphRAG map-reduce 摘要**：社区摘要可缓存、可版本化、可回滚。
- **T043 [P1] Entity linking (fast)**：query → entity 候选（alias/synonym + embedding），驱动 KG recall。
- **T044 [P1] KG + 向量联合检索融合**：把 KG 命中的 chunk 作为 seed 扩展向量检索候选池。
- **T045 [P1] KG 反噪声策略**：低置信关系过滤、重复边合并、黑名单类型。

- **T046 [P2] Relation type taxonomy**：tenant 可配置关系类型、权重、展示名。
- **T047 [P2] KG 增量更新**：文档版本变更时仅更新影响子图。
- **T048 [P2] KG 可解释路径输出**：对每个命中 chunk 输出“路径证据”（实体链路）用于 UI。
- **T049 [P2] KG 实体向量检索**：实体向量索引用于相似实体召回（已部分，补齐评估）。
- **T050 [P2] KG 健康度仪表**：实体/边增长率、噪声率、孤儿比例、覆盖率趋势。

- **T051 [P3] 多模态 KG 节点**：支持图片/表格节点（需要 opencv/OCR 组合）。
- **T052 [P3] KG 知识冲突检测**：同一实体属性冲突时提示（不自动改写）。
- **T053 [P3] KG 版本快照**：按 pipeline_hash 做图快照与对比。
- **T054 [P3] KG 权限分层**：实体级/关系级 ACL（超企业场景，延后）。
- **T055 [P3] KG 自动评估集生成**：从图中生成问答对用于回归。

---

## 4) Track D — Chunking / Parsing / Ingestion (T056–T070)

- **T056 [P0] Chunk 策略对齐引用**：结构化 chunking（标题/表格/代码块）并确保 citations 稳定。
- **T057 [P0] Chunk 质量指标标准化**：短/长/重复/覆盖率/overlap waste 的统一计算与阈值。
- **T058 [P0] 文档版本化证据（doc_pipeline_key 全链路）**：已部分，补齐所有 ingest 入口与 UI。
- **T059 [P0] 解析失败诊断包**：失败时产出可下载诊断包（已部分，补齐一致性）。
- **T060 [P0] 增量 ingest（幂等）**：同源重复上传/connector 重跑不产生重复 chunk（版本化合并）。

- **T061 [P1] Semantic chunking**：基于 embedding 的语义断句（可选 torch/sklearn）。
- **T062 [P1] Table-aware chunking**：表格抽取/结构化存储与问答一致性。
- **T063 [P1] Code-aware chunking**：按 AST/语言块切分，保留上下文。
- **T064 [P1] PDF layout signals**：页眉页脚过滤、版面块识别（opencv 可选）。
- **T065 [P1] 多语言 chunk normalization**：统一编码、段落分隔、引用展示本地化。

- **T066 [P2] Connector ingest policy**：对不同 connector 强制治理策略（PII/secret/license）。
- **T067 [P2] Dedup across datasets (optional)**：企业同源文档跨数据集去重策略（谨慎）。
- **T068 [P2] Ingest preview 可视化**：前端展示 chunk 分布与问题点。
- **T069 [P3] OCR pipeline 插拔**：mineru/paddle/自建 OCR 的一致接口与回归。
- **T070 [P3] 文件类型扩展**：pptx/docx/eml 等工业常见类型（可选）。

---

## 5) Track E — Answer / Guardrails / Governance (T071–T080)

- **T071 [P0] 结构化回答 schema**：回答分点+引用 + JSON schema（可供 downstream 消费）。
- **T072 [P0] Post-check 反幻觉**：轻量 entailment/fact-check（预算可控，可关）。
- **T073 [P0] PII/secret/license guardrails**：与治理规则联动，可阻断/告警，可审计。
- **T074 [P1] Abstain policy 工业化**：abstain_rate 可控，原因可解释。
- **T075 [P1] 证据覆盖率 KPI**：回答必须达到引用覆盖阈值，否则降级/拒答。

- **T076 [P2] Tool/SQL 安全策略**：SQL 生成/执行强制脱敏、白名单、审计。
- **T077 [P2] Tenant glossary / synonyms**：tenant-scoped 术语表提升召回与 KG linking。
- **T078 [P2] 自适应引用颗粒度**：段落 vs 句子引用策略。
- **T079 [P3] 多轮记忆治理**：对 conversation memory 做可控摘要与清理。
- **T080 [P3] 对齐“可见证据”模式**：visible_evidence_only 更严格落地与 UI 提示。

---

## 6) Track F — Evaluation / Regression / Replay (T081–T090)

- **T081 [P0] EvidenceItem → RegressionCase 自动 sync（HITL）**：仅 approved 才能进入回归集。
- **T082 [P0] Regression gate 标准化**：CI/预发阈值策略、失败报告、diff 归因。
- **T083 [P0] 自动 hardcase mining**：从 trace/feedback 聚类、去重、候选推荐。
- **T084 [P0] Replay（PII-safe capture + deterministic）**：线上请求回放到离线评估。
- **T085 [P1] Slice dashboard**：按数据源/文件类型/语言/权限切片展示指标。

- **T086 [P1] Judge 模型版本化**：LLM-as-judge 的 prompt/model 版本化与回滚。
- **T087 [P2] 评估成本预算**：每次 run 成本/时延上限与排队策略。
- **T088 [P2] 质量漂移检测**：embedding drift、数据分布漂移预警。
- **T089 [P3] 自动标注辅助**：active learning 提示人工标注最有价值样本。
- **T090 [P3] 对外 leaderboard 导出**：企业报告用（脱敏）。

---

## 7) Track G — Enterprise Ops / Compliance / Delivery (T091–T100)

- **T091 [P0] 数据生命周期：导出/删除/保留策略**：数据导出（NDJSON/ZIP）、删除（含向量/KG/对象存储）、保留（retention job）。
- **T092 [P0] SSO（OIDC）基础**：登录、tenant claim、角色映射、审计。
- **T093 [P0] 多租户配额与限流**：dataset/account 维度 quota policy + enforcement + 观测。
- **T094 [P0] 加密与密钥管理**：at-rest/in-transit policy + 可选 KMS。
- **T095 [P0] Helm/K8s 打包**：可参数化部署、升级、回滚。

- **T096 [P1] 灾备与备份恢复演练**：DB/对象存储/向量库备份与演练脚本。
- **T097 [P1] Runbooks**：常见故障定位与处理（ingest/index/retrieval/rerank/LLM）。
- **T098 [P1] 安全基线扫描**：依赖漏洞扫描、镜像扫描、配置检查。
- **T099 [P2] 组织级审计导出对接 SIEM**：与企业日志管道对齐（字段稳定、压缩、游标）。
- **T100 [P2] 私有化交付 checklist**：交付验收清单、SLA/SLO、容量规划。

---

## 8) 执行策略（我将按此推进）

1. **先把交付底座做硬**：T091–T095（合规/运维/交付）与 T081–T085（评估回归）优先。
2. **其次补齐 retrieval/rerank 工业能力**：T001–T005、T021–T025。
3. **再做 KG/GraphRAG 进阶**：T036–T045。
4. **最后做体验与规模化优化**：多模态、在线学习、DR 演练、可视化深挖。

> 我会严格遵守：**TDD（先写失败测试）**、**PII-safe 默认**、**每 wave 一次 commit 并 push**、`bd` issue 跟踪。

