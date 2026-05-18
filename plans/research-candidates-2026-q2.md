# MimirQ 仍值得调研的方向清单（2026 Q2-Q3）

> 现状：plans/ 目录已有 **51 份 plan**，覆盖 RAG 主战场（检索 / 解析 / 切块 / 评测 / 安全 / 反馈 / KG / Agentic / POC 运营 / 行业规则 / DeepDoc 二开 等）。本份用于**盘点剩余仍值得做 deep dive 的方向**，给每条主题：① 现状契合度 ② 缺什么 ③ 调研价值 ④ 预期产出 ⑤ 优先级；让用户挑选下一份 plan 的目标。
>
> 创建日期：2026-05-18
> 来源：扫描 `plans/` 全部 51 份 + 对比 `app/` 各模块代码量与 gap
> 性质：**调研选题清单**，不是实施计划；用户选定后再单独立 deep dive plan
>
> **核心论断**：MimirQ 已经完成"产品广度"调研（51 份 plan 跨 RAG / KG / 安全 / 评测 / 商业化），剩下值得调研的多偏向 **"工程深度"与"商业化基础设施"**——多租户隔离 / Citation 精度 / Connector 生态 / 成本治理 / SLO 体系 / LLM 路由 / MCP 输出 等 18 个候选，按 P0/P1/P2 排序后挑选。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 已有 51 份 plan 的覆盖矩阵（避免重复立项） |
| 第 2 章 | 仍值得调研的候选清单（18 个候选 × 优先级） |
| 第 3 章 | P0 候选 4 项（明显空白 + 高商业价值） |
| 第 4 章 | P1 候选 7 项（中等优先 / 重要不紧急） |
| 第 5 章 | P2 候选 7 项（重要但可等） |
| 第 6 章 | 主题优先级矩阵（客户拉力 × 工程价值 × 差异化） |
| 第 7 章 | 用户决策入口（请挑选 1-3 项立项） |

---

## 1 已有 51 份 plan 覆盖矩阵

| 主题域 | 覆盖 plan | 状态 |
|---|---|---|
| **RAG 整体** | rag-deep-research / capability-gap / gap-summary / system-landscape / worth-doing-prioritized | ✅ 已饱和 |
| **KG** | kg-deep-research / kg-diagnostics / kg-snapshot / kg-visualization | ✅ 已饱和 |
| **解析 / 切块** | parsing-chunking / parsing-frontend / chunk-preview / pageindex / multimodal-math / deepdoc-secondary / deepdoc-pipeline / data-cleaning-rules / cleaning-embedding-prompts | ✅ 已饱和 |
| **检索 / 重排** | hybrid-search-tuning / context-expansion-rerank / agentic-reasoning | ✅ 已饱和 |
| **Embedding** | embedding-models-mainstream | ⚠️ 缺 fine-tune / drift / 迁移专项 |
| **评测** | evaluation / eval-dataset / ablation / cn-benchmark-baseline | ✅ 已饱和 |
| **Agentic** | agentic-reasoning / agentic-memory / self-consistency / cross-doc-synthesis | ✅ 已饱和 |
| **POC / MVP / Onboarding** | poc-attribution / poc-to-mvp / pre-poc-scanner / precheck-frontend / industry-rules | ✅ 已饱和 |
| **安全 / 合规** | safety-compliance / compliance-automation / quarantine-frontend | ✅ 已饱和 |
| **反馈 / 闭环** | feedback-loop / feedback-frontend | ✅ 已饱和 |
| **入库 / Pipeline** | ingestion-frontend / ingest-pipeline-orchestration / auto-tagging | ✅ 已饱和 |
| **可视化** | visualization / kg-visualization | ✅ 已饱和 |
| **商业化** | deepdoc-api-productization / mimirq-vs-mainstream / industry-rules-productization / edge-deployment | ✅ 已饱和 |
| **品牌** | brand-icon-design-audit | ✅ 新增 |
| **代码质量** | fullstack-code-audit / fullstack-code-quality / STATUS_AUDIT_DETAILED | ✅ 已有 |
| **流式 / 长链路** | streaming / cross-doc | ⚠️ 长上下文专项缺 |
| **多模态** | multimodal-math-chart | ⚠️ 视频 RAG 已有调研但 audio/video 完整链路缺 |
| **Prompts** | prompts-mainstream-research / ibm-champion-blueprint | ✅ 已饱和 |

### 1.1 真正的空白区（本 plan 候选来源）

1. **多租户深度** — RLS / chunk-level ACL / Saga 删除 / 数据隔离测试
2. **Connector 生态广度** — 目前仅 `db/`，缺 SharePoint/Confluence/Notion/GitHub/S3/Drive/Box/Slack 等
3. **Citation 精度专项** — evaluation plan 称"真护城河"但无实施 plan
4. **成本治理** — `cost_tracker.py` 已有，但定价模型 / 单查询归因 / 客户报表缺
5. **LLM 路由策略** — engine `_select_llm` 已有，但任务类型 / 复杂度 / 成本权衡综合策略缺
6. **Embedding fine-tuning / drift** — 模型升级迁移路径缺
7. **Reranker fine-tuning** — 9 种 reranker 但无自训练专项
8. **MCP server 接入** — Claude / 第三方 AI agent 集成缺
9. **SLO / SLI 体系** — `metrics_sli.py` + `slo_snapshot_service.py` 已有，但完整 SLO 调研缺
10. **长上下文 RAG** — >500 页 / >1M token 文档专项缺
11. **Active Learning 闭环** — Hardcase mining 自动闭环缺
12. **A/B 实验框架** — 离线 ablation 完善，在线 A/B 缺
13. **数据生命周期 / 冷热分层** — 缺
14. **RTBF / 数据沿用追溯** — compliance plan 提及但实施细节缺
15. **错误诊断 / RCA 工具** — 缺
16. **Tenant Onboarding 自动化** — industry-rules onboarding 含模板，端到端自动化缺
17. **报告自动生成 / Insight Mining** — 缺
18. **批处理 / 离线作业框架** — 缺

---

## 2 候选清单总览（18 个）

| # | 主题 | 类别 | 优先级 | 客户拉力 | 工程价值 | 差异化 |
|---|---|---|---|---|---|---|
| 1 | 多租户深度（RLS + chunk-ACL + Saga） | 工程基础设施 | **P0** | 高 | 高 | 中 |
| 2 | Connector 生态（SharePoint/Confluence/Notion/+5） | 产品广度 | **P0** | 高 | 中 | 中 |
| 3 | Citation 精度专项 | RAG 质量 | **P0** | 高 | 高 | **高（护城河）** |
| 4 | 成本治理（Token 经济 / 单查询归因 / 报表） | 商业化 | **P0** | 高 | 中 | 中 |
| 5 | LLM 路由策略 | RAG 质量 | P1 | 中 | 高 | 中 |
| 6 | Embedding fine-tune / drift / 迁移 | 模型层 | P1 | 中 | 高 | 中 |
| 7 | Reranker fine-tune / cross-encoder 训练 | 模型层 | P1 | 中 | 高 | 中 |
| 8 | MCP server 接入 / Agent 集成 | 生态 | P1 | 中 | 中 | **高** |
| 9 | SLO/SLI 体系 + 客户 SLA | 商业化 | P1 | 中 | 高 | 中 |
| 10 | 长上下文 RAG（>500 页 / >1M token） | RAG 质量 | P1 | 中 | 高 | 中 |
| 11 | Active Learning + Hardcase mining 闭环 | 闭环 | P1 | 低 | 高 | **高** |
| 12 | A/B 实验框架（在线灰度） | 工程 | P2 | 低 | 中 | 低 |
| 13 | 数据生命周期 / 冷热分层 | 工程 | P2 | 低 | 中 | 低 |
| 14 | RTBF / Lineage 数据沿用追溯 | 合规 | P2 | 中 | 高 | 中 |
| 15 | 错误诊断 / RCA 工具 | 工程 | P2 | 低 | 中 | 中 |
| 16 | Tenant Onboarding 自动化（端到端） | 商业化 | P2 | 中 | 中 | 中 |
| 17 | 报告自动生成 / Insight Mining | 产品上层 | P2 | 中 | 中 | 中 |
| 18 | 批处理 / 离线作业框架 | 工程 | P2 | 低 | 中 | 低 |

---

## 3 P0 候选（4 项）

### 3.1 #1 多租户深度 — RLS + chunk-level ACL + Saga 级联删除

**为何 P0**：所有 B2B SaaS 的底线；MimirQ 已有多租户隔离基础（`tenant_id` 字段贯穿全栈），但**chunk-level ACL 闭环未做**（`rag-deep-research` 标为战略项 / `rag-poc-to-mvp` 中提到 Supabase RLS 无限递归踩坑用 SECURITY DEFINER 解决，但**没有专项 plan 系统化沉淀**）。

**现状盘点**：
- ✅ `tenant_id` 在 PostgreSQL 表层完整隔离
- ✅ `app/services/chat_conversation_access.py` + `document_access.py` 已有 ACL 过滤
- ⚠️ **Milvus / 向量库 chunk-level ACL 未必同步**（embedding 索引可能跨租户漏检索）
- ⚠️ RLS Saga 删除（用户离职 → 级联清理 chunk / embedding / KG / 反馈 / 审计）未系统化
- ⚠️ 多租户压力测试 / 隔离回归测试缺
- ⚠️ Supabase RLS SECURITY DEFINER 踩坑仅口头沉淀

**调研价值**：
- 客户 PoC 转生产**必问**："我们部门 A 的文档不能被部门 B 检索到"
- 等保 2.0 / 个保法明确要求"数据最小授权"
- 是 SaaS 客户尽职调查 (DD) 标配 checklist

**预期产出**（如果立项）：~500-700 行 plan
- 现状盘点：tenant_id 贯穿层 / Postgres RLS / Milvus collection 隔离 / KG 节点 ACL
- 业界对标：Pinecone Namespace / Weaviate Class / Qdrant Collection / Notion / Glean / Microsoft Purview
- 8 大缺口清单：chunk-level / KG ACL / Saga 删除 / Stale embedding 清理 / SCIM 同步 / 审计追溯 / 隔离测试 / 跨租户检索防御
- P0 落地（~1500 行代码）
- 决策门槛 / 陷阱清单

---

### 3.2 #2 Connector 生态扩展 — SharePoint/Confluence/Notion/GitHub/S3/Drive

**为何 P0**：
- `app/connectors/` 目前仅 **`db/` 一种**（数据库 introspection / catalog / privacy）
- `app/connectors/base.py` 已有 `ConnectorBase` ABC 基类（**架构就位**）
- `rag-deep-research-2026-q2.md` 战略项明确 "Connectors 前 5"（SharePoint/Confluence/Notion/GitHub/S3）但**没有专项 plan**
- 大客户的"知识"分散在 ≥5 个系统里，**没有 connector = 客户必须手动导出上传 → POC 转生产卡点**

**调研价值**：
- 直接对标 Glean（核心卖点就是 100+ connector）/ Microsoft Search / Notion Q&A
- 中国市场对应：钉钉 / 企微 / 飞书 / 金蝶 / 用友 / 蓝凌
- ACL 同步是真技术壁垒（不只是数据接入，还要"原系统权限"实时同步）

**预期产出**：~600-800 行 plan
- 业界对标：Glean / Microsoft Connectors / Atlassian / Notion / Lark Suite
- 国内连接器栈：飞书 / 钉钉 / 企微 / 金蝶 / 用友 / 蓝凌 OA / 致远
- 优先级排序（按客户拉力）：① 飞书 / 钉钉 / 企微 → ② SharePoint / Confluence → ③ Notion / GitHub → ④ S3 / Drive / Box → ⑤ Slack / Jira / Linear
- 共同 schema 设计：增量同步 / OAuth / ACL 镜像 / 大文件 / 删除事件 / Webhook
- 每个 connector ~300-500 行代码估算

---

### 3.3 #3 Citation 精度专项 — RAG "真护城河"实施 plan

**为何 P0**：
- `rag-evaluation-deep-dive-2026-q2.md` 第 8 章明确 "**Citation 是真护城河**" + "Atomic Fact 比 Faithfulness 严"
- 但**实施 plan 完全缺失**——只有评测层（怎么测）没有产线层（怎么改进）
- 客户场景："你回答里说 X，请给我看出处" → 引用错位 = 信任崩塌

**现状盘点**：
- ✅ `app/rag/engine.py` 已有 citations 字段（assistant message 表 schema 存在）
- ✅ `app/rag/components/` 含 attribution 相关
- ⚠️ Citation 与 chunk bbox 是否完整链路（PDF.js 跳转）未系统化
- ⚠️ Citation 准确率（生成的引用确实支持答案）未系统评测
- ⚠️ Atomic Fact 拆分（一句话拆 N 个原子事实分别 citation）未做

**调研价值**：
- 是企业知识库**信任体系**的核心
- 法律 / 金融 / 医疗 / 学术领域**必备**
- 直接对标 Vectara HHEM / Glean grounding / Perplexity citations

**预期产出**：~600 行 plan
- 业界对标：Vectara HHEM-2.0 / Perplexity / Glean / Bing Copilot / SciSpace / Consensus
- Citation 4 大维度：定位准确 / 内容支持 / 粒度合适 / 视觉跳转
- Atomic Fact 拆分算法（LLM-based + dependency parser）
- Citation 评测集自建（500 题 × 引用片段 GT）
- PDF.js bbox 跳转 + 高亮 / 报告导出（含可点 link）
- 实施代码 ~1500 行

---

### 3.4 #4 成本治理 — Token 经济 / 单查询归因 / 客户报表

**为何 P0**：
- `app/core/cost_tracker.py` 已存在但**调研深度不足**
- 每个 plan 都在堆能力，但**没有一份**专门讨论"每个 query 花了多少钱 / 怎么收费 / 怎么压成本"
- 客户 PoC 转生产必问："我们一年用 RAG 大概要花多少 token / 钱"
- 内部研发必须："新加的某个 enrich / agent / rerank 让单查询贵了多少"

**现状盘点**：
- ✅ `cost_tracker.py` 已有
- ✅ OTel span 部分已埋
- ⚠️ Per-tenant 月度账单视图缺
- ⚠️ 单查询成本拆解（embedding $X / LLM $Y / rerank $Z）UI 缺
- ⚠️ 成本 vs 质量 Pareto 缺
- ⚠️ Cache 命中率对成本影响量化缺
- ⚠️ 客户预算 / 配额 / 告警机制缺

**调研价值**：
- 商业化的财务底盘（无法解释成本 = 无法定价）
- 内部技术决策的依据（堆能力前先算贵不贵）
- 客户审计 / 财务对账 / 多租户分账

**预期产出**：~500 行 plan
- 业界对标：Langfuse / Helicone / Portkey / OpenAI Usage / Anthropic Console / Azure Cost Mgmt
- Token 经济模型：embedding / LLM input / LLM output / rerank / tool call / vision OCR 6 维拆解
- 成本归因：per-query / per-tenant / per-dataset / per-feature
- 配额与告警 / 多模型自动降级（高峰用 Haiku / 复杂用 Opus）
- 客户报表 UI（月度账单 + 趋势 + 异常告警）
- 实施代码 ~1000 行

---

## 4 P1 候选（7 项）

### 4.1 #5 LLM 路由策略调研

- **现状**：`engine.py:_select_llm` + `MODEL_COMPLEXITY_HISTORY_WEIGHT` 已有基础
- **缺**：任务类型路由 / 多模型 fallback / 失败重试 / 成本-质量权衡综合策略
- **预期产出**：~400 行 plan + ~600 行代码
- **关联**：与 `rag-prompts-mainstream-research` / `rag-agentic-reasoning` 协同

### 4.2 #6 Embedding fine-tuning / drift / 升级迁移

- **现状**：`rag-embedding-models-mainstream` 已有市场调研，但 **fine-tune / drift / 切换**缺
- **缺**：模型升级时旧 embedding 怎么办（重 embed 全库代价 $$$）/ 客户私有 fine-tune 流程 / drift 监控
- **预期产出**：~500 行 plan + ~800 行代码
- **关联**：与 cn-benchmark-baseline 共享评测

### 4.3 #7 Reranker fine-tuning / Cross-encoder 自训练

- **现状**：9 种 reranker 已接入 / `app/rag/reranker/` 完整
- **缺**：基于客户反馈数据的 reranker fine-tune（用 hardcase 训练）
- **预期产出**：~400 行 plan
- **关联**：与 #11 Active Learning + feedback-loop plan 强协同

### 4.4 #8 MCP server 接入 / Agent 集成

- **现状**：`rag-poc-to-mvp-delivery` 一处提及"MCP Server"作为生态集成方向，**未深化**
- **价值**：把 MimirQ 当 MCP server 输出给 Claude / Cursor / Cline 等 → **流量入口**
- **业界对标**：Anthropic MCP / OpenAI Plugins / Glean Action
- **预期产出**：~500 行 plan + ~700 行代码（实现 `mcp_server.py` + 工具暴露 + 鉴权）
- **差异化潜力高**：第一批中文 RAG MCP server

### 4.5 #9 SLO / SLI 体系 + 客户 SLA

- **现状**：`metrics_sli.py` + `slo_snapshot_service.py` + `api/v1/observability.py` 已有
- **缺**：完整 SLO 字典（检索 P95 / 召回率 / 答案质量 / 可用率 / 错误率）+ 客户合同 SLA
- **预期产出**：~450 行 plan
- **关联**：成本治理 / 多租户共享指标基础设施

### 4.6 #10 长上下文 RAG（>500 页 / >1M token）

- **现状**：`rag-pageindex-deep-dive` 部分覆盖（PageIndex tree search）/ deepdoc 大 PDF 分段已规划
- **缺**：100K-1M token **单文档**的检索 + 生成完整链路（不是切块，是大模型直接读）
- **业界对标**：Gemini 2 1M / Claude 200K / GPT-4o 128K / Llama 4 10M context
- **预期产出**：~500 行 plan
- **价值**：法律合同 / 财报 / 临床指南等"必须全读"场景

### 4.7 #11 Active Learning + Hardcase mining 闭环

- **现状**：`rag-feedback-loop` + `rag-feedback-frontend` + `poc-attribution-framework` 覆盖反馈层
- **缺**：从反馈→自动挑 hardcase→进评测集→训练 reranker / fine-tune embedding **自动闭环**
- **预期产出**：~500 行 plan
- **差异化高**：业界少有真正闭环的产品（多数停在"收集反馈"）

---

## 5 P2 候选（7 项）

### 5.1 #12 A/B 实验框架（在线灰度）

- **现状**：`rag-ablation-deep-dive` 已覆盖**离线** ablation；**在线** A/B 缺
- **缺**：feature flag / 流量分配 / 统计显著性在线计算 / 实验报告
- **业界对标**：Optimizely / Statsig / GrowthBook / GitLab Feature Flags
- **预期产出**：~400 行 plan

### 5.2 #13 数据生命周期 / 冷热分层

- **缺**：知识库内容随时间过期 / 旧文档归档 / 重新 embedding 策略
- **预期产出**：~350 行 plan

### 5.3 #14 RTBF / Lineage 数据沿用追溯

- **现状**：`rag-compliance-automation` 提及 RTBF Saga 级联
- **缺**：lineage tracking（哪个 chunk 来自哪个文档哪行）+ 删除影响域分析
- **预期产出**：~400 行 plan
- **价值**：GDPR / PIPL 合规必备

### 5.4 #15 错误诊断 / RCA 工具

- **缺**："为什么这个 query 答错了" 一键 RCA / per-query 全链 trace 钻取
- **预期产出**：~350 行 plan
- **关联**：与 visualization plan + observability 协同

### 5.5 #16 Tenant Onboarding 自动化（端到端）

- **现状**：`industry-rules-productization` 含 onboarding 模板
- **缺**：从客户首次登录 → 行业模板选择 → 文档上传 → 评测集生成 → 行业规则 mining → 第一次 demo 的**全自动化引导**
- **预期产出**：~500 行 plan

### 5.6 #17 报告自动生成 / Insight Mining

- **缺**：从知识库自动生成"行业报告 / 公司画像 / 风险摘要"等**衍生内容**
- **业界对标**：BloombergGPT / Glean Insights / Notion AI Reports
- **预期产出**：~450 行 plan
- **商业模式**：报告即服务（RaaS）增量定价

### 5.7 #18 批处理 / 离线作业框架

- **现状**：Celery 等可能已用（待核），但**调研深度不够**
- **缺**：大规模回填 / 重 embedding / KG 重建 / 评测全量重跑等离线作业的**统一框架**
- **预期产出**：~350 行 plan

---

## 6 主题优先级矩阵

```
                     工程价值
                       高
                        |
                        |
              [1]多租户  |  [3]Citation
              [6]Embed FT|  [11]Active Learning
              [7]Rerank FT|  [10]长上下文
              [9]SLO    |
                        |
        客户拉力 ─────────┼────────── 客户拉力
        低              |             高
                        |
              [13]生命周期|  [2]Connector
              [12]A/B    |  [4]成本治理
              [18]批处理 |  [16]Onboarding
              [15]RCA   |  [8]MCP
              [17]报告  |
                        |
                     工程价值
                       低
```

**差异化潜力（不在矩阵里但加权）**：
- ★★★★★：#3 Citation / #11 Active Learning / #8 MCP（首批中文）
- ★★★★：#2 Connector（ACL 同步是壁垒）
- ★★★：#1 多租户 / #4 成本 / #6 Embed FT / #10 长上下文

---

## 7 用户决策入口

请挑选 **1-3 个**主题做下一份 deep dive plan：

### 高 ROI 推荐组合

**组合 A：商业化基础设施（B2B SaaS 必备）**
- #1 多租户深度
- #4 成本治理
- #9 SLO/SLA 体系

**组合 B：质量护城河（差异化突破）**
- #3 Citation 精度
- #11 Active Learning 闭环
- #10 长上下文 RAG

**组合 C：生态扩张（拉新与流量）**
- #2 Connector 生态
- #8 MCP server 接入
- #16 Tenant Onboarding 自动化

**组合 D：模型层深化（技术深度）**
- #5 LLM 路由策略
- #6 Embedding fine-tuning / drift
- #7 Reranker fine-tuning

---

## 附录 A：单项调研产出量级估算

| 优先级 | 平均 plan 行数 | 后续实施代码行数 | 调研工期 |
|---|---|---|---|
| P0 (4 项) | 500-800 | 1000-2000 | 0.5-1 周 / 项 |
| P1 (7 项) | 400-500 | 600-1500 | 0.5 周 / 项 |
| P2 (7 项) | 350-500 | 500-1000 | 0.3-0.5 周 / 项 |

**全部 18 项做完**：调研 ~6-8 周 + 实施 ~6-12 月。**建议挑 3-5 项最关键的先做**。

## 附录 B：本 plan **不**包含的方向（已饱和或不建议）

- ✗ 又一份 RAG 综述 / capability gap（已有 4 份）
- ✗ KG 任何细分（已有 4 份）
- ✗ 解析 / 切块 / chunk-preview 任何细分（已有 5+ 份）
- ✗ 评测的任何细分（已有 4 份）
- ✗ Agentic 任何细分（已有 4 份）
- ✗ POC 运营 / 行业规则 / onboarding 模板细分（已有 4 份）
- ✗ 视频 RAG（已有 `rag-video-rag`，等客户问再启动）
- ✗ 流式响应（已有 `rag-streaming`）
- ✗ 多模态数学（已有 `rag-multimodal-math-chart`）
- ✗ 合规自动化（已有 `rag-compliance-automation`）
- ✗ 边缘部署（已有 `rag-edge-deployment`）
- ✗ DeepDoc 任何方向（已有 2 份）

---

## 附录 C：与已有 plan 的"互补关系"速查

| 候选 | 与之最相关的已有 plan | 互补点 |
|---|---|---|
| #1 多租户 | rag-poc-to-mvp / rag-safety-compliance | 这两 plan 提了 RLS 但没系统化 |
| #2 Connector | rag-deep-research / rag-system-landscape | 战略项标记但无专 plan |
| #3 Citation | rag-evaluation-deep-dive | 提了"护城河"但只在评测侧 |
| #4 成本治理 | rag-ablation-deep-dive | ablation 含成本维度但非治理 |
| #5 LLM 路由 | rag-prompts / rag-agentic-reasoning | 路由是底层 / 那两是上层应用 |
| #6 Embed FT | rag-embedding-models-mainstream | 市场调研已有 / fine-tune 缺 |
| #7 Rerank FT | rag-hybrid-search-tuning | 调参已有 / 训练缺 |
| #8 MCP | rag-poc-to-mvp（一处提及） | 完全空白 |
| #9 SLO | rag-visualization / observability | 可视化 / 观测有 / 体系缺 |
| #10 长上下文 | rag-pageindex-deep-dive | tree search 已有 / 端到端长上下文缺 |
| #11 Active Learning | rag-feedback-loop / poc-attribution | 收集已有 / 闭环训练缺 |
| #12-18 | 各自独立 | 完全空白 |

---

## 附录 D：如果要排"一年路线图"

按"做完一项产生确定性收益再做下一项"逻辑排：

```
Q2 剩余 (5 周)：
  → 选 1 个 P0：建议 #4 成本治理（最快、最直接的商业化基础）
  → 同时启动 #11 Active Learning（与 feedback-loop 协同强）

Q3 (12 周)：
  → #3 Citation 精度（差异化护城河）
  → #1 多租户深度（B2B 转生产门槛）
  → #2 Connector 生态（拉新引擎）

Q4 (12 周)：
  → #8 MCP server（流量入口）
  → #5 LLM 路由 + #6 Embedding FT（模型层综合）
  → #10 长上下文 RAG（高价值场景）

2027 Q1：
  → P2 候选按客户拉力滚动启动
```

---

> **下一步**：用户挑选 1-3 项后，告诉我具体哪个（按编号），我立即开始写对应的 deep dive plan，沿用本项目 plan 习惯的风格——业界对标 / gap 清单 / P0/P1/P2 / 落地代码估算 / Daily 拆解 / 决策门槛 / 陷阱清单。
