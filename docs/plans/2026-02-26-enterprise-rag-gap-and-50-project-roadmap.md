# Enterprise RAG Gap Snapshot + 50-Project Roadmap

> **Goal:** 把 MimirQ 打造成企业级「顶尖」RAG 平台：可评估、可审计、可规模化、可合规、可持续迭代（feedback → hardcases → regression → leaderboard → gate）。
>
> **Current date:** 2026-02-26
>
> **Important:** 本文刻意不包含任何真实用户问题/文档 ID 等潜在 PII；所有 trace/指纹计划均要求 PII-safe。

---

## 0) 当前进度（到 2026-02-26）

### 已完成（Wave0 + Wave1）

- **Wave0：检索配置指纹（retrieval_config_hash）**
  - 在 retrieval-only orchestration trace/metrics 中加入稳定哈希，便于对比不同检索配置的质量差异，且避免写入 query/tenant/dataset 等敏感字段。
- **Wave1：持续质量闭环（feedback → hardcases → leaderboard）**
  - `retrieval_config_hash` 统一指纹 helper（PII-safe），并贯通到 chat 的 rag_trace JSONL。
  - 新增反馈转 **draft EvidenceItem** 端点：把线上 feedback 快速沉淀为可审核 hardcase（EvidenceSuite）。
  - 新增回归 run 的 **leaderboard** 端点：按检索指标排序，返回轻量排行 + `retrieval_config_hash`。
  - 补齐单测与 API 文档。

### 已在待办（Wave2+）

`bd ready` 已有 Wave2/Wave3/Wave4 三个 epic（candidate generation / reranking&learning / KG+compliance packaging）。

---

## 1) 与顶尖 RAG 系统的差距（Gap Snapshot）

下面按“顶尖 RAG 平台”的常见能力维度对齐，列出我们现状与差距（同时给出优先级建议）。

### A. 候选召回（Candidate Generation）

**顶尖形态：**
- 多路召回（dense + sparse + graph + rules）+ 动态预算（per-query）+ 去重融合（RRF/learned fusion）
- 多向量/late-interaction（ColBERT/PLAID）用于高召回与难例
- 可控的 metadata/ACL filter，支持多数据源、多数据集路由

**差距：**
- sparse（SPLADE/BM25 增强）与 multi-vector（ColBERT 系）需更系统接入和可观测化。
- 召回侧的“可解释诊断”（候选为什么被召回、哪些通道贡献最大）还需要更强的结构化输出与 UI。

**优先级：P0（Wave2）**

### B. 重排与学习（Reranking + Learning-to-Rank）

**顶尖形态：**
- 多级重排：轻量 cross-encoder / bi-encoder rerank + LLM rerank（可开关、可预算）
- LTR pipeline：特征、训练、hard negatives、回归 gate、在线/离线一致性

**差距：**
- LTR 训练/回放/版本化、hard negative mining 自动化需要工程化落地。
- 对 reranker 的成本/延迟预算与 SLO 联动需要标准化。

**优先级：P0（Wave3）**

### C. Query 理解与路由（Query Understanding / Routing）

**顶尖形态：**
- query rewrite、多 query、decomposition、HyDE、实体链接、意图识别
- 动态 routing（到 dataset/index/工具）+ “可解释 routing 决策”

**差距：**
- rewrite/routing 当前更多靠经验配置；需要与评估/leaderboard 深度绑定（可回滚、可 A/B）。

**优先级：P1**

### D. 证据与回答（Grounding / Citations / Guardrails）

**顶尖形态：**
- 证据对齐：段落/句子级引用、引用高亮、可追溯（doc version / pipeline hash）
- Guardrails：事实性、敏感信息、合规政策、拒答与可解释

**差距：**
- EvidenceItem → RegressionCase 的全链路（review/approve → sync → gate）虽有基础，但需要更强的 workflow/权限/审计与 UI 面板。

**优先级：P1**

### E. 评估、回归与可观测（Evaluation / Regression / Observability）

**顶尖形态：**
- 离线评估：数据切片、回归对比、可视化、差异归因（retrieval vs rerank vs answer）
- 线上监控：SLO、成本、失败率、漂移检测；一键回放（replay）

**差距：**
- 需要把“hardcase 发现/生成”自动化：从 trace/feedback 挖掘、聚类、去重、分桶覆盖。
- 需要更强的“实验管理”（run lineage、配置版本、对比视图、审批流程）。

**优先级：P0-P1**

### F. 企业级工程（Security / Compliance / Multi-tenancy / Ops）

**顶尖形态：**
- SSO（OIDC/SAML）、RBAC、审计、加密、数据生命周期（导出/删除/保留）
- 多租户隔离、配额与限流、弹性扩缩、灾备、可升级/可迁移

**差距：**
- 合规“打包”与默认安全基线需要进一步产品化（Wave4）。

**优先级：P0-P1**

---

## 2) Roadmap 设计原则（企业级）

1. **可回滚**：任何质量/策略变化必须能被 `retrieval_config_hash`/run lineage 追踪，并能安全回滚。
2. **PII-safe 默认**：trace/指纹/leaderboard 只允许进入“配置/结构化指标”，禁止进入用户 query、tenant/dataset/document_ids 等敏感字段（必要时做单独的有权限审计日志）。
3. **评估先行**：新策略上线前必须有离线评估（回归套件 + 关键切片）+ 线上监控指标。
4. **成本/延迟预算**：每层（rewrite/recall/rerank/LLM）都要有预算与开关，并在 trace 中可见。
5. **一波一提交（Wave Commit Discipline）**：每个 wave 完结后只做一次 commit（包含代码+测试+文档+bd 状态）。

---

## 3) 50 个项目（Projects）

说明：
- 这里的“项目”粒度为 1-3 周（可拆成若干 `bd` 子任务）。
- 标注优先级：P0（必须）、P1（强烈建议）、P2（中期）、P3（长期优化）。
- 每个项目给出：**Deliverables / Acceptance**，尽量可验证。

### 3.1 Projects 01-10：召回与索引（Candidate Gen）

**P01 (P0) SPLADE sparse recall 接入（Wave2）**
- Deliverables: SPLADE encoder + sparse index + hybrid fusion（可配置/可观测）
- Acceptance: regression runs 中 sparse 通道可开关；leaderboard 可按 sparse 配置分组；端到端延迟可控。

**P02 (P0) Multi-vector retrieval（ColBERT/late-interaction）候选通道（Wave2）**
- Deliverables: multi-vector index + top-k candidates + trace/metrics
- Acceptance: 回归套件上 Recall@20 提升可量化；可回滚；资源占用有上限。

**P03 (P1) Candidate 去重与多通道贡献解释**
- Deliverables: 每个候选携带 `source_channels` + 得分分解（dense/sparse/kg）
- Acceptance: rag_trace 中可看到候选的“为什么进来”；UI/导出可读。

**P04 (P1) 元数据过滤（metadata filters）一致性与审计**
- Deliverables: filter schema、校验、trace redaction policy
- Acceptance: filter 不进入 fingerprint；但能在权限审计日志中追溯。

**P05 (P1) 分层索引（doc-level → chunk-level）**
- Deliverables: doc 级粗召回 + chunk 精召回
- Acceptance: 大文档/超大库下延迟与召回可同时改善；有基准对比。

**P06 (P2) 动态 top_k / fetch_k 预算（per-query）**
- Deliverables: 预算器（基于 query 复杂度/过滤范围/索引健康）
- Acceptance: latency P95 降低，质量不退化（回归 gate）。

**P07 (P2) 多数据集路由（dataset routing）**
- Deliverables: router + 权限校验 + 解释输出
- Acceptance: 多 dataset 情况下误召回率可控；可视化路由决策。

**P08 (P2) 索引健康与重建自动化（index health + auto rebuild）**
- Deliverables: 指标、报警、重建策略、回滚
- Acceptance: 索引漂移/损坏可自愈；不会影响在线稳定性。

**P09 (P3) 查询缓存（retrieval cache）与一致性策略**
- Deliverables: key 由 retrieval_config_hash + query_hash（可选）构成；TTL/invalidations
- Acceptance: 热点问答显著降延迟；不引入数据泄露。

**P10 (P3) 召回 A/B 实验框架**
- Deliverables: config rollout + 分流 + 指标对比
- Acceptance: 能对比不同召回策略的在线指标；实验可回滚。

### 3.2 Projects 11-20：重排与学习（Rerank/LTR）

**P11 (P0) LTR 特征与训练数据定义（Wave3）**
- Deliverables: 特征 schema、训练样本生成、版本化
- Acceptance: 训练/推理特征一致；可复现实验结果。

**P12 (P0) Hard negative mining（跨 run/跨版本）（Wave3）**
- Deliverables: 从失败/低分样本自动挖掘 hard negatives
- Acceptance: LTR/reranker 提升可在 regression leaderboard 上量化。

**P13 (P0) ColBERT rerank（候选重排层）（Wave3）**
- Deliverables: 高精度 rerank（可预算）
- Acceptance: NDCG/MRR 提升；延迟/成本有阈值与降级策略。

**P14 (P1) LLM reranker 标准化接口 + 成本预算**
- Deliverables: provider interface、token 预算、超时与 fallback
- Acceptance: 在 trace 中能看到 rerank 预算与降级原因。

**P15 (P1) 多级重排流水线（coarse → fine）**
- Deliverables: 轻量模型先筛候选，再用重模型精排
- Acceptance: P95 latency 可控，质量不退化。

**P16 (P2) 训练/评估 run lineage（模型版本/数据版本）**
- Deliverables: 每次训练/评估可追溯：数据集版本、索引版本、模型版本
- Acceptance: 任意 leaderboard 条目可回放并复现。

**P17 (P2) 在线学习（从 feedback/evidence 产生训练信号）**
- Deliverables: 反馈到训练样本的安全管道（HITL gating）
- Acceptance: 不会被噪声/投毒；可审计。

**P18 (P2) Rerank 的可解释性（feature attribution）**
- Deliverables: 输出 top features / contribution（best-effort）
- Acceptance: 工程可用，不阻塞主路径。

**P19 (P3) Cross-encoder 教师模型蒸馏**
- Deliverables: 蒸馏到轻量 reranker
- Acceptance: 延迟下降且质量保持。

**P20 (P3) 多语种/代码域 rerank 专项**
- Deliverables: 针对中文/代码的 rerank 适配
- Acceptance: 在 slice leaderboard 上可见提升。

### 3.3 Projects 21-30：Query 理解与路由

**P21 (P1) Query rewrite（可配置、可评估、可回滚）**
- Deliverables: rewrite templates + 版本化 + trace 记录（PII-safe hash）
- Acceptance: rewrite 策略 A/B 可控；不写入原 query 明文到公共 trace。

**P22 (P1) Multi-query / diversification**
- Deliverables: 多 query 生成 + 合并去重 + 预算
- Acceptance: Recall 提升可验证；成本/延迟可控。

**P23 (P1) Decomposition（复杂问题拆解）**
- Deliverables: 子问题图 + 子检索 + 合并回答（带引用）
- Acceptance: 对 hardcases 有明确收益；可降级到单 query。

**P24 (P2) 意图识别（问答/查数/操作）与工具路由**
- Deliverables: intent classifier + router
- Acceptance: 错路由率可监控；可人工 override。

**P25 (P2) 实体链接（Entity linking）与 KG 扩展**
- Deliverables: entity linker + kg query expansion
- Acceptance: KG 增益在 slice 上稳定可见。

**P26 (P2) 结构化过滤器生成（safe filter builder）**
- Deliverables: LLM 生成过滤条件但必须通过 schema 校验与 allowlist
- Acceptance: 防注入；严格审计。

**P27 (P2) 查询归因：路由/重写对质量贡献**
- Deliverables: run summary 分解（rewrite vs recall vs rerank）
- Acceptance: leaderboard 可定位“差在哪一层”。

**P28 (P3) 用户画像与会话记忆（可控）**
- Deliverables: memory tiers（短期窗口 + 长期摘要）
- Acceptance: 有 clear controls；不会泄露跨租户信息。

**P29 (P3) 多模态 query（图/表/代码）专项**
- Deliverables: 输入解析、专用检索
- Acceptance: 有独立评估集与指标。

**P30 (P3) Prompt-aware routing（按模板/场景自适配）**
- Deliverables: prompt template 与检索策略联动
- Acceptance: 模板变更不会静默改变检索行为（可追溯）。

### 3.4 Projects 31-40：证据、回答、Guardrails

**P31 (P1) 句子级 citation alignment + 高亮**
- Deliverables: evidence alignment pipeline + 前端高亮跳转
- Acceptance: 引用错误率下降；用户可一键定位证据。

**P32 (P1) Context compression（去重/摘要）**
- Deliverables: 结构化压缩器（可配置）+ eval
- Acceptance: token 成本降低，质量不退化。

**P33 (P1) Abstain/Refusal policy 标准化**
- Deliverables: 拒答策略、触发原因、可观测
- Acceptance: abstain_rate 可控，不影响正确问答。

**P34 (P1) 安全与敏感信息 Guardrails（与治理规则联动）**
- Deliverables: PII/secret/license guardrails + 处理动作
- Acceptance: 违规可阻断/红线报警；可审计。

**P35 (P2) Answer synthesis 的结构化输出（分点+引用）**
- Deliverables: 结构化回答模板与 JSON schema
- Acceptance: 引用覆盖率提升；便于 downstream 消费。

**P36 (P2) 证据版本化（doc_pipeline_key/pipeline_hash 全链路）**
- Deliverables: 证据随文档版本变化的兼容/回退策略
- Acceptance: 回归套件在 re-chunk 后仍尽量可用。

**P37 (P2) 反幻觉验证器（post-check）**
- Deliverables: 轻量 fact-check/entailment（可预算）
- Acceptance: hallucination 相关投诉下降；可关闭。

**P38 (P3) 领域术语表与同义词库（tenant-scoped）**
- Deliverables: glossary 管理 + 检索增强
- Acceptance: 对专业领域召回/回答提升可测。

**P39 (P3) 文档结构理解（标题/表格/代码块）**
- Deliverables: 结构化 chunking + retrieval aware
- Acceptance: 对长文档/手册类明显提升。

**P40 (P3) 多语言引用与本地化（i18n citations）**
- Deliverables: 多语言引用展示、编码统一
- Acceptance: 多语种 hardcases 覆盖。

### 3.5 Projects 41-50：评估平台、运维与合规

**P41 (P0) EvidenceItem → RegressionCase 自动 sync（HITL gating）**
- Deliverables: 仅 approved items 可 sync；冲突处理；审计日志
- Acceptance: 回归套件质量可控；不会被噪声污染。

**P42 (P0) Regression gate（CI/预发）标准化**
- Deliverables: 阈值策略、失败报告、diff 归因
- Acceptance: 关键指标回归会阻断；报告可读。

**P43 (P1) 自动 hardcase mining（从 trace/feedback 聚类）**
- Deliverables: 聚类去重、切片覆盖、候选推荐
- Acceptance: hardcase 产出稳定；人工审核成本下降。

**P44 (P1) 线上 SLO：延迟/成本/失败率/质量代理指标**
- Deliverables: dashboards + alerts + runbooks
- Acceptance: 能定位问题层级（ingest/index/retrieval/rerank/LLM）。

**P45 (P1) Replay：线上请求回放到离线评估**
- Deliverables: request capture（PII-safe）+ deterministic replay
- Acceptance: 任意 leaderboard run 可回放/复现。

**P46 (P1) 多租户配额与限流（dataset/account 维度）**
- Deliverables: quota policy + enforcement + 观测
- Acceptance: 防止滥用与成本失控。

**P47 (P1) SSO + RBAC（最小权限）**
- Deliverables: OIDC/SAML、角色/权限矩阵、审计
- Acceptance: 企业客户可落地；审计完整。

**P48 (P2) 数据生命周期：导出/删除/保留策略**
- Deliverables: data export + delete workflows + retention
- Acceptance: 合规要求可配置；不会遗漏数据副本。

**P49 (P2) 加密与密钥管理（at-rest/in-transit）**
- Deliverables: encryption policy + KMS integration（可选）
- Acceptance: 满足企业安全基线。

**P50 (P2) 部署形态打包（单机/集群/云）+ 灾备**
- Deliverables: helm/compose、HA、备份恢复演练
- Acceptance: 标准化交付与运维手册。

---

## 4) 下一步建议（从现在开始怎么推进）

1. **先打 Wave2（P01/P02/P03）**：把召回做成“工业级候选池”，否则后面的 LTR/Guardrails 都是空中楼阁。
2. 同步把 **EvidenceSuite → RegressionGate** 跑通（P41/P42），确保质量闭环真正可用。
3. 规划并落地“运行可观测 + 成本预算”（P44/P46），避免进入“越做越慢越贵”。

如果你希望，我可以把以上 50 个项目自动转成 `bd` issues（带 parent/依赖/优先级/延期策略），并给出 Wave2 的详细实施计划文档（TDD 细拆到可执行任务）。

