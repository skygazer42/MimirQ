# MimirQ 对标顶尖知识库功能差距 Roadmap(2026-05-19)

## Context

**为什么写**:已有 `plans/rag-system-landscape-2026-q2-supplement.md`(2026-05-07,11 家商业 + 12 家开源 RAG 11×11 横向矩阵)给出战略层结论 "工程深度业界第一梯队 / 差距在商业化包装",但**该 plan 焦点是护城河战略**,未把"功能层差距"落到可排期的开发任务。本 plan 补这一层:把"快被追平 / 真空白 / 商业化包装"三类差距映射到 P0/P1/P2 可执行 roadmap,串联 27 份既有调研 plan 的落地次序。

**与既有 27 份 plan 的关系**:**不重复细节**,本 plan 仅做 ①功能空白识别(未立 plan 的)②已立 plan 的优先级排期 ③对外可 quote 的功能完整度矩阵。

**对标基线**:Glean(企业搜索王者)/ Notion AI(用户体验)/ M365 Copilot(工作流嵌入)/ Vectara(SaaS 标准)/ Coze + 通义 + 阿里云百炼 + 钉钉企微飞书(中文生态)/ Harvey(垂直合规)。

**核心论断**(沿用 system-landscape):
- **真正不可拷贝**(★★★★★):行业规则库 / POC 运营 know-how / KG 影响分析
- **快被追平**(★★★):解析栈 / Agentic / 评测严谨
- **真空白**(★):联邦 / 视频 / 流式 / 合规 / Agent+RAG / 边缘 + **MCP Server / Agent Studio / Connector 生态 / 数据治理三件套**(本 plan 新识别)

---

## 主题 A:快被追平的能力(需主动量化 + 对外 SLA)

### A-1 DeepDoc 解析 API 化(对标 Reducto / Mistral OCR)
- **现状**:`plans/deepdoc-api-productization-2026-q3.md` 已有完整 P1-2 plan(425 行 / 4-6 月)
- **关键功能**:3 档解析模式(fast/accurate/table-focused)+ Python+Node SDK + 4 套餐 + playground
- **差距感受**:Reducto 已上 Series A($45M),Mistral OCR 走开源策略;我们 ~5300 行 vision 栈躺仓库
- **落地次序**:P1(本季度后期启动)
- **依赖**:无,可独立启动

### A-2 Agentic 协议标准化(对标 OpenAI Agents SDK / Anthropic Computer Use / MCP)
- **现状**:`workflows/`(2370) + `agents/`(1390) + `tools/`(1647)~5400 行,在第一梯队,**但未对接业界协议**
- **业界趋势**:OpenAI Agents SDK 2025 H2 GA / MCP 已成跨厂商标准 / LangGraph 2026 引入 multi-agent supervisor
- **关键功能**:
  - tools 暴露为 MCP server(让 Claude Desktop / Cursor / Cline 直接调用 MimirQ 知识库)
  - workflows 暴露为 OpenAI Agents SDK Function Tools
  - 兼容 LangGraph Studio 可视化调试(对接 OTel span)
- **落地次序**:P0(本季度,与 B-4 合并)
- **依赖**:OTel 埋点先行(对照 `plans/rag-visualization-deep-dive-2026-q2.md` P0)

### A-3 评测可量化对外暴露(对标 Vectara HHEM-2.0 / DeepEval / TruLens)
- **现状**:后端评测栈 ~3000 行 + 前端 ~3000 行,但**对外暴露的 metric 仅 3 个**;客户看不到"为什么这个答案可信"
- **业界对照**:Vectara HHEM-2.0 是行业默认 hallucination SLA;DeepEval 提供 SaaS dashboard
- **关键功能**:
  - `plans/rag-evaluation-deep-dive-2026-q2.md` P0 已规划 12+ metric 选择器 + Citation 评测 + Atomic Fact
  - 本 plan 补 ①每答案"可信度卡片"(faithfulness / citation coverage / atomic fact precision)对前端透出 ②客户可下载 HTML 评测报告(沿用 snapshot/precheck FILE_A023 三原则)
- **落地次序**:P0
- **依赖**:Citation 真护城河应优先

---

## 主题 B:功能真空白(待开新)

### B-1 联邦 RAG(P1)
- **场景**:跨企业 / 跨子公司私域数据汇聚,数据不出本地但联合检索
- **业界**:Glean Federated Search / Microsoft Search;**国内央企刚需**(集团总部检索各子公司知识)
- **技术路径**:联邦学习不必,只需 federated retrieval —— 各子公司部署轻量 retrieval node + 总部 coordinator 做 RRF 融合
- **关键功能**:`app/rag/federated/` 新模块,~2500 行,3-4 月
- **落地次序**:P2 — **等首个央企客户**(决策门槛:>= 1 客户付费意向 ¥150 万+)
- **依赖**:`plans/rag-edge-deployment-2026-q3.md` 政务专网部署作为前置

### B-2 合规自动化(P1-1 已有 plan)
- **现状**:`plans/rag-compliance-automation-2026-q3.md` 完整 plan(476 行 / 3-4 月)
- **杀手场景**:条款比对 / 红线检测 / 合规报告生成 / 法规版本追溯 + KG 影响分析(B-7 的副产物)
- **商业模式**:SaaS ¥30-80 万/年 + 私有化 ¥200-500 万 + 行业版本
- **落地次序**:P1(决策门槛 = 2-3 律所付费意向)
- **依赖**:法规条款级 parser + LegalArticle KG schema

### B-3 视频 RAG(P2)
- **现状**:`plans/rag-video-rag-2026-q3.md` 调研 plan(306 行)
- **判断**:**真商业价值 80% 在会议视频文字化+检索**(M365 在做),其他场景商业价值有限
- **落地次序**:P2 — **等客户主动询问**(不预先全栈布局)
- **MVP 形态**:仅 ASR + 文本 RAG,复用现有栈,~800 行 1-2 周可交付

### B-4 MCP Server 化(P0,本 plan 新识别为 P0 不在原 27 份中)
- **背景**:MCP(Model Context Protocol)已成 Anthropic / OpenAI / Cursor / Cline / Continue 跨厂商标准。**知识库不是独立网站,是嵌入工作流的能力**(MEMORY 中已警示这是产品化错位)。
- **业界对照**:Glean / Notion / 钉钉 / 飞书 / 企微 全部走"嵌入工作流"路线;独立网站是过时形态
- **关键功能**(~800 行 / 2 周):
  - `app/mcp_server/` 暴露 4 个 tool:`search_kb` / `get_document` / `submit_feedback` / `list_industry_rules`
  - 支持 stdio + SSE + streamable HTTP 三传输
  - 自动鉴权(沿用 JWT)+ 按用户 ACL 过滤
  - Claude Desktop / Cursor / Cline 配置文档 + 截图
  - 同时暴露为 ChatGPT Custom GPT Action(OpenAPI schema)
- **落地次序**:**P0(本 plan 最高 ROI 项)** —— 一周内可让客户的研发团队在 Cursor 里直接调用 MimirQ
- **依赖**:无,可立即启动

### B-5 Agent Studio 配置 UI(P2,本 plan 新识别)
- **背景**:Coze / 通义万相 / 阿里云百炼 / Dify 等"用户自建 agent"配置 UI 已成中文生态标配。我们只能开发者写代码
- **关键功能**(~3000 行 / 6-8 周):
  - 前端拖拽 UI:tools 节点 / retrieval 节点 / LLM 节点 / output 节点
  - 配置式 prompt + few-shot example 录入
  - 一键发布为 MCP server(对接 B-4)+ HTTP endpoint
  - 模板市场(行业 agent 预置)
- **落地次序**:P2 — **等行业规则库产品化**(C-1)成功后再做
- **依赖**:B-4 MCP server / C-1 行业规则库

### B-6 Connector 生态前 5(P1,本 plan 新识别为高优先级)
- **现状**:`ConnectorBase` ABC 已存在(`app/connectors/base.py:11`),但**只有 db 一种实现**
- **业界标配**:LlamaIndex 280+ connectors / LangChain 200+ / R2R / Cognita 都有几十个
- **优先级前 5**(MEMORY 中 system-landscape 已列):
  - SharePoint(微软生态客户必备)
  - Confluence(技术团队标配)
  - Notion(中小企业新晋标配)
  - GitHub(代码 + issue + wiki)
  - S3 / 阿里云 OSS(对象存储)
- **关键功能**(每个 ~800 行 / 2 周,合计 10 周):
  - 增量同步 + 删除事件 + ACL 同步(关键 — 大多数开源 RAG 不做 ACL 同步)
  - 失败重试 + checkpoint resume(`app/connectors/db/` 已有模式可复用)
- **落地次序**:P1,先 SharePoint + Confluence(企业客户需求量最大)
- **依赖**:无

### B-7 数据治理三件套(P1-P2,本 plan 新识别)

#### B-7.1 数据血缘实时可视化(P1)
- **现状**:`plans/rag-kg-snapshot-deep-dive-2026-q2.md` 已有 P0 影响分析(BFS k-hop),但是"快照-时刻"而非实时
- **差距**:Atlan / Collibra / Microsoft Purview 提供实时数据血缘 dashboard
- **关键功能**:实时 lineage(document → chunk → embedding → answer)沿用现有 OTel span,新增 lineage viewer UI
- **落地次序**:P1
- **依赖**:OTel 埋点(rag-visualization plan P0)

#### B-7.2 知识冲突自动检测(P1)
- **场景**:同一概念在多份文档中描述不一致 → 自动告警(法规修订 / 内部流程更新典型)
- **业界对照**:Glean / Notion 都做"document conflict detection"
- **技术路径**:同 entity 多 chunk 余弦相似度 < 阈值时触发 LLM 判定;复用 `app/rag/kg/extraction/` entity linking
- **关键功能**(~600 行 / 2 周):`app/rag/governance/conflict_detector.py` + 前端 `/governance/conflicts` 页面
- **落地次序**:P1(对合规客户 B-2 价值倍增)
- **依赖**:KG entity linking 已有

#### B-7.3 知识过期检测(P2)
- **场景**:法规版本更新 → 自动 invalidate 旧引用 / 合同模板版本变更 → 通知用户
- **业界对照**:Harvey / CaseText 把此作为律所核心卖点
- **技术路径**:文档 metadata 加 `valid_until` + `supersedes_doc_id`,定时任务扫描,触发 quarantine
- **关键功能**(~400 行 / 1 周):复用现有 quarantine 流水线(`/knowledge/quarantine` 页面已有 2802 行 UI)
- **落地次序**:P2
- **依赖**:`/knowledge/quarantine` 重构(健康度 plan A-P1)

---

## 主题 C:商业化包装(护城河变现)

### C-1 行业规则库产品化(P0,已有 plan)
- **现状**:`plans/industry-rules-productization-2026-q2.md`(483 行)— **后端 60% 已完成 + 前端 0% + router 注入 0%**
- **落地次序**:**P0 最优先**(本月可交付)
- **预期效果**:跟客户演示时可现场创建术语映射 + 实时 preview 改写效果,从"演示能力"变"演示资产"

### C-2 中文 benchmark 跑基线(P0,已有 plan)
- **现状**:`plans/cn-benchmark-baseline-2026-q2.md`(438 行)— CRUD-RAG + C-MTEB-zh + Chinese FinQA + 自建中文金融 50 题
- **落地次序**:**P0**(与 C-1 并行,1 周可完成)
- **预期效果**:销售可 quote 硬数字 "我们在 CRUD-RAG 上 nDCG@10 = X.XX,优于 Y / 持平 Z"

### C-3 POC 运营 know-how 产品化(P1,本 plan 新识别)
- **现状**:`plans/rag-poc-attribution-framework-2026-q2.md`(650 行)+ `plans/rag-pre-poc-scanner-2026-q2.md`(650 行)+ `plans/rag-poc-to-mvp-delivery-2026-q2.md`(900 行)已有 ~2200 行积累
- **差距**:这些都是**内部方法论**,未做成"客户可复用的工具包"
- **关键功能**(~1500 行 / 3 周):
  - POC kickoff template(30 分钟填表 + 反例清单 + 数据脱敏样例)
  - 5 字段埋点 SDK(JS + Python)给客户嵌入
  - "POC 报告生成器"自动产出客户视角 PDF(沿用 FILE_A023 三原则)
  - 三分类归因 dashboard 模板
- **落地次序**:P1 — 与 C-1 完成后启动
- **商业模式**:与"行业规则库"打包 SKU 卖给中型客户(¥30-80 万)

### C-4 SLA / 计费 / 多租户结算(P1,本 plan 新识别)
- **现状**:**0 → 1 真空**;`app/tenants/` 已有租户隔离基础,但无计费 / SLA 监控
- **业界标配**:Vectara / Cohere / 阿里云百炼都按 token / API 调用 / 文档数计费
- **关键功能**(~2000 行 / 6-8 周):
  - 计费 metering(对接 OTel)
  - SLA monitor(p50/p95 latency / availability / error rate)+ 告警
  - 用量 dashboard + 月度账单 PDF
  - Stripe / 支付宝 / 微信支付集成
- **落地次序**:P1 — 与 A-1 DeepDoc API 化绑定(SaaS 模式必需)
- **依赖**:无,可独立启动

---

## 优先级矩阵 × 排期

### P0(本季度 Q2,2026-05~2026-06)
| ID | 任务 | 工作量 | 已有 plan | 启动条件 |
|---|---|---|---|---|
| C-1 | 行业规则库产品化 | 1 周 | ✓ | 立即 |
| C-2 | 中文 benchmark 基线 | 1 周 | ✓ | 立即(可与 C-1 并行) |
| B-4 | MCP Server 化 | 2 周 | ✗(本 plan 新增) | 立即 |
| A-3 | 评测可量化对外暴露 | 2-3 周 | 部分 | C-1 完成后 |
| A-2 | Agentic 协议标准化 | 2 周 | ✗(本 plan 新增) | 与 B-4 合并 |
| **P0 合计** | **~5-6 周** | | | |

### P1(下季度 Q3,2026-07~2026-09)
| ID | 任务 | 工作量 | 已有 plan |
|---|---|---|---|
| A-1 | DeepDoc API 化 | 8 周 | ✓ |
| B-2 | 合规自动化 | 8 周(条件触发) | ✓ |
| B-6 | Connector 前 5 | 10 周 | ✗(部分调研) |
| C-3 | POC know-how 产品化 | 3 周 | 部分 |
| C-4 | SLA / 计费 / 多租户 | 6-8 周 | ✗(本 plan 新增) |
| B-7.1 | 数据血缘实时 | 3 周 | ✗(本 plan 新增) |
| B-7.2 | 知识冲突检测 | 2 周 | ✗(本 plan 新增) |

### P2(年内 Q4,2026-10~2026-12)
| ID | 任务 | 工作量 | 已有 plan |
|---|---|---|---|
| B-5 | Agent Studio | 6-8 周 | ✗(本 plan 新增) |
| B-1 | 联邦 RAG | 12 周(客户驱动) | ✗(本 plan 新增) |
| B-3 | 视频 RAG MVP | 2 周(客户驱动) | ✓ |
| B-7.3 | 知识过期检测 | 1 周 | ✗(本 plan 新增) |
| - | 边缘部署 / 政务专网 | 8-12 周 | ✓ |

---

## 决策门槛(每个任务的"是否启动"客观信号)

| 任务 | 启动门槛 | 砍掉条件 |
|---|---|---|
| C-1 行业规则库 | 无 — 后端已 60% | — |
| C-2 中文 benchmark | 无 | — |
| B-4 MCP Server | 无 — 业界已标准化 | — |
| A-3 评测暴露 | 无 | — |
| A-1 DeepDoc API | ≥ 1 SaaS PoC 客户 | 内部 OmniDocBench-CN 显示弱于 Mistral OCR |
| B-2 合规自动化 | 2-3 律所/法务部门付费意向 | 无客户进展 |
| B-6 Connector 前 5 | 客户列出 top 需求 | SharePoint 之外都无问 |
| C-3 POC know-how | C-1 + C-2 完工 | — |
| C-4 SLA/计费 | 启动 SaaS 形态(配合 A-1) | 全部走私有化 |
| B-1 联邦 RAG | ≥ 1 央企/集团客户付费意向 ¥150 万+ | 无 |
| B-3 视频 RAG | 客户主动询问 | 永不主动启动 |
| B-5 Agent Studio | C-1 成功 + 用户反馈"想自建 agent" | C-1 卖不动 |

---

## 与 27 份既有 plan 的去重声明

| 本 plan 任务 | 既有 plan | 本 plan 增量 |
|---|---|---|
| C-1 | industry-rules-productization | 仅排期,不重写细节 |
| C-2 | cn-benchmark-baseline | 仅排期 |
| A-1 | deepdoc-api-productization | 仅排期 |
| B-2 | rag-compliance-automation | 仅排期 |
| B-3 | rag-video-rag | 仅排期 |
| A-2 | (无)| **本 plan 新增** |
| A-3 | rag-evaluation-deep-dive 局部 | 补"对客户暴露"维度 |
| B-1 | (无)| **本 plan 新增** |
| B-4 | (无)| **本 plan 新增,P0 最高 ROI** |
| B-5 | (无)| **本 plan 新增** |
| B-6 | system-landscape 提到但未立 plan | **本 plan 拓展** |
| B-7.1/2/3 | (无)| **本 plan 新增** |
| C-3 | poc-attribution + pre-poc-scanner + poc-to-mvp 局部 | 补"产品化包装" |
| C-4 | (无)| **本 plan 新增** |

**本 plan 净新增**:**A-2 / B-1 / B-4 / B-5 / B-7.1 / B-7.2 / B-7.3 / C-4** 共 8 项功能空白未在 27 份 plan 中详述。

---

## 验证(每个季度末客观信号)

### Q2 末(2026-06-30)验证
- 客户演示 deck 增加"行业规则库"+ "中文 benchmark 数字"+ "MCP Server in Cursor demo"3 张 slide
- 至少 1 个外部开发者通过 MCP Server 接入 MimirQ
- 评测 dashboard 对客户开放查看 ≥ 8 个 metric

### Q3 末(2026-09-30)验证
- DeepDoc API 开放公测 + 10+ 开发者注册
- Connector 至少接入 SharePoint + Confluence 真实客户
- SLA dashboard 上线,有 ≥ 3 个客户在用计费

### Q4 末(2026-12-31)验证
- 至少 1 个 P2 真空白功能上线(Agent Studio MVP / 联邦 RAG MVP / 视频 RAG MVP 任选)
- 对外可 quote 的功能矩阵 vs Glean / 阿里云百炼 的"持平 / 优于 / 落后"评分

---

## 不在本 plan 范围

- **代码健康度**(已在 `plans/code-health-audit-2026-q2.md`)
- **既有 27 份 plan 的实现细节**(本 plan 仅排期 + 决策门槛,不重写)
- **学术调研**(已在 rag-deep-research 系列覆盖)
- **批量调研型 plan**(本 plan 是 roadmap 整合,不是新调研)

---

## 一句话总结

**MimirQ 不缺能力,缺商业化包装与跨工作流嵌入。Q2 三件事:把已建的护城河变现(C-1 + C-2),把 MCP Server 化为入场券(B-4)。8 项新识别功能空白(A-2 / B-1 / B-4 / B-5 / B-7.1/2/3 / C-4)是未来 6 个月的真正待开 plan。**
