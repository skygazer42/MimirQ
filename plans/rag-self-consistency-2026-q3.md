# Self-Consistency K-Path 推理（能力 P0 #2，2026 Q3）

> 把现有 *单路径 reasoning*（Self-RAG / CRAG / FLARE / planner-worker）升级为 **K 路径并行 + 答案聚类 + majority voting** 的多路径 reasoning。降低 LLM 单次推理不稳定的幻觉风险，与 P0 #1 跨文档融合协同。
>
> 创建日期：2026-05-08
> 来源：`rag-gap-and-recommendations-summary-2026-q2.md` 第 5.2 节真 GAP / 用户对话 2026-05-08 聚焦能力
> 优先级：P0（能力 #2）
>
> **核心一句话**：grep `self_consistency` / `tree_of_thought` 0 命中；Self-Consistency（Wang 2022）是 LLM reasoning 最低成本最高收益的技术之一，1 周 ~400 行可让所有现有 workflow 都获得 K-path voting 能力。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 现状盘点 + 学术依据 |
| 第 2 章 | 算法设计（K-path + clustering + voting） |
| 第 3 章 | 落点设计（3 个） |
| 第 4 章 | 与现有 12 个 workflow 集成 |
| 第 5 章 | 1 周里程碑 |
| 第 6 章 | 风险 + 范围之外 |

---

## 1 现状盘点 + 学术依据

### 1.1 现有 workflow

`app/rag/workflows/` 12 个 agent：
- `crag_streaming.py`、`flare.py`、`self_rag.py`、`self_route.py`、`system_router.py`
- `planner_worker.py`、`react.py`、`evaluator_optimizer.py`、`parallelization.py`
- `chain.py`、`routing.py`、`query_rewrite.py`、`rerank_expand_rerank.py`

**全部是单路径 reasoning**（每次只生成 1 个答案 + 1 次 retrieval + 1 次 LLM）。

`parallelization.py` 名字像 self-consistency 但实际是 *并行检索*（多 retriever 并发），不是 *并行推理* 的 K-path voting。

### 1.2 学术依据

- **Wang et al. (2022) "Self-Consistency Improves Chain of Thought"**：K-path（K=5-40）+ majority voting，arithmetic / commonsense / symbolic reasoning 全面提升
- **CoT Decoding (NeurIPS'24)**：温度采样 K 路径
- **Universal Self-Consistency (Chen 2023)**：用 LLM 自己 cluster 不同答案
- **Tree-of-Thought (Yao 2023)**：分支搜索（更复杂）
- **Graph-of-Thought (Besta 2024)**：DAG 搜索

### 1.3 选型决策

**首选 Self-Consistency（不是 ToT/GoT）**：
- 实现最简单（K 个独立 LLM 调用 + 聚类）
- 学术效果验证最充分（5 年应用）
- 与现有 workflow 解耦，可作为 *wrapper* 应用到任意 workflow
- 成本可控（K=5 vs ToT 的 ≥ 20 节点）

ToT/GoT 是 P3 远期评估，本 plan **仅做 Self-Consistency**。

### 1.4 确认缺失

```bash
$ grep -rln "self_consistency\|majority_vote\|tree_of_thought\|graph_of_thought" app/
# (返回 0 命中)
```

---

## 2 算法设计

### 2.1 4 步 Pipeline

```
Step 1: 接收上游 workflow 的 query + retrieved_chunks
Step 2: K 路径并发 LLM 调用（不同 temperature / seed）
Step 3: 答案聚类（embedding 相似度 + LLM judge）
Step 4: Majority voting + 输出最终答案 + 不一致信号
```

### 2.2 步骤详解

#### Step 2：K 路径并发

- K 默认 5（可配置 3-10）
- 每路径用不同 `temperature`（[0.7, 0.8, 0.9, 1.0, 1.1]）和 `seed`
- `asyncio.gather` 并发，超时 30s
- 失败路径 fallback 到 K-1（不阻断）

#### Step 3：答案聚类

- **数值答案**：精确匹配（± tolerance）
- **短文本（< 50 token）**：embedding 相似度 ≥ 0.85 视为同簇
- **长文本（≥ 50 token）**：先 LLM 抽取 *核心 claim* 再聚类（参照 Universal Self-Consistency）
- **JSON / 结构化**：字段级别比较

#### Step 4：Majority Voting + 不一致输出

- 簇大小排序，最大簇 = majority answer
- 输出元信息：
  ```json
  {
    "answer": "...",                  // majority
    "confidence": 0.6,                // 3/5 同意 = 0.6
    "alternatives": [                  // 其他簇答案
      {"answer": "...", "votes": 1, "reasoning": "..."}
    ],
    "is_unstable": false              // 最大簇 < K/2 时为 true
  }
  ```

### 2.3 成本控制

| 维度 | 控制 |
|---|---|
| K 值 | 默认 5，复杂 query 7，简单 3 |
| Temperature 多样性 | 不重复 seeds + 多种 temperature |
| 跳过 SC | 简单事实 query（"X 是什么"）跳过，仅复杂 reasoning 启用 |
| 缓存 | (query_hash, retrieved_hash) 24h 缓存 SC 结果 |
| Token 预算 | 单 query SC 总 token 不超 N（可配置） |

### 2.4 何时启用 SC？

不是所有 query 都启用：
- ✅ **数值题 / 计算题**：高度受益（"X 增长多少"）
- ✅ **多步推理**：受益明显（"先 A 再 B 然后 C"）
- ✅ **跨文档对比**：与 P0 #1 协同
- ❌ **简单事实**：浪费成本（"X 是什么"）
- ❌ **生成型**（摘要 / 写作）：取一个即可

通过 `system_router` 检测 query 类型自动启用 / 关闭。

---

## 3 落点设计（3 个）

### 3.1 落点 A：核心 wrapper `self_consistency.py`

**文件**：`app/rag/workflows/self_consistency.py`

**设计**：作为 *higher-order workflow*，wrap 任意 base workflow。

**接口**：
```python
class SelfConsistencyWrapper(BaseWorkflow):
    def __init__(self, base_workflow: BaseWorkflow, k: int = 5):
        self.base = base_workflow
        self.k = k

    async def run(self, query, ...):
        # K 路径并发
        results = await asyncio.gather(*[
            self.base.run(query, temperature=t, seed=s)
            for t, s in zip(temps, seeds)
        ])
        # 聚类 + 投票
        clusters = cluster_answers(results)
        return majority_vote(clusters)
```

**复用资产**：
- `app/rag/workflows/base.py:BaseWorkflow`
- `app/rag/embedding/`（聚类用 embedding 相似度）
- `app/rag/llm/`（LLM judge 模式参考 IBM 蓝图 Pydantic SO）

**新增**：~250 行

### 3.2 落点 B：答案聚类工具

**文件**：`app/rag/core/answer_clustering.py`

**接口**：
```python
def cluster_answers(answers: list[str]) -> list[AnswerCluster]:
    """按答案类型自动选择聚类策略"""
    if all(is_numeric(a) for a in answers):
        return cluster_numeric(answers, tolerance=0.05)
    if all(len(a) < 50 for a in answers):
        return cluster_short_text(answers, threshold=0.85)
    return cluster_long_text_via_llm(answers)  # 抽 claim 再聚类
```

**新增**：~120 行

### 3.3 落点 C：与 system_router 集成

**文件**：`app/rag/workflows/system_router.py`（修改）

**新增逻辑**：
- query intent classifier 判断是否需要 SC
- 数值 / 多步 / 跨源 query → 启用 SC（K=5）
- 简单事实 / 生成型 → 跳过 SC

**改动**：~50 行

### 3.4 工作量汇总

| 落点 | 行数 | 工时 |
|---|---|---|
| A SC wrapper | 250 | 3 day |
| B 答案聚类 | 120 | 2 day |
| C router 集成 | 50 | 1 day |
| 单测 + 集成测试 | 80 | 1 day |
| **合计** | **~500 行** | **~7 day / 1 周** |

---

## 4 与现有 12 个 workflow 集成

### 4.1 SC wrap 的 workflow 矩阵

| 现有 workflow | 是否 wrap SC | 理由 |
|---|---|---|
| `chain.py` | ✅ | 链式推理多步 |
| `react.py` | ✅ | tool-using 推理需稳定 |
| `self_rag.py` | ✅ | critic 投票 |
| `crag_streaming.py` | ⚠️ | streaming 模式不易 K-path，仅 final answer 启用 |
| `flare.py` | ✅ | look-ahead 不确定步骤 |
| `planner_worker.py` | ✅ | plan 步骤 SC |
| `evaluator_optimizer.py` | ❌ | 已有迭代逻辑 |
| `parallelization.py` | ❌ | 已并行检索 |
| `routing.py` | ❌ | 仅决策，不需 SC |
| `system_router.py` | ❌ | 仅决策 |
| `query_rewrite.py` | ✅ | 改写多版本投票 |
| `rerank_expand_rerank.py` | ⚠️ | 在 final answer 启用 |

### 4.2 配置 + 开关

`app/core/config.py` 新增：
```python
RAG_SELF_CONSISTENCY_ENABLED: bool = False        # 默认关
RAG_SELF_CONSISTENCY_K: int = 5
RAG_SELF_CONSISTENCY_TEMPERATURES: list = [0.7, 0.8, 0.9, 1.0, 1.1]
RAG_SELF_CONSISTENCY_AUTO_SCOPE: bool = True      # 由 router 决定
RAG_SELF_CONSISTENCY_TIMEOUT_PER_PATH: int = 30
RAG_SELF_CONSISTENCY_MAX_TOKENS_TOTAL: int = 50000
```

### 4.3 评测对照（rag-ablation 协同）

加 ablation：with-SC vs without-SC × 5 个 workflow。

---

## 5 1 周里程碑

### Day 1-2（Skeleton + clustering）
- [ ] `self_consistency.py` skeleton + 注册到 factory
- [ ] `answer_clustering.py` 三类聚类（numeric / short / long-via-llm）
- [ ] 单测覆盖

### Day 3-4（K-path 调度）
- [ ] asyncio.gather K 路径
- [ ] Temperature / seed 多样性
- [ ] 失败路径 fallback
- [ ] 缓存 (query, retrieved) 24h

### Day 5（Router 集成）
- [ ] `system_router.py` 加 intent classifier 决策 SC
- [ ] 简单事实 query 跳过

### Day 6（评测）
- [ ] Ablation：with-SC vs without-SC 在 GSM8K-zh / 复杂金融 query
- [ ] 输出对照报告

### Day 7（GA + 文档）
- [ ] 默认对 数值 / 多步 / 跨源 query 启用
- [ ] 配置文档 + 客户演示

---

## 6 风险 + 范围之外

### 6.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| K 路径成本翻 K 倍 | LLM 成本压力 | 仅在受益 query 启用 + cache |
| 聚类失败 | majority 算不准 | LLM judge fallback |
| 长答案聚类难 | 长摘要难以 majority | 抽 claim 再聚类 |
| 与 streaming 冲突 | crag streaming 不能多路径 | 仅在 final 启用 |
| 增加端到端延迟 | K 路径并发但仍 ≥ 单路径 max | 超时 30s + 失败容忍 |

### 6.2 范围之外（明确不做）

- 不做 Tree-of-Thought / Graph-of-Thought（更复杂，留给 P3）
- 不做 monte carlo tree search（学术为主）
- 不做 reward model（RLHF 范畴）
- 不做 prompt 自动优化（DSPy 范畴）

### 6.3 不要的东西

- ❌ 不要默认全启用（成本爆炸）
- ❌ 不要在简单事实 query 启用（浪费）
- ❌ 不要 K 太大（≤ 10 即可）
- ❌ 不要忽略 alternatives（不一致时给用户看）

---

## 7 与既有 plan 协同

| plan | 协同 |
|---|---|
| `rag-cross-doc-synthesis-2026-q3.md`（P0 #1） | NLI pairwise 投票降误判 |
| `rag-feedback-loop-2026-q3.md`（P0 #5） | 用户选 alternatives → 反哺 K 选择 |
| `rag-evaluation-deep-dive-2026-q2.md` | with-SC vs without-SC ablation |
| `rag-agentic-reasoning-deep-dive-2026-q2.md` | SC 是 agentic reasoning 标配 |
| `rag-ablation-deep-dive-2026-q2.md` | SC 作为新参数加入 38 → 39 |

---

## 8 关键洞察

1. **Self-Consistency 是 reasoning 最低 hanging fruit**（5 年学术验证）
2. **作为 wrapper 不破坏现有 12 workflow**（higher-order 设计）
3. **关键不是"做 SC"而是"何时做"**（router 决定）
4. **与 P0 #1 协同**（NLI 单点判定 + SC 投票 = 降误差双保险）
5. **K=5 是甜蜜点**（学术验证 + 成本可控）
