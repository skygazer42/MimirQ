# Retrieval-Only RAG 与顶尖系统差距快照（KG-Centric）

**Date:** 2026-02-24

## 范围与共识（避免跑偏）

本项目的核心定位是 **retrieval-first / evidence-first**：

- 平台主要输出 “召回文本 / 证据”（`citations`）
- 不以 “回答编排/工作流生成” 为主（LangGraph/Agent 只作为可选上层）

因此本文只讨论与顶尖 RAG 系统相比，在 **检索召回、重排、KG 参与检索、评测回归门禁、可观测性、性能** 等方面的差距。

---

## 已具备的能力（作为基线）

以下能力在 MimirQ 中已存在或已具备可用脚手架：

- **Retrieval-only Evidence API**：`POST /api/v1/rag/retrieve` 返回 `citations` + `metrics` + `query_debug`（schema 化）。
- **Hybrid Retriever**：dense vector + in-memory BM25，支持 `linear` / `RRF` 融合。
- **Persistent lexical fallback**（Postgres FTS + pg_trgm）：对代码、token、版本号等召回假阴性有明显兜底价值（见 `docs/guides/lexical_fallback.md`）。
- **可控的 query enhancement**（可关可开）：
  - query rewrite
  - alias/dict expansion
  - multi-query / HyDE / decomposition（bounded）
- **KG 辅助检索**：
  - KG query expansion（`kgq` 角色）
  - KG chunk injection（`kg` 角色）
  - KG diagnostics（面向 hardcase 的 one-eval 风格诊断）
- **回归门禁与离线评测**：
  - regression case bundle（`mimirq.regression_cases.v1`）
  - retrieval-only gate（Recall/Hit/MRR/NDCG + abstain）可用于 CI（见 `docs/guides/regression_gate.md`）

---

## 与顶尖 Retrieval RAG 系统的差距（重点）

这里的 “顶尖” 以常见企业级检索平台能力为参照：多阶段候选生成 + 精排、可回归评测、在线观测闭环、工程化可扩展。

### 1) Sparse 检索仍缺 “生产级 SPLADE / Learned Sparse”

现状：
- 已有 sparse channel 脚手架，可参与 fusion，但目前提供的是 deterministic provider（为测试/管道打通服务）。

差距：
- 缺少生产级 SPLADE 模型（transformers / ONNX / batching）及其：
  - index 构建与持久化（而不是随 BM25 内存索引生命周期）
  - multilingual / domain 适配与评测基线
  - 量化、召回速度与内存成本控制

影响：
- 对 acronym/拼写变体/领域同义词的召回上限不如 learned sparse。

### 2) Late-interaction（ColBERT 系列）仍缺真实索引与检索栈

现状：
- 已提供 ColBERT-style late-interaction reranker 的 deterministic 脚手架（用于 API/特征/测试闭环）。

差距：
- 真实 ColBERT 系统一般包含：
  - token-level embedding 的索引结构（FAISS/PQ/IVF 等）
  - 近似检索与分段 maxsim 的高性能实现
  - 训练与蒸馏（通常从 cross-encoder 监督）

影响：
- 对 “短 query 精确证据定位” 的精排上限受限。

### 3) LTR（Learning-to-Rank）缺少 end-to-end 训练闭环与线上治理

现状：
- 已有 xgboost LTR reranker provider（`ltr`）与离线训练脚本入口（从回归用例集生成训练数据）。

差距（生产级常见要求）：
- 真正的 LTR 通常需要：
  - query group（按 query 分组的 pairwise/listwise objective）
  - hard negative mining（从失败案例或曝光日志挖掘）
  - 线上特征一致性与版本治理（feature store / model registry）
  - 自动化评测与回滚策略（A/B + SLO gate）

影响：
- 目前更像 “可用的骨架”，可插拔但距离规模化优化还差数据闭环与治理。

### 4) KG 的优势仍未充分转化为可学习的 ranking 信号

现状：
- KG 已参与：query expansion 与 chunk injection，并具备 evidence_required 等质量开关。

差距：
- 顶尖系统会把 KG 变成稳定特征源，例如：
  - 节点/路径特征：PageRank、最短路径长度、共现强度、relation type/置信度
  - 证据锚定质量特征：是否有 span、引用密度、跨文档一致性
  - “KG 召回阶段 vs 文档召回阶段” 的统一去重/融合策略

影响：
- KG 目前更偏 “候选扩展器”，而不是 “可学习的精排信号放大器”。

### 5) 评测与线上可观测：还缺更强的 “持续优化” 基建

现状：
- 有 regression cases/gate、retrieval-only 指标、KG diagnostics。

差距：
- 顶尖系统通常还有：
  - 统一的 leaderboard（按 slice：文件类型/语言/质量/命中通道/是否 KG 注入等）
  - 线上日志采样到离线评测集（半自动闭环）
  - 低基数 Prometheus 指标 + dashboard（P95 latency、top score 分布、abstain_rate、hit@k）

影响：
- 能做回归，但 “持续优化速度” 仍受工具链影响。

---

## 本次优化扫荡（2026-02-24）已补齐/已落地内容

本次扫荡的重点是：**保持默认行为不变**，新增能力全部 behind flags，并补齐 deterministic tests。

- Evidence retrieval-only 指标 gate（Recall/Hit/MRR/NDCG）与离线回归门禁测试。
- Sparse channel（SPLADE-style）+ deterministic provider（synonym 扩展）+ fusion 支持。
- ColBERT late-interaction reranker 脚手架 + provider wiring + 单测。
- LTR (xgboost) reranker：
  - 稳定 feature spec（包含 KG/role one-hot）
  - provider + 单测
  - 从 regression cases 通过 Evidence API 生成训练数据并训练模型的脚本
- Evidence orchestrator 支持 post-fusion rerank（用于 retrieval-only Evidence API 场景的后置精排实验）。

---

## 后续建议（建议以 bd issues 形式拆分跟进）

如果目标是继续逼近 “顶尖检索平台”，后续优先级建议：

1. 生产级 SPLADE provider（模型加载、batching、持久化索引、CI 基线）。
2. 生产级 ColBERT 栈（索引构建、近似检索、端到端评测与性能预算）。
3. LTR 训练闭环：
   - query-group 的 pairwise/listwise 训练
   - hard negative mining
   - feature/version 治理与线上 A/B
4. KG 特征工程：
   - path/graph 特征
   - evidence anchoring 的质量特征
   - KG 与文档召回的统一融合策略与解释输出

