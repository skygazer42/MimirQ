# RAG Excellence 20（精细化数据→检索流水线）

目标：把 MimirQ 的核心从“会回答”进一步推向“检索工程 + 数据工程极致化”，让每一步（入库画像→预处理→全量 Markdown→治理→切块→索引/检索(+KG)→评估/回归→观测闭环）都有**可观测、可复现、可回归**的产物与指标。

> 说明：
> - 本清单不是“再做一个 LLM+RAG”，而是把现有链路打磨到“可解释 + 可运营 + 可工程化”。
> - 每项都要有：产物（结构化数据/报告）、指标（分布/TopN/分位数）、以及测试或回归门禁（DoD）。

---

## 任务列表（20）

状态标记：
- DONE：已具备可用能力 + 有测试/文档支撑
- PARTIAL：已有底座，但还缺关键产物/指标/可视化/门禁
- TODO：缺失，需要实现

1) **入库 Run Manifest（全链路运行清单）**（PARTIAL）
   - 现状：Connector 有 `connector_runs`；手动上传/批处理缺统一 run 视角。
   - DoD：任意 ingestion 都产生 run_id；run 记录 config/pipeline_hash、阶段耗时、产物指针、失败原因 TopN；支持 run 对比与回放。

2) **数据分布画像（Dataset Profiling）**（DONE）
   - 现状：Dataset Profile summary + deep scan/backfill 已具备（语言/页数/解析质量/大小等分布）。
   - DoD：已有（并持续补齐缺口字段）。

3) **画像报告（可分享/可审计）**（PARTIAL）
   - 现状：Profile/Report HTML 导出存在；但需覆盖更多关键分布与解释。
   - DoD：Profile HTML 报告覆盖：格式/状态/长度/大小/页数/解析质量/语言/切块（代理）/合规（PII/Secrets）等，并可脱敏导出。

4) **入库前校验 + 隔离区（Quarantine）**（DONE）
   - 现状：Precheck + Governance quarantine 已具备；前端有隔离队列。
   - DoD：已有（后续可做：隔离原因聚类与修复建议）。

5) **粗筛预处理（coarse sieve）**（PARTIAL）
   - 现状：preprocess steps + governance 清洗已有；但缺“面向分布”的可视化与参数建议。
   - DoD：对常见噪声（页眉页脚/TOC/boilerplate/重复段落/断行）输出 impact 指标与对比报告；可一键应用到 ingestion policy。

6) **Canonical Markdown（全量统一 Markdown 产物）**（PARTIAL）
   - 现状：`DocumentParsedContent` 持久化 original/processed markdown 已具备。
   - DoD：定义并落地 `canonical.md` 规范（标题/列表/表格/代码块等稳定格式），并确保跨解析后端可 diff、可复现。

7) **溯源映射（原文→MD→chunk）**（PARTIAL）
   - 现状：chunk/page/start/end 等字段存在；chunk-preview 已支持定位与覆盖率指标。
   - DoD：形成稳定的 provenance map（page/offset ↔ markdown span ↔ chunk_key），支持“点击引用跳原文页/段”。

8) **Markdown 治理规则引擎（Rule Packs）**（DONE）
   - 现状：rule_packs/regex_rules/governance profiles 已具备。
   - DoD：已有（后续：规则效果统计与回归用例沉淀）。

9) **质量打分 + 标签体系**（PARTIAL）
   - 现状：parse_quality、低密度/扫描 PDF/PII/Secrets 等 finding 已具备。
   - DoD：补齐统一 `quality_score`/`quality_tags`（doc/section/chunk）并在检索侧可用（过滤/降权/路由）。

10) **敏感信息检测与脱敏**（DONE）
   - 现状：PII/Secrets 检测 + mask/redact + 统计已具备。
   - DoD：已有（后续：策略回归与误报分析）。

11) **多层去重（doc + chunk）**（PARTIAL）
   - 现状：exact dup（file_sha256）+ near_dedup（simhash best-effort）+ 可选 chunk exact-dedup 已具备部分。
   - DoD：形成可解释的 dedup report（保留/丢弃理由、聚类规模、影响评估），并支持回滚/复算。

12) **切块策略模板库（按文档类型）**（DONE）
   - 现状：auto/多策略 chunker + chunk preview 已具备。
   - DoD：已有（后续：策略自动推荐与更强的结构化策略）。

13) **切块分布分析（符合要求）**（PARTIAL）
   - 已实现（2026-02-09）：Dataset Profile 新增 chunk 代理分布（chunks/doc 与 avg chars/chunk），并在 Profile 页面 + HTML 报告中展示。
   - TODO：补充“chunk-level 分布”（需要 deep scan 或入库时写入 per-doc chunk_stats）。

14) **切块参数自动调优（Auto-tune）**（TODO）
   - DoD：给定文件/策略/约束（coverage_ratio、overlap_waste、max_chunks 等），自动搜索参数并输出 TopN 推荐 + 对比报告，可一键应用。

15) **Parent-Child / Neighbor Window**（DONE）
   - 现状：parent_child + neighbor window 已具备，并在 chunk-preview 文档中说明。

16) **Embedding 版本化 + 漂移检测**（PARTIAL）
   - 现状：pipeline_hash/embedding_space_hash + provenance snapshot 已具备。
   - DoD：检测 embedding 变更/漂移（版本对比、重建建议、cache 命中率），并与回归门禁联动。

17) **混合索引与可审计打分**（PARTIAL）
   - 现状：hybrid 检索 + query_debug/evidence 已具备。
   - DoD：输出候选打分分解（BM25/向量/rerank/过滤原因）与可视化，支持“为什么这个 chunk 被选中/被丢弃”。

18) **检索画像与 SLO**（DONE）
   - 现状：retrieval_profile + 证据接口 + metrics 字段已具备。
   - DoD：已有（后续：按 dataset/pipeline_hash 细分的长期看板）。

19) **KG 抽取与 chunk 绑定（可版本化）**（DONE）
   - 现状：KG 抽取/索引/引用增强/搜索与图谱 API 已具备。

20) **KG-aware 检索 + 评估回归**（PARTIAL）
   - 现状：KG search + RAGAS + retrieval-only gate 已具备。
   - DoD：把 KG-aware 检索也纳入证据/回归集，形成可对比的“索引版本→检索质量→门禁”闭环。

---

## 执行顺序（建议）

P0（先补“可观测/可复现”底座）：1 → 6 → 7 → 13（chunk-level）→ 17  
P1（提效与自动化）：5 → 11 → 14 → 16  
P2（闭环与运营）：9 → 18（看板化）→ 20（门禁覆盖 KG-aware）

