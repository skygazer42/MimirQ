# `/knowledge/feedback` 反馈中心前端调研 — 现状评估 + 自研深化

## Context

**触发场景**:用户从 `/knowledge/feedback` 出发,要求对**反馈中心前端**做全面调研,**约束:不引大包优先自研**。这是 RAG 运营闭环的"反馈基础设施"——业务专家日常使用即标注,差评分类驱动迭代。对齐 `poc-attribution-framework` plan 的**5 字段极简埋点**(original_query / llm_response / final_context_filenames / feedback_score / latency_total_ms)+ **差评三分类根因**(检索不到 24% / 答错 35% / 超纲 37%)+ **超纲三级验证**。

**问题**:`/knowledge/feedback` 已具规模(`page.tsx` **1238 行** + 2 个 source.test),用 TanStack Query + Dialog,**调用 `feedbackApi`** + `MessageFeedbackEnriched` 类型——前端基础设施完整,**但需对照 POC plan 严格审视**:① 5 字段是否齐全展示 ② 差评三分类是否可视化 ③ 超纲三级验证 UI ④ 行业规则库三大组件入口 ⑤ 系统可控好评率(剔除超纲)⑥ LLM 辅助标注分工 ⑦ 反馈反哺 hardcase 闭环 ⑧ 跨时段趋势。本调研以 POC plan 为对照,**全部自研**。

---

## 1. 现状盘点

### 1.1 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `page.tsx` | **1238** | 主页面 |
| `loading.tsx` / `error.tsx` | - | 状态壳 |
| `page.layout.source.test.ts` / `page.source.test.ts` | - | 测试 |

### 1.2 已具备能力(从 imports 推断)

- ✅ 用 TanStack Query (`useQuery`)
- ✅ Dialog 详情查看
- ✅ Search input + Select 过滤
- ✅ 翻页 / 刷新
- ✅ Badge 状态标记
- ✅ `MessageFeedbackEnriched` 类型(已对接后端富数据)

### 1.3 8+ 大缺口(对照 POC attribution plan)

1. ❌ **5 字段极简埋点完整展示**(original_query / llm_response / final_context_filenames / feedback_score / latency_total_ms 一行展示)
2. ❌ **差评三分类自动归因**(检索不到 / 答错 / 超纲 三类饼图)
3. ❌ **超纲三级验证可视化**(术语展开零命中 / Top1 相似度 0.3-0.5 阈值 / HyDE 反向检索零命中)
4. ❌ **系统可控好评率**(剔除超纲后真实好评率)
5. ❌ **行业规则库入口**(术语映射表 / 问题模式库 / 意图分类——产品化护城河)
6. ❌ **LLM 辅助标注**(LLM 预先归因 → 人工确认/修正)
7. ❌ **反馈反哺 hardcase 闭环**(差评自动加入 RAGAS regression set,对接 `/graph/diagnostics`)
8. ❌ **跨时段趋势**(7d / 30d 移动平均)
9. ❌ **bad case 钻取联动**(对接 ablation plan per-case)
10. ❌ **客户运营报告**(对客户证明"我们怎么处理差评")

---

## 2. 业界对标(全部排除大包)

| 工具 | 借鉴点 | 排除 |
|---|---|---|
| **Pendo / Hotjar** | 用户反馈 | SaaS 通用产品 |
| **Userpilot** | NPS | 通用 |
| **LangSmith Annotation Queue** | LLM 标注 | 商业 |
| **Promptfoo Annotation** | prompt 标注 | 偏 prompt |
| **Argilla** (开源标注) | 开源标注平台 | 全套引入太重 |
| **Doccano / Label Studio** | 标注 UI | 同上 |

**结论**:全部自研,只复用现有 echarts/recharts。

---

## 3. P0 落地任务(2-3 周)

### 3.1 5 字段极简埋点完整展示(~300 行)

**修改/新建** `web/components/feedback/feedback-row-detail.tsx`:
- 一行展示 5 字段(POC plan 极简埋点):
  - `original_query`(用户原问题)
  - `llm_response`(LLM 回答)
  - `final_context_filenames`(最终用了哪些文档)
  - `feedback_score`(用户打分:好评/差评)
  - `latency_total_ms`(延迟)
- 紧凑卡片设计,Dialog 展开看完整

### 3.2 差评三分类自动归因(~500 行)

**新建** `web/components/feedback/bad-case-attribution-pie.tsx`:
- 后端 `app/services/bad_case_attribution_service.py`(新)接收 differ
- 三分类(对齐 POC plan):
  - `检索不到`(24%)— retrieval miss(可控)
  - `答错`(35%)— generation hallucination(可控)
  - `超纲`(37%)— OOD(不可控,需剔除)
- echarts pie + 钻取列表
- 每分类显示 top-5 case + 推荐修复

### 3.3 超纲三级验证可视化(~400 行)

**新建** `web/components/feedback/oot-three-tier-verification.tsx`:
- 三级验证(对齐 POC plan):
  - **Tier 1**:术语展开零命中(query 术语扩展后仍 0 召回)
  - **Tier 2**:Top1 相似度 0.3-0.5 阈值(检索到但分数太低)
  - **Tier 3**:HyDE 反向检索零命中(假设答案的反向检索仍 0)
- 三栏 timeline,每栏显示判定依据
- 三级都过 → 标记为"真超纲"(不计入差评)

### 3.4 系统可控好评率(~200 行)

**新建** `web/components/feedback/controllable-rate-card.tsx`:
- 顶部大 KPI:`系统可控好评率 = (好评) / (好评 + 答错 + 检索不到)`(剔除超纲)
- 对比"原始好评率"(含超纲)
- 7d / 30d 趋势小图
- 这是对齐 POC plan 核心洞察

### 3.5 行业规则库入口(~600 行)

**新建** `web/app/knowledge/feedback/industry-rules/page.tsx`:
- 三大组件(POC plan 护城河):
  - **术语映射表**(同义词 / 缩写)
  - **问题模式库**(常见 query 模板)
  - **意图分类**(query intent → pipeline 路由)
- 表格 + CRUD UI
- 后端:`app/rag/industry_rules/` 已规划

### 3.6 LLM 辅助标注分工(~350 行)

**新建** `web/components/feedback/llm-assisted-annotation.tsx`:
- LLM 预先归因(差评三分类 + 严重度)
- 人工确认/修改 UI
- 对齐 POC plan 分工原则:LLM 提效率,人工保质量
- 自动 / 手动两种模式 toggle

### 3.7 反馈反哺 hardcase 闭环(~250 行)

**新建** `web/components/feedback/hardcase-feedback-loop.tsx`:
- 选中差评 case → "加入 RAGAS regression set"按钮
- 跳 `/graph/diagnostics` 触发 hardcase generator
- 形成"反馈 → 评测 → 修复"闭环
- 对接 `app/services/hardcase_discovery_service.py`(已有 467 行)

### 3.8 跨时段趋势(~200 行)

**新建** `web/components/feedback/feedback-trend-chart.tsx`:
- 折线图:每日好评率 / 差评率
- 7d 移动平均
- 异常下降告警 banner
- 与 `kg_diagnostics_trend` 协同

---

## 4. P1 任务(1 月)

### 4.1 bad case 钻取联动
- 点 case → 跳 `/evaluations/ablations/bad-cases`(对接 ablation plan)
- per-metric 失败钻取

### 4.2 客户运营报告
- "本月我们处理了 N 条差评,X% 已修复"
- 对客户证明运营透明

### 4.3 反馈维度多切片
- 按 user / domain / intent / time / parser / chunking 切片

### 4.4 标注一致性度量
- 多人标注同一 case → Cohen's κ
- 防止标注主观

### 4.5 自动化告警
- 差评率 7d MA 上升 >5% → 告警
- 与 `kg_diagnostics_trend` 共用基础设施

---

## 5. 关键文件

**修改**:
- `page.tsx`(1238,集成新组件 + 顶部加可控好评率 KPI)

**新建**(纯自研,~2800 行):
- `web/components/feedback/feedback-row-detail.tsx`(P0)
- `web/components/feedback/bad-case-attribution-pie.tsx`(P0)
- `web/components/feedback/oot-three-tier-verification.tsx`(P0)
- `web/components/feedback/controllable-rate-card.tsx`(P0)
- `web/components/feedback/llm-assisted-annotation.tsx`(P0)
- `web/components/feedback/hardcase-feedback-loop.tsx`(P0)
- `web/components/feedback/feedback-trend-chart.tsx`(P0)
- `web/app/knowledge/feedback/industry-rules/page.tsx`(P0)
- `app/services/bad_case_attribution_service.py`(后端 P0)
- `app/rag/industry_rules/`(后端 P0,已规划)

**复用**:
- `feedbackApi`(已有)+ `MessageFeedbackEnriched` 类型
- `app/services/hardcase_discovery_service.py`(467 行)
- echarts pie / line / trend
- TanStack Query

---

## 6. 验证

1. 5 字段:每行展示完整,Dialog 看 full context
2. 差评三分类:测试集中三类比例与 POC plan 24/35/37 数量级一致
3. 超纲三级:三级判定逻辑对照 POC plan 可执行
4. 可控好评率 KPI:数值与原始好评率有差异(说明剔除超纲生效)
5. hardcase 闭环:点"加入 regression"→ 后端 hardcase_discovery_service 接收
6. `pnpm verify` + 现有 source.test 全过

---

## 7. 与已有调研协同

- **`rag-poc-attribution-framework`**(锚点):本计划是其前端落地;5 字段 + 三分类 + 三级验证完整对齐
- **`rag-poc-to-mvp-delivery`**:反馈基础设施是 PoC-to-MVP 的核心(业务专家日常使用即标注)
- **`rag-evaluation-deep-dive`**:hardcase 反哺对接 RAGAS regression
- **`rag-kg-diagnostics-deep-dive`**:差评 case 联动 KG 诊断
- **`rag-ablation-deep-dive`**:per-case 钻取共享
- **`rag-visualization-deep-dive`**:bad cases 归因看板共享
- **`rag-safety-compliance-deep-dive`**:行业规则库与 OutputGuard 协同

---

## 8. 关键洞察

1. **反馈基础设施是 RAG 工程化的命脉**:对齐 PoC-to-MVP "先建反馈基础设施,再优化检索 → Prompt → 微调"
2. **差评三分类是真护城河**:不分类的好评率是误导(超纲不可控不应背锅);系统可控好评率才是真 KPI
3. **行业规则库三大组件**(术语 / 模式 / 意图)是**唯一跨企业难迁移的护城河**——产品化关键(对齐 POC plan)
4. **LLM 辅助标注 ≠ 全自动**:对齐 POC plan 分工原则,LLM 提效率人工保质量
5. **不引大包**:Argilla/Label Studio 全套都不要,自研 8 组件 ~2800 行
6. **闭环反哺 hardcase**:让差评不只是数字,而是改进的种子
7. **超纲三级验证**是业界都没做透的差异化:大多数产品把超纲算差评,我们识别后剔除

---

## 9. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- 反馈页已有 KPI 卡、趋势卡、密集反馈看板、搜索/筛选/列表摘要,能支撑运营人员快速定位差评与中立反馈。
- 后端已有 enriched feedback、hardcase discovery、POC attribution report、industry rules API 与 KG/evaluation 诊断能力,反馈数据可进入评测和归因链路。
- 当前闭环是“收集反馈 → 筛选坏例 → 反哺 hardcase/诊断/行业规则”,不是把反馈页做成通用标注平台。

明确不做:
- 暂不内置 Label Studio/Argilla 级多人标注系统、Cohen's κ 工作台或全自动 LLM 审核队列。
- 暂不在反馈页重复实现 ablation/KG/evaluation 的深度钻取页面;坏例分析仍复用现有评测和诊断工作台。

Directive: 后续反馈页只承载运营分流与坏例入口,复杂分析继续下沉到 evaluation/KG/ablation 专页。
