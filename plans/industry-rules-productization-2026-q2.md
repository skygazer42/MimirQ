# 行业规则库产品化（P0-1，2026 Q2）

> 把行业规则库（术语 / 模式 / 意图）从 *PoC 项目散落工件* 升级为 *MimirQ 一级产品能力*。基于现状（**后端 60% 已完成**，缺前端 UI + router 接入 + onboarding + 评测闭环），1 周 1200 行代码达到客户可演示的 MVP。
>
> 创建日期：2026-05-07
> 来源：`rag-system-landscape-2026-q2-supplement.md` 第 7.1 P0-1
> 论据：`rag-poc-attribution-framework-2026-q2.md` 第 7.4 节论证 *行业规则库是垂直 SaaS 真正护城河*
>
> **核心一句话**：行业规则库（术语 + 问题模式 + 意图分类）后端基础设施已就位、缺前端 UI 与运营闭环；这 1 周补完即可形成对外卖点 + 客户 onboarding 标准动作。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 现状盘点（后端 60% / 前端 0% / 流程 30% / 运营 0%） |
| 第 2 章 | 缺口清单（5 项：UI / router 接入 / onboarding / 评测 / 审核流） |
| 第 3 章 | Schema 与现状契约（不改 schema，只补外围） |
| 第 4 章 | 前端 UI 设计（3 Tab + mining 审核 + preview） |
| 第 5 章 | Router 接入路径（query_rewrite workflow / system_router） |
| 第 6 章 | 客户 onboarding 模板 + 评测闭环 |
| 第 7 章 | 1 周 daily 里程碑 |
| 第 8 章 | 验证方案 |
| 第 9 章 | 风险 + 范围之外 |

---

## 1 现状盘点

### 1.1 后端已完成（60%）

| 模块 | 文件 | 行数 | 状态 |
|---|---|---|---|
| Schema | `app/rag/industry_rules/schema.py` | 11 | ✅ `IndustryRuleset(name, glossary, patterns, intents)` dataclass |
| YAML 持久化 | `app/rag/industry_rules/loaders/yaml_loader.py` | 159 | ✅ load / list / replace / write candidates |
| Query rewrite applier | `app/rag/industry_rules/appliers/query_rewrite.py` | 17 | ✅ `expand_query_terms` 已实现 |
| 自动挖掘 | `app/rag/industry_rules/mining/auto_rules.py` | 94 | ✅ glossary / pattern / intent 候选生成 |
| API endpoints | `app/api/v1/industry_rules.py` | 145 | ✅ 已注册到 v1 router，含 CRUD + preview-rewrite |
| 示例规则集 | `app/rag/industry_rules/rulesets/industrial_control/` | — | ✅ 1 个完整 vertical（glossary / intents / patterns） |

### 1.2 前端缺失（0%）

- ❌ `web/app/governance/industry-rules/` 不存在
- ❌ 仅有 `web/components/governance-common-lines/` 和 `governance-profiles/` 两个旁路组件
- ❌ 完全无 ruleset 选择器 / 编辑器 / mining 审核 UI

### 1.3 流程接入（30%）

| 集成点 | 状态 |
|---|---|
| Query rewrite applier | ✅ `expand_query_terms` 函数已实现 |
| **System router 接入** | ❌ `system_router.py` / `self_route.py` 未调用 applier |
| **Query rewrite workflow 接入** | ❌ `app/rag/workflows/query_rewrite.py` 未调用 applier |
| 检索 orchestrator | ❌ 未在主路径注入 |

### 1.4 运营闭环（0%）

- ❌ 无客户 onboarding 模板（PoC 第一天填什么）
- ❌ 无评测闭环（mining 候选 → 人工审核 → 上线 → 评测 → 反哺 mining）
- ❌ Mining 候选目前只生成到 `glossary.generated.yaml`，没人审核流
- ❌ 无前端展示 `ruleset` 命中率 / 改写效果

### 1.5 真正剩下的 5 个空白

1. **前端 UI**（最大）：3 Tab + mining 候选审核 + preview-rewrite 实时演示
2. **Router 集成**：让 query_rewrite applier 自动注入主检索路径
3. **客户 onboarding**：PoC 第一天填什么 / 怎么填的标准动作
4. **评测闭环**：mining → review → promote → evaluate → feedback 全链路
5. **可见性**：让客户看到"这个 query 因为规则库被改写成了 X"，建立信任

---

## 2 缺口清单（5 项 → 5 个落点）

| # | 缺口 | 落点 | 工作量 |
|---|---|---|---|
| 1 | 前端 UI | `web/app/governance/industry-rules/page.tsx` + `web/components/industry-rules/*` | ~700 行 |
| 2 | Router 集成 | `app/rag/workflows/query_rewrite.py` + `app/rag/workflows/system_router.py` | ~80 行 |
| 3 | Onboarding 模板 | `app/rag/industry_rules/templates/` + 文档 | ~150 行 + docs |
| 4 | 评测闭环 | `app/rag/evaluation/poc_runner/industry_rules_eval.py` | ~200 行 |
| 5 | Trace 可见性 | 在 chat / debug UI 透出 query 改写步骤 | ~80 行 |
| **合计** | | | **~1210 行** |

---

## 3 Schema 与现状契约（不改 schema）

明确**不动** `app/rag/industry_rules/schema.py` 现有 `IndustryRuleset` dataclass。所有外围补充。

### 3.1 现有 schema 契约（必须保留）

```python
@dataclass(frozen=True)
class IndustryRuleset:
    name: str
    glossary: dict[str, list[str]]      # term → [aliases]
    patterns: list[dict[str, object]]    # 问题模式
    intents: list[dict[str, object]]     # 意图分类
```

### 3.2 现有 YAML 文件结构（必须保留）

每个 ruleset 是一个目录：
```
app/rag/industry_rules/rulesets/{name}/
├── glossary.yaml          # 已审核的术语
├── glossary.generated.yaml # mining 候选（待审核）
├── patterns.yaml
└── intents.yaml
```

### 3.3 仅扩充新字段（可选，向后兼容）

如客户场景需要，可以扩充 ruleset metadata（不进 dataclass，作为 YAML 顶级字段）：

```yaml
# glossary.yaml
metadata:
  industry: 工控售后        # 行业标签
  language: zh-CN
  reviewer: zhang.san      # 最近审核人
  reviewed_at: 2026-05-07
  source_pocs: ["poc_001"] # 来源 PoC
terms:
  授权:
    - 加密锁
    - 许可证
```

> 仅当客户场景出现时再扩，本 plan 不强制。

---

## 4 前端 UI 设计（缺口 #1，最大块）

### 4.1 路由与目录

```
web/app/governance/industry-rules/page.tsx          # 入口
web/components/industry-rules/
├── ruleset-selector.tsx        # 顶部 ruleset 切换
├── glossary-tab.tsx            # 术语 Tab
├── glossary-mining-panel.tsx   # mining 候选审核
├── patterns-tab.tsx            # 问题模式 Tab
├── intents-tab.tsx             # 意图分类 Tab
├── rewrite-preview-panel.tsx   # 实时改写预览
└── ruleset-stats-card.tsx      # 命中率 / 上线状态
```

### 4.2 三 Tab UI 草图

#### 顶部
```
[Ruleset: industrial_control ▼]  [+ 新建]   [⤵ 导入 YAML]   [⤴ 导出]
术语 14   模式 5   意图 6   |   今日命中 87 次   |   ✅ 已上线
```

#### Tab 1: 术语（Glossary）
- 主表：`Term | Aliases (chip) | 来源 | 审核人 | 操作`
- 右侧侧栏（可折叠）：mining 候选（接 `glossary.generated.yaml`）
  - 每条候选：`token | count | source | [✓ 接受] [✗ 拒绝]`
  - 接受：调 `PUT /rulesets/{name}/glossary` 加入 canonical
- 顶部：搜索 / 筛选 / 批量导入

#### Tab 2: 问题模式（Patterns）
- 主表：`Marker | 触发条件 | Followup（澄清话术）| 启用`
- 接 `patterns.yaml`，CRUD
- 例：`{markers: ["闪退","崩溃"], followup: "请提供版本、系统和崩溃前操作"}`

#### Tab 3: 意图分类（Intents）
- 主表：`Intent | Keywords (chip) | 路由策略`
- 接 `intents.yaml`，CRUD
- 例：`{name: "授权", keywords: ["授权","加密锁","许可证"], route: "kg_search"}`

### 4.3 实时改写预览（独立 Card）

```
┌─ Preview Rewrite ──────────────────────────┐
│ Input:  授权报错怎么办                       │
│ Ruleset: industrial_control               │
│ ─────────────────────────────────────────── │
│ Output: 授权报错怎么办 加密锁 许可证          │
│ ✓ 命中 1 个术语                              │
│ ✓ 命中 1 个意图：fault_troubleshooting     │
└────────────────────────────────────────────┘
```

接 `POST /preview-rewrite` 已有 endpoint。

### 4.4 复用既有 web 组件

| 既有组件 | 复用点 |
|---|---|
| `web/components/governance-profiles/` | 切换器 + 编辑面板风格参考 |
| `web/components/governance-common-lines/` | 列表风格 + 批量编辑 |
| `web/components/ui/tabs.tsx` | shadcn Tabs |
| `web/components/ui/data-table.tsx`（如有） | 表格 |
| `web/lib/api/governance.ts`（同模式） | API 客户端模式 |
| `web/components/chunk-preview/components/empty-state.tsx` | 空态参考 |

### 4.5 新增 i18n keys（zh-CN.ts）

```ts
IndustryRules: {
  pageTitle: '行业规则库',
  description: '术语 / 问题模式 / 意图，是垂直 RAG 的真正护城河',
  tabs: { glossary: '术语', patterns: '问题模式', intents: '意图分类' },
  mining: {
    title: '挖掘候选（待审核）',
    accept: '接受',
    reject: '拒绝',
    promoteAll: '批量上线',
  },
  preview: { title: '改写预览', placeholder: '输入要测试的 query…' },
  // ...
}
```

### 4.6 工作量

- ~700 行 TS + JSX（含 5 个组件）
- 1.5 day（前端工程师）

---

## 5 Router 集成（缺口 #2）

### 5.1 现状

- `expand_query_terms` 已在 `app/rag/industry_rules/appliers/query_rewrite.py:1-17` 实现
- 但未被任何 workflow 调用 ⚠️

### 5.2 接入点 A：`app/rag/workflows/query_rewrite.py`

注入到 query rewrite workflow 主路径：

```python
# 伪代码：在现有 query rewrite 流程之前调用
from app.rag.industry_rules.appliers.query_rewrite import expand_query_terms
from app.rag.industry_rules.loaders import load_ruleset, ruleset_exists

def run(query: str, ruleset_name: str | None = None) -> str:
    if ruleset_name and ruleset_exists(ruleset_name):
        ruleset = load_ruleset(ruleset_name)
        query = expand_query_terms(query, ruleset.glossary)  # 先做 industry 改写
    # ... 后续 LLM-based query rewrite 不变 ...
    return final_query
```

### 5.3 接入点 B：`app/rag/workflows/system_router.py`

利用 intents 决策路由：

```python
# 伪代码
intent = match_intent(query, ruleset.intents)  # 命中 fault_troubleshooting → tools=["kg_search"]
if intent and intent.get("route"):
    return intent["route"]
# fallback to default routing
```

### 5.4 配置与开关

- 通过 `dataset.metadata.industry_ruleset` 字段绑定 ruleset 到具体 dataset
- 通过 settings 开关：`INDUSTRY_RULES_ENABLED=true`，默认 `false` 直至客户 PoC 启用

### 5.5 工作量

- ~80 行（含 query_rewrite + system_router 两处调用 + dataset metadata 字段）
- 0.5 day

---

## 6 客户 onboarding 模板 + 评测闭环（缺口 #3 + #4）

### 6.1 客户 onboarding 模板（缺口 #3）

新增 `app/rag/industry_rules/templates/`：

```
templates/
├── README.md                    # 第一天填什么 / 怎么填
├── poc_kickoff_checklist.md     # PoC 启动 checklist
├── empty_ruleset_template/      # 空模板
│   ├── glossary.yaml.tmpl       # 含示例 + 注释
│   ├── patterns.yaml.tmpl
│   └── intents.yaml.tmpl
└── examples/
    ├── financial_research/      # 金融研究模板
    ├── insurance_claims/        # 保险理赔模板
    └── industrial_control/      # 工控（已有）
```

#### `poc_kickoff_checklist.md` 内容

```markdown
# PoC 第 1 天：行业规则库填写 checklist

## 必填项（第 1 天，30 分钟）
- [ ] 客户内部专有术语 5-10 个（"授权" → "加密锁/许可证"）
- [ ] 常见问题 3-5 类（错配 / 闪退 / 配置）
- [ ] 主要意图 3-5 个（按客户业务流程）

## 可选项（前 1 周边做边补）
- [ ] 历史工单 100 条 → 自动 mining → 审核
- [ ] 联系业务专家共建（非工程师）

## 反例（不要做）
- ✗ 试图把所有词都填进去（会过度泛化）
- ✗ 让工程师独自填（一定要业务专家）
```

### 6.2 评测闭环（缺口 #4）

新增 `app/rag/evaluation/poc_runner/industry_rules_eval.py`（~200 行）：

| 闭环步骤 | 落点 |
|---|---|
| ① Mining | 现有 `auto_rules.py` 已生成候选 |
| ② Review | 前端 UI mining 审核面板（4.2 节） |
| ③ Promote | 调 `PUT /rulesets/{name}/glossary` 加入 canonical |
| ④ Evaluate | 新建 `industry_rules_eval.py`：跑评测集，对比 *启用规则* vs *不启用* |
| ⑤ Feedback | 把命中率 / 改写准确率回写到 `rulesets/{name}/metrics.json` |
| ⑥ 反哺 mining | 命中率低的术语下次 mining 优先级提升 |

`industry_rules_eval.py` 接口（伪代码）：

```python
def run_industry_rules_evaluation(
    ruleset_name: str,
    eval_set: list[dict],  # 5 字段埋点（参照 rag-poc-attribution-framework）
) -> dict:
    """
    在评测集上对比 with-rules vs without-rules：
    - accuracy 提升 / 下降
    - 改写命中率（多少 query 被规则库改写）
    - 改写正确率（改写后是否更准）
    - 误伤率（不该改写的被改写了）
    """
    ...
```

### 6.3 工作量

- onboarding 模板：~150 行 + docs，0.5 day
- 评测闭环：~200 行，1 day

---

## 7 1 周 daily 里程碑

### Day 1（周一）—— 前端 UI 主框架
- [ ] 新建 `web/app/governance/industry-rules/page.tsx`
- [ ] `ruleset-selector.tsx` + ruleset 列表 / 切换
- [ ] 三 Tab 占位（含空态）
- [ ] 接 `GET /rulesets` 与 `GET /rulesets/{name}`

### Day 2（周二）—— 术语 Tab + Mining 审核
- [ ] `glossary-tab.tsx` 主表（CRUD + 批量）
- [ ] `glossary-mining-panel.tsx` mining 候选侧栏
- [ ] 接 `PUT /rulesets/{name}/glossary`
- [ ] 调用 `mining/auto_rules.py` 输出审核（已有 endpoint 或新增）

### Day 3（周三）—— 模式 + 意图 Tab + Preview
- [ ] `patterns-tab.tsx` + `intents-tab.tsx`
- [ ] `rewrite-preview-panel.tsx` 实时预览（接 `POST /preview-rewrite`）
- [ ] 顶部 `ruleset-stats-card.tsx` 命中率 stub

### Day 4（周四）—— Router 接入 + Onboarding 模板
- [ ] `app/rag/workflows/query_rewrite.py` 注入 `expand_query_terms`
- [ ] `app/rag/workflows/system_router.py` 注入 intent 路由
- [ ] `app/rag/industry_rules/templates/` 模板 + docs
- [ ] dataset metadata 加 `industry_ruleset` 字段（已存在则跳过）

### Day 5（周五）—— 评测闭环 + Trace 可见性
- [ ] `app/rag/evaluation/poc_runner/industry_rules_eval.py`
- [ ] 在 chat / debug UI 透出 query 改写步骤（命中术语 / 意图标注）
- [ ] 把评测结果写回 `rulesets/{name}/metrics.json`

### Day 6-7（周末）—— 测试 + 文档 + 演示
- [ ] 端到端测试：填模板 → 上线 → 改写 query → 评测对比
- [ ] 内部演示 + 反馈
- [ ] 客户 PoC kickoff 文档定稿

### 工作量分布

| 角色 | 工时 |
|---|---|
| 前端工程师 | 3 day（Day 1-3） |
| 后端工程师 | 1.5 day（Day 4-5 部分） |
| PM / 运营 | 0.5 day（Day 4 onboarding 模板 + Day 6-7 文档） |
| **合计** | **~5 day / 1 周** |

---

## 8 验证方案

### 8.1 单元测试
- [ ] `app/rag/industry_rules/appliers/query_rewrite.py:expand_query_terms` 已有测试，补：边界（空 glossary / 空 query / 多重命中）
- [ ] `app/rag/industry_rules/mining/auto_rules.py` 候选生成正确性
- [ ] `app/rag/evaluation/poc_runner/industry_rules_eval.py` with vs without 对比

### 8.2 集成测试
- [ ] `POST /api/v1/industry-rules/preview-rewrite` 端到端
- [ ] Query rewrite workflow 注入后改写正确
- [ ] System router 按 intent 决策路由

### 8.3 前端测试
- [ ] 三 Tab 切换 + CRUD
- [ ] Mining 审核 → promote 流程
- [ ] Preview 实时反应

### 8.4 端到端 demo
- [ ] 用 `industrial_control` ruleset 做演示：
  1. 输入 "授权报错怎么办"
  2. UI 显示改写为 "授权报错怎么办 加密锁 许可证"
  3. UI 显示命中意图 `fault_troubleshooting`
  4. 检索结果展示 + Citation
- [ ] 用 `financial_research` 模板做第二个演示

### 8.5 验证 metric

| Metric | 目标 |
|---|---|
| 行业术语命中率 | ≥ 60%（client 内部 query 触发改写比例） |
| 改写正确率 | ≥ 85%（人工标注 50 条改写，正确不误伤的比例） |
| 评测集 with-rules vs without | with-rules accuracy ≥ +5pt |
| Mining 审核效率 | 业务专家 30 min 审核 30 个候选 |

---

## 9 风险 + 范围之外

### 9.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 客户业务专家不愿意填 | onboarding 失败 | 用 mining 候选 + 模板降低填写成本到 30 min |
| Mining 噪音大 | 误录入低质量术语 | 必须人工审核，禁止自动 promote |
| 改写过度泛化 | 检索召回噪音变大 | 评测闭环监控误伤率 |
| 多 ruleset 切换混乱 | dataset 绑错 ruleset | 一 dataset 一 ruleset，UI 显式绑定 |
| 规则库变更未审计 | 无法追踪 who-changed-what | YAML 文件入 git（已是文件存储） |

### 9.2 范围之外（明确不做）

- 不重写 schema（保留 `IndustryRuleset` dataclass）
- 不引入 DB 表（YAML 文件存储足够）
- 不做规则版本管理 UI（git diff 即可）
- 不做多人协同编辑（PoC 阶段单人维护）
- 不做规则库市场（marketplace），后期再说
- 不做规则库自动 LLM 生成（mining + 人工审核已够）

### 9.3 不要的东西（陷阱清单）

- ❌ 不要把 `glossary.generated.yaml` 自动 promote 到 canonical（必须人工审核）
- ❌ 不要在前端做"AI 推荐填什么"按钮（鼓励懒惰，破坏 know-how 沉淀）
- ❌ 不要把 ruleset 嵌入向量库（只是 *规则* 不是检索内容）
- ❌ 不要做"规则库共享"（每家客户的规则是独有资产，**不应跨客户**）

---

## 10 与既有 plan 协同

| 既有 plan | 协同点 |
|---|---|
| `rag-poc-attribution-framework-2026-q2.md` 第 7.4 节 | 本 plan 是其落地实现 |
| `rag-poc-to-mvp-delivery-2026-q2.md` | 本 plan 的 onboarding 模板对接其客户交付流程 |
| `rag-eval-dataset-deep-dive-2026-q2.md` | industry_rules_eval.py 复用其评测集建设方法论 |
| `rag-feedback-frontend-deep-dive-2026-q2.md` | bad case 反哺 mining（feedback → 候选） |
| `rag-system-landscape-2026-q2-supplement.md` 第 5.2 节 | 本 plan 实现"真正不可拷贝护城河 #1" |
| `rag-agentic-reasoning-deep-dive-2026-q2.md` | system_router 接入意图路由 |

---

## 11 完成后输出

1. **代码**：~1210 行（700 frontend + 80 router + 150 templates + 200 evaluation + 80 trace）
2. **客户演示**：基于 `industrial_control` 的 5 分钟 demo
3. **客户 onboarding 文档**：第 1 天 30 分钟填表流程
4. **内部 SOP**：销售 + 工程的 PoC kickoff 标准动作
5. **评测报告 demo**：with-rules vs without-rules 在 1 个 PoC 客户上的对比
6. **MEMORY.md 索引项**：追加一条
