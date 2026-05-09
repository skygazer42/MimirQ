# Feedback 自动反哺闭环（能力 P0 #5，2026 Q3）

> 把现有 *仅到存储层* 的 feedback（`MessageFeedback` 表 + `feedback_service.py`）升级为 **三路自动反哺闭环**：bad case → hard_negative_mining 训练集 / reranker fine-tune / industry_rules 候选。是 MimirQ 飞轮的根源 —— 客户用得越久，系统越准。
>
> 创建日期：2026-05-08
> 来源：`rag-gap-and-recommendations-summary-2026-q2.md` 第 5.2 节真 GAP / 用户对话 2026-05-08 聚焦能力
> 优先级：P0（能力 #5）
> 状态：**Stage 0 PASS（候选预览闭环，2026-05-08）**
> Stage 0 验收：差评 feedback 可生成 HardNeg 候选、训练三元组与 rules 候选；提供只读 API 与反馈页 summary；不自动写入训练集、不自动改 rules、不触发 fine-tune。
>
> **核心一句话**：基础设施（feedback API + hard_negative_mining 352 行 + 9 种 reranker + industry_rules mining）全部就位，但 **三者断联**；2 周 ~700 行胶水代码可让飞轮转起来。

---

## Stage 0 PASS 记录（2026-05-08）

| 项 | 结论 | 验收 |
|---|---|---|
| 负反馈候选 API | 已新增只读 `GET /feedback/loop/candidates` | `tests/test_feedback_loop_api_wiring.py` |
| HardNeg 候选 | 差评 feedback 可复用现有 mining 逻辑生成 hard negative records | `tests/test_feedback_loop_candidates.py` |
| 训练三元组 | 可从负反馈 query / positive chunk / negative chunk 生成离线 triples | `tests/test_feedback_loop_candidates.py` |
| Rules 候选 | 可基于 ruleset 输出 glossary/pattern/intent 候选，不自动生效 | `tests/test_feedback_loop_candidates.py` |
| Feedback 服务接线 | `FeedbackService` 组装真实 conversation/message/citations/retrieval_trace | `tests/test_feedback_service.py::test_build_feedback_loop_candidates_uses_negative_feedback_context` |
| 前端 summary | 反馈页展示 HardNeg、训练三元组、Rules 候选与转化率 | `web/app/knowledge/feedback/page.source.test.ts` + Playwright smoke |
| Batch dispatcher | 新增手动/定时 batch 调度入口，不监听 feedback insert | `tests/test_feedback_loop_dispatcher.py` |
| HardNeg promoter | 负反馈候选可导出 PII-safe JSONL，并保留 feedback/conversation/message/dataset lineage | `tests/test_feedback_hard_negative_promoter.py` |

Stage 0 的 PASS 含义：**候选生成、人工审核入口、受控 JSONL 导出已经打通**。这不代表 reranker fine-tune、自动 promote、Prometheus/OTel 监控已经完成。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 现状盘点（基础设施已就位但断联） |
| 第 2 章 | 三路反哺设计 |
| 第 3 章 | 落点（5 个） |
| 第 4 章 | 调度 + 监控 |
| 第 5 章 | 评测：飞轮验证 |
| 第 6 章 | 2 周里程碑 |
| 第 7 章 | 风险 + 范围之外 |

---

## 1 现状盘点

### 1.1 已有底层能力（不重做）

| 模块 | 文件 | 状态 |
|---|---|---|
| Feedback API | `app/api/v1/feedback.py` | ✅ 已有 |
| Feedback 服务 | `app/services/feedback_service.py` | ✅ 已有 |
| Feedback model | `app/models/feedback.py:MessageFeedback` | ✅ 已有（tenant + conversation + message + account 隔离） |
| Feedback Schema | `app/api/schemas/feedback.py` | ✅ |
| Hard Negative Mining | `app/rag/evaluation/hard_negative_mining.py` | ✅ 352 行（提供 mining 接口） |
| 9+ Reranker | `app/rag/reranker/`（bge_v2 / colbert / cross_encoder / dashscope / hybrid / kg / llm_based） | ✅ 已有 |
| Industry Rules Mining | `app/rag/industry_rules/mining/auto_rules.py` | ✅ 94 行 |
| 前端 Feedback UI | `web/app/knowledge/feedback/` | ✅ 已有 |

### 1.2 真正缺失的"反哺"链路

```
当前现状：
  ┌────────────┐    ┌──────────┐    ┌────────────┐
  │ User 反馈  │ →  │ DB 存储   │ →  │ 仅人工查看 │
  └────────────┘    └──────────┘    └────────────┘

期望状态：
  ┌────────────┐    ┌──────────┐    ┌─────────────────────────┐
  │ User 反馈  │ →  │ DB 存储   │ →  │ 自动反哺三路            │
  └────────────┘    └──────────┘    │  ① hard_negative ↻      │
                                    │  ② reranker fine-tune ↻ │
                                    │  ③ industry_rules 候选 ↻│
                                    └─────────────────────────┘
```

### 1.3 验证（grep 0 命中）

```bash
$ grep -rln "online_learning\|RLHF\|reward_model\|feedback_promote\|auto_finetune" app/
# (仅 evaluation 文档中提到，代码无实现)
```

### 1.4 真正缺失的 5 件事

1. **Bad case 自动归类**（feedback negative → 三类用途分发）
2. **hard_negative 自动 promote**（feedback → mining 训练集）
3. **Reranker 增量 fine-tune 调度**（每 N 周用 feedback 微调 cross-encoder）
4. **Industry rules 自动建议**（feedback bad case → industry_rules 候选）
5. **反哺监控 dashboard**（飞轮速度可视）

---

## 2 三路反哺设计

### 2.1 总体架构

```
                  ┌────────────────┐
                  │ MessageFeedback│
                  │ (with metadata)│
                  └────────┬───────┘
                           │
              ┌────────────┼────────────┐
              ↓            ↓            ↓
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ Path 1:  │ │ Path 2:  │ │ Path 3:  │
       │ HardNeg  │ │ Reranker │ │ Rules    │
       │ Promoter │ │ Tuner    │ │ Enricher │
       └──────────┘ └──────────┘ └──────────┘
              ↓            ↓            ↓
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ JSONL    │ │ Job队列   │ │ glossary │
       │ 存储     │ │ + 训练   │ │ generated│
       └──────────┘ └──────────┘ └──────────┘
```

### 2.2 Path 1：Hard Negative 自动 Promote

**输入**：`MessageFeedback` 中评分 ≤ 2（差评）+ `final_context_filenames`（已有 5 字段埋点）

**逻辑**：
- 每条差评 → 提取 retrieved chunks
- 调用 `hard_negative_mining.py:mine_hard_negatives_for_case_from_trace`
- 加入 `hard_negatives.jsonl`
- 标记 source = "user_feedback_2026-05-08"
- 24h 后回放评测看是否真的提升 recall

**复用资产**：
- `app/rag/evaluation/hard_negative_mining.py`（352 行已有完整接口）

### 2.3 Path 2：Reranker 增量 Fine-Tune

**输入**：累积 ≥ N 条（默认 500）feedback 后触发

**逻辑**：
- 构造 (query, positive_chunk, negative_chunk) 三元组
  - positive：评分 ≥ 4 的 query 对应 chunks
  - negative：评分 ≤ 2 的 query 对应 chunks
- 用 sentence-transformers / cross-encoder 微调
- 训练完上传 minio 形成新 reranker 版本
- A/B test：新版 vs 旧版（rag-ablation 框架）
- 通过门槛后自动 deploy

**复用资产**：
- `app/rag/reranker/`（9+ 种）
- `app/rag/evaluation/`（A/B 框架）
- 现有 model registry（如有）

### 2.4 Path 3：Industry Rules 候选自动建议

**输入**：`MessageFeedback` + 现有 `industry_rules` 配置

**逻辑**：
- 差评 query → 抽取关键术语
- 与现有 `glossary.yaml` 对比，未命中的 → 候选
- 与 `auto_rules.py:_build_glossary_suggestions` 联动（已有逻辑）
- 写入 `glossary.generated.yaml` 等待人工审核
- 在 `/governance/industry-rules` UI 中显示候选（与 P0-1 协同）

**复用资产**：
- `app/rag/industry_rules/mining/auto_rules.py`（94 行已有候选生成）
- `app/rag/industry_rules/loaders/yaml_loader.py:write_glossary_candidates`

---

## 3 落点设计（5 个）

### 3.1 落点 A：核心反哺调度器

**文件**：`app/rag/feedback_loop/dispatcher.py`

**功能**：
- 监听 `MessageFeedback` insert 事件（DB trigger / event bus / 定时）
- 按反馈类型分发到三路 promoter
- 失败重试 + 死信队列

**复用**：
- `app/tasks/queue.py`（arq 已有）

**新增**：~150 行

### 3.2 落点 B：HardNegativePromoter

**文件**：`app/rag/feedback_loop/hard_negative_promoter.py`

**功能**：
- 拉取最近 24h 差评
- 转换为 hard_negative 三元组
- 写入 `evaluation/hard_negatives_user_feedback.jsonl`
- 与现有 `hard_negative_mining.py` merge

**新增**：~150 行

### 3.3 落点 C：RerankerFineTuner

**文件**：`app/rag/feedback_loop/reranker_finetuner.py`

**功能**：
- 累积 ≥ 500 条 feedback 后触发
- 微调 cross_encoder（sentence-transformers）
- 上传到 minio + 注册 model registry
- A/B 评测后自动 promote

**配置**：
```python
RAG_FEEDBACK_RERANKER_FINETUNE_ENABLED: bool = False
RAG_FEEDBACK_RERANKER_BATCH_SIZE: int = 500
RAG_FEEDBACK_RERANKER_FINETUNE_FREQUENCY: str = "weekly"  # daily / weekly / monthly
RAG_FEEDBACK_RERANKER_AB_DURATION: int = 7  # day
```

**新增**：~250 行

### 3.4 落点 D：RulesEnricher

**文件**：`app/rag/feedback_loop/rules_enricher.py`

**功能**：
- 差评 query 抽取术语
- 与 ruleset 对比 → 未命中候选
- 写入 `glossary.generated.yaml`
- 与 P0-1 行业规则库 UI 集成

**新增**：~100 行

### 3.5 落点 E：监控 dashboard

**文件**：`web/app/knowledge/feedback/loop-dashboard.tsx`

**显示内容**：
- 每月反馈数 / 差评率
- 三路 promote 数量（hard_negative / rules / reranker）
- A/B test 进度
- Recall 提升率 / Reranker MRR 提升

**新增**：~200 行

### 3.6 工作量汇总

| 落点 | 行数 | 工时 |
|---|---|---|
| A 调度器 | 150 | 2 day |
| B HardNeg | 150 | 2 day |
| C Reranker | 250 | 4 day |
| D Rules | 100 | 2 day |
| E Dashboard | 200 | 3 day |
| 测试 | 100 | 2 day |
| **合计** | **~950 行** | **~15 day / 2 周** |

---

## 4 调度 + 监控

### 4.1 调度策略

| 路径 | 频率 | 触发条件 |
|---|---|---|
| HardNeg promoter | 每 24h | 当日差评 ≥ 5 |
| Rules enricher | 每 7 天 | 累积 ≥ 50 候选 |
| Reranker fine-tune | 月度 | 累积 ≥ 500 feedback |

### 4.2 监控指标

- **反哺速度**：每月新增 hard_neg / rules / reranker 版本数量
- **质量提升**：HardNeg promote 后 recall@5 提升率
- **审核效率**：rules 候选审核率（接受 / 拒绝 / 待审）
- **A/B 通过率**：Reranker A/B 通过 promote 比例
- **客户感知**：每月差评率下降趋势

### 4.3 监控页面集成

- 接入 `app/observability/`（已有 OTel）
- 反哺事件入 audit log（已有 7 个 audit 服务）
- Prometheus rule（已有 `docs/ops/templates/prometheus-rule-mimirq.yaml`）

---

## 5 评测：飞轮验证

### 5.1 飞轮速度评测

| 时间 | 反哺前 baseline | 反哺后 |
|---|---|---|
| 第 0 周 | 70% accuracy | — |
| 第 4 周 | — | 73%（HardNeg + Rules） |
| 第 8 周 | — | 76%（+ Reranker A/B） |
| 第 12 周 | — | 78% |

预期：3 月内提升 5-10pt accuracy（线性或衰减）。

### 5.2 退出条件

| 条件 | 决策 |
|---|---|
| 4 周后无明显提升 | 复盘三路实现 |
| HardNeg 提 recall < 1pt | 反哺机制有问题 |
| Reranker A/B 不通过 | 训练数据不足或质量差 |
| Rules 接受率 < 30% | mining 算法太宽 |

### 5.3 评测 baseline 复用

- `evaluation/poc_runner/` 5 字段埋点已有
- 自建中文金融评测集（P0-2）
- CRUD-RAG（P0-2）

---

## 6 2 周里程碑

### Week 1：核心三路 + 调度

#### Day 1-2（调度器 + HardNeg）
- [x] `dispatcher.py` skeleton + 监听 feedback insert（已收窄为 manual/scheduled batch，不做实时监听）
- [x] `hard_negative_promoter.py` + 复用 mining 接口
- [x] HardNeg 端到端：差评 → JSONL 验证

#### Day 3-4（Rules enricher）
- [ ] `rules_enricher.py` 差评 → glossary 候选
- [ ] 与 P0-1 行业规则库 UI 集成（候选侧栏）
- [ ] 端到端测试

#### Day 5（Reranker fine-tune skeleton）
- [ ] `reranker_finetuner.py` 框架
- [ ] 三元组构造逻辑
- [ ] 单元测试

### Week 2：Reranker fine-tune + 监控

#### Day 6-8（Reranker 训练完整闭环）
- [ ] sentence-transformers 微调代码
- [ ] minio 上传 + model registry
- [ ] A/B 评测集成（rag-ablation 框架）
- [ ] 自动 promote 逻辑

#### Day 9-10（Dashboard）
- [ ] `loop-dashboard.tsx` 三路指标
- [ ] Prometheus 指标暴露
- [ ] OTel 埋点

#### Day 11-12（评测 + 文档）
- [ ] 飞轮速度 baseline
- [ ] 客户演示文档
- [ ] 完整 SOP

#### Day 13-14（Buffer + GA）

---

## 7 风险 + 范围之外

### 7.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Feedback 噪音大 | 反哺学到错误信号 | 评分 ≤ 2 才计为差评 + 多用户验证 |
| HardNeg 错杀正例 | 影响检索质量 | A/B 评测后才上线 |
| Reranker 过拟合 | 在用户场景过拟，跨场景退步 | 跨 dataset 评测 |
| Rules 候选噪音 | 误录入低质量术语 | 必须人工审核（与 P0-1 协同） |
| 反哺速度过快 | 模型不稳定 | 月度训练 + 7 天 A/B |
| 客户隐私 | feedback 含敏感数据 | tenant 隔离 + audit log |

### 7.2 范围之外（明确不做）

- 不做完全在线学习（每条 feedback 即时生效）—— 风险过大
- 不做 LLM 自动 fine-tune（成本太高，本期仅 reranker）
- 不做 RLHF（reward model 太重）
- 不做跨 tenant 反哺（每 tenant 独立模型）
- 不做 prompt 自动优化（DSPy 范畴）

### 7.3 不要的东西

- ❌ 不要让"赞"和"差评"权重相同（差评信号更强）
- ❌ 不要 promote 单个用户的偏好（需 ≥ 3 用户验证）
- ❌ 不要在生产直接更新模型（A/B 验证）
- ❌ 不要忽略 audit（每次反哺必须审计）

---

## 8 与既有 plan 协同

| plan | 协同点 |
|---|---|
| `industry-rules-productization-2026-q2.md`（P0-1） | Rules 候选直接进 P0-1 的 mining 审核 UI |
| `rag-feedback-frontend-deep-dive-2026-q2.md` | feedback UI 已有，本 plan 加反哺后端 |
| `rag-ablation-deep-dive-2026-q2.md` | Reranker A/B 复用 ablation 框架 |
| `rag-evaluation-deep-dive-2026-q2.md` | 反哺后评测复用统一 LLM-Judge |
| `rag-cross-doc-synthesis-2026-q3.md`（P0 #1） | 用户标"真冲突"反哺 NLI 训练 |
| `rag-self-consistency-2026-q3.md`（P0 #2） | 用户选 alternatives → 反哺 K 选择 |
| `rag-poc-attribution-framework-2026-q2.md` | 5 字段埋点是反哺数据基础 |

---

## 9 关键洞察

1. **基础设施已就位**：feedback API + hard_negative_mining + 9 reranker + industry_rules mining 全部已有，本 plan 是 *连接器*
2. **飞轮的根源**：客户用得越久 → 反馈越多 → 系统越准 → 客户越粘
3. **三路解耦设计**：HardNeg / Rules / Reranker 可独立失败、独立优化
4. **A/B 是底线**：自动反哺必须配 A/B 评测，否则盲目可能退化
5. **与 P0-1 行业规则库强协同**：Rules enricher 直接复用 P0-1 的 UI 审核流
