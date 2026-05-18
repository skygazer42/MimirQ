# KG 稳定性与延迟硬化（2026 Q3）

> **核心命题**：MimirQ KG 栈在 16 项业界主流"KG 稳定性 + 低延迟"清单中已完成 13 项（hybrid 检索 / query routing / ontology / provenance / canonicalization / 图遍历限制 / community 预计算 / 缓存 / 全局 vs 局部 / entity↔chunk 反向映射 / baseline 对照 / 受控 relation / parse_bench），剩 **3 个真正的 gap** 会直接影响"KG 不稳定 + QA 慢"的客户体验。本 plan 针对这 3 个 gap 给出具体修复路径 + 在线 QA latency SLO 体系，4-5 周完成 P0 部分。
>
> 创建日期：2026-05-18
> 来源：用户提问"KG 不稳定 + QA 长" + 对照清单 16 项后定位的 3 个 gap
> 关联：
> - `plans/rag-kg-deep-research-2026-q2.md`（KG 整体方法论）
> - `plans/rag-kg-diagnostics-deep-dive-2026-q2.md`（KG 评测）
> - `plans/rag-kg-snapshot-deep-dive-2026-q2.md`（快照与 diff）
> - `plans/rag-agentic-reasoning-deep-dive-2026-q2.md`（agentic search 现状）
>
> **一句话**：现在的 KG 已"够强"但"不够稳、不够快"——补 3 个 gap（多维版本字段 / agentic budget / structured_query 路由）+ 1 套 SLO 体系，把"不稳"与"慢"从感性吐槽变成可量化的 KPI。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 三个 gap 的现状代码定位 + root cause |
| 第 2 章 | 总体硬化架构图（指标视角） |
| 第 3 章 | P0-A 多维版本字段（解决"重建图就变了不知道原因"） |
| 第 4 章 | P0-B Agentic LLM Budget + Fallback Chain（解决"QA 长"） |
| 第 5 章 | P0-C intent_router 加 structured_query 类别（解决"结构化查询走 KG"误路由） |
| 第 6 章 | P1 在线 QA latency SLO 体系 |
| 第 7 章 | P2 KG 稳定性指标看板 |
| 第 8 章 | 落地里程碑（4-5 周 Daily 拆解） |
| 第 9 章 | 测试 / 验收指标 |
| 第 10 章 | 风险与陷阱清单 |

---

## 1 三个 gap 的现状代码定位

### 1.1 Gap 1 — 多维版本追踪缺失

**已有**：`app/rag/kg/models.py:58,120` Entity / Edge 表都有 `pipeline_version` / `version_scope`（粗粒度的"document_version"）。`kg/snapshot.py` 202 行做整张图快照。

**缺**：每条边没有以下 4 个独立字段：

```python
extractor_prompt_version: str    # 抽取 prompt 的 git sha / hash
extractor_model_version: str     # LLM 模型 ID（如 claude-opus-4-7@2026-05）
ontology_version: str            # 当时 ontology allowlist 的版本（DB 行 hash）
kg_build_version: str            # 这一次构建运行的 UUID（关联 logs / cost / latency）
```

**后果**：
- 客户问"为什么今天图和昨天不一样"——只能回答"重新构建过"，无法精确归因（prompt 改了？模型升级？ontology 调整？）
- A/B 实验同时跑两版 extractor 时，边混在同一张图里无法区分
- 回滚困难：snapshot 是整张图回滚，无法"只回滚 prompt vN 抽出的边"

**严重度**：⚠️ 中（影响可解释性 + 客户信任，但不影响 baseline 工作）

### 1.2 Gap 2 — Agentic Search 无 LLM Call Budget

**已有**：`kg/search/agentic_beam_search.py:11-12` 有 `beam_width=3, max_depth=3`（最坏 9 条路径）；`plan_on_graph.py` 实现 PoG。

**缺**：
- 没有 `max_llm_calls` 总数硬上限
- 没有 `budget_seconds` 时间预算
- 没有"超时降级链"：agentic 失败 → drift → local → 纯 hybrid RAG
- 没有 LLM call 成本归因（OTel span 在哪一步花了多少）

**后果**：
- 用户问的"QA 时间很长"——根因之一就是 agentic 路径在最坏情况下可能跑 9-27 次 LLM call（每跳 beam_width × LLM 评分）
- 没有 SLO 约束，慢 query 无法主动降级
- 客户成本不可预测（每个 query 花多少 token 取决于 agentic 走多远）

**严重度**：⚠️⚠️⚠️ 高（直接影响延迟与成本）

### 1.3 Gap 3 — intent_router 缺 structured_query 类别

**已有**：`app/rag/policy/intent_router.py` 含 7 个类别（LOG / API / HOWTO / FAQ / GREETING / THANKS / SMALLTALK）。

**缺**：没有 `STRUCTURED_QUERY` / `TABULAR_QUERY` 类别识别。

**后果**：
- 用户问"哪些合同金额超过 100 万"这类**应该走 NL2SQL** 的查询，被路由到 RAG / KG → 召回不准 + 慢
- `lotus_bridge.py` 和 `table_tag_service.py` 的 NL2SQL 能力**没有自动入口**，只能用户主动选

**严重度**：⚠️ 中（已有能力没被用上，纯路由问题）

---

## 2 总体硬化架构

```
                  用户查询
                     ↓
        ┌──────────────────────────┐
        │   intent_router (P0-C)    │
        │   8 类别（加 STRUCTURED）  │
        └────┬─────┬────┬─────┬─────┘
             │     │    │     │
   greeting/  rag  kg   structured_query
   smalltalk  ↓    ↓        ↓
         直接回 ┌─ kg_method_router ──────────┐
         应    │  local / global / agentic   │
              │  with budget (P0-B)          │
              │   ├─ max_llm_calls = N       │
              │   ├─ budget_seconds = S      │
              │   └─ fallback chain          │
              │       agentic → drift →      │
              │       local → hybrid RAG     │
              └────────┬─────────────────────┘
                       ↓
                  hybrid retriever
                       ↓
                     rerank
                       ↓
                生成（1-2 次 LLM call）
                       ↓
        OTel span + latency SLO + cost (P1)
                       ↓
       KG 边写入时附 4 维版本字段 (P0-A)
```

### 2.1 SLO 设计目标（P1 章节细化）

| 指标 | Target | 触发动作 |
|---|---|---|
| QA P95 latency | ≤ 3s | 超时降级 |
| QA P99 latency | ≤ 6s | 告警 + 强制走 hybrid only |
| 单 query LLM call 数 | ≤ 3 | budget 触发 |
| 单 query token 消耗 | ≤ 8K input | budget 触发 |
| KG 路径触发率 | 控制在 15-30% | 路由策略调整 |
| KG 路径召回 +5pt vs hybrid | 持续监控 | 否则降权 |

---

## 3 P0-A：多维版本字段（解决"重建图就变了不知道原因"）

### 3.1 Schema 变更

**改造**：`app/rag/kg/models.py` Entity / Edge 表新增 4 字段。

```python
# app/rag/kg/models.py 改造
class KgEntity(Base):
    # ... 现有字段 ...

    # 新增 4 维版本字段
    extractor_prompt_version = Column(String(64), nullable=True, index=True)
    extractor_model_version = Column(String(128), nullable=True, index=True)
    ontology_version = Column(String(64), nullable=True, index=True)
    kg_build_id = Column(String(64), nullable=True, index=True)
    # 已有的 pipeline_version 保留作为粗粒度兼容

class KgEdge(Base):
    # ... 现有字段 ...
    extractor_prompt_version = Column(String(64), nullable=True, index=True)
    extractor_model_version = Column(String(128), nullable=True, index=True)
    ontology_version = Column(String(64), nullable=True, index=True)
    kg_build_id = Column(String(64), nullable=True, index=True)
```

**Alembic migration**：

```python
# alembic/versions/xxxx_add_kg_version_fields.py
def upgrade():
    for table in ['kg_entities', 'kg_edges']:
        op.add_column(table, sa.Column('extractor_prompt_version', sa.String(64), nullable=True))
        op.add_column(table, sa.Column('extractor_model_version', sa.String(128), nullable=True))
        op.add_column(table, sa.Column('ontology_version', sa.String(64), nullable=True))
        op.add_column(table, sa.Column('kg_build_id', sa.String(64), nullable=True))
        op.create_index(f'ix_{table}_kg_build_id', table, ['kg_build_id'])
        op.create_index(f'ix_{table}_extractor_prompt_version', table, ['extractor_prompt_version'])
```

### 3.2 版本注册表

**新增**：`app/rag/kg/build_registry.py` ~250 行

```python
@dataclass
class KgBuildRecord:
    kg_build_id: str  # uuid4
    tenant_id: str
    started_at: datetime
    finished_at: datetime | None
    extractor_prompt_version: str   # e.g. "kg_extract_prompt_v2_2026_05_18"
    extractor_prompt_sha: str       # prompt text 的 sha256
    extractor_model_version: str    # 如 "claude-opus-4-7@2026-05"
    ontology_version: str           # ontology DB rows 的 hash
    ontology_snapshot_blob: bytes   # 当时的 ontology allowlist 完整快照
    doc_count: int
    entity_count: int
    edge_count: int
    total_llm_calls: int
    total_cost_usd: float
    notes: str | None
```

**新增表 `kg_build_records`**：与 entity/edge 关联（`kg_build_id` 外键）。

### 3.3 KG Pipeline 接入

**改造**：`app/rag/kg/pipeline.py` 在 KG 构建入口生成 `kg_build_id` + 注册 record + 把 4 维版本传给 extractor。

```python
# kg/pipeline.py 改造伪代码
async def build_kg(tenant_id, doc_ids, ontology):
    build_id = str(uuid4())
    prompt_version = get_prompt_version("kg_extraction")
    prompt_sha = sha256(get_prompt_text("kg_extraction"))
    model_version = get_current_llm_model_id()
    ontology_version = compute_ontology_hash(ontology)

    record = KgBuildRecord(
        kg_build_id=build_id,
        extractor_prompt_version=prompt_version,
        extractor_prompt_sha=prompt_sha,
        extractor_model_version=model_version,
        ontology_version=ontology_version,
        ontology_snapshot_blob=serialize(ontology),
        ...
    )
    await save_build_record(record)

    for entity, edge in extract(doc_ids, ontology):
        entity.kg_build_id = build_id
        entity.extractor_prompt_version = prompt_version
        entity.extractor_model_version = model_version
        entity.ontology_version = ontology_version
        # 同理 edge
        await save(entity, edge)

    await mark_build_finished(record)
```

### 3.4 API 暴露

**新增** `app/api/v1/kg_build.py` ~150 行：

```python
@router.get("/kg/builds")
async def list_kg_builds(tenant_id: UUID): ...

@router.get("/kg/builds/{build_id}")
async def get_kg_build(build_id: str):
    """返回 record + 关联 entities/edges 数量 + 与上一 build 的 diff"""

@router.get("/kg/builds/{build_id}/diff/{other_build_id}")
async def diff_kg_builds(build_id: str, other_build_id: str):
    """对比两次 build 的 entity/edge 差异 + 4 维版本差异定位根因"""

@router.post("/kg/builds/{build_id}/rollback")
async def rollback_to_build(build_id: str):
    """只回滚到指定 build_id 的边（保留其他 build 的边）"""
```

### 3.5 前端 UI

**改造**：`web/app/graph/snapshots/page.tsx`（已有 1229 行）增加：
- 4 维版本字段展示
- 同一 doc 不同 build_id 的 diff 视图
- "归因到字段"分析（哪个版本变化导致这条边消失了）

### 3.6 工程量

| 项 | 行数估算 |
|---|---|
| `kg/models.py` 改造 + migration | +80 |
| `kg/build_registry.py` 新增 | ~250 |
| `kg/pipeline.py` 接入 | +60 |
| `api/v1/kg_build.py` 新增 | ~150 |
| 前端改造 | ~200 |
| 单测 | ~150 |
| **合计** | **~900 行 / 1 周** |

---

## 4 P0-B：Agentic LLM Budget + Fallback Chain（解决"QA 长"）

### 4.1 设计原则

| 原则 | 含义 |
|---|---|
| 硬上限 | 每个 query 的 LLM call 总数有硬上限（默认 3） |
| 时间预算 | 总 wall-clock 时间预算（默认 5s） |
| 降级链 | 任一上限触发 → 降级到下一档检索路径 |
| 可观测 | OTel span 记录每一步耗时 + LLM token 消耗 + 触发降级原因 |
| 可配置 | 通过 settings 调整 budget；不同 query type 不同档 |

### 4.2 LLM Budget 中间件

**新增**：`app/rag/kg/search/budget.py` ~200 行

```python
@dataclass
class SearchBudget:
    max_llm_calls: int = 3
    max_total_seconds: float = 5.0
    max_input_tokens: int = 8000
    max_output_tokens: int = 2000
    started_at: float = field(default_factory=time.monotonic)
    llm_call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def check(self) -> BudgetStatus:
        """返回 OK / NEAR_LIMIT / EXCEEDED + reason"""

    def consume(self, llm_call: bool = False, input_tokens: int = 0, output_tokens: int = 0):
        """记录一次消费;返回是否仍允许继续"""

    def remaining_seconds(self) -> float: ...
    def remaining_calls(self) -> int: ...

class BudgetExceeded(Exception):
    """触发降级链的标志异常"""
    reason: str  # "llm_calls_exceeded" / "timeout" / "tokens_exceeded"
```

### 4.3 Fallback Chain 编排器

**新增**：`app/rag/kg/search/fallback_chain.py` ~300 行

```python
class KgSearchFallbackChain:
    """
    降级链（按优先级从严到松）：
    1. agentic_beam_search   (LLM 重度，质量最高)
    2. plan_on_graph (PoG)   (LLM 中度)
    3. drift_search          (LLM 轻度)
    4. local_search          (无 LLM, 仅图遍历)
    5. hybrid_rag_only       (完全跳过 KG)
    """

    CHAIN = [
        ("agentic_beam_search", BUDGET_AGENTIC),
        ("plan_on_graph", BUDGET_POG),
        ("drift_search", BUDGET_DRIFT),
        ("local_search", BUDGET_LOCAL),
        ("hybrid_rag_only", BUDGET_NONE),
    ]

    async def search(self, query: str, *, budget: SearchBudget) -> SearchResult:
        decisions = []
        for method_name, method_budget in self.CHAIN:
            if not budget.allows(method_budget):
                decisions.append((method_name, "skipped_due_to_budget"))
                continue
            try:
                result = await self._run_method(method_name, query, budget=budget)
                decisions.append((method_name, "success"))
                result.fallback_log = decisions
                return result
            except BudgetExceeded as e:
                decisions.append((method_name, f"exceeded:{e.reason}"))
                continue
            except Exception as e:
                logger.warning(f"{method_name} failed: {e}")
                decisions.append((method_name, f"error:{e.__class__.__name__}"))
                continue

        # 全链失败 → 最低限度 hybrid RAG
        return await hybrid_rag_only(query)
```

### 4.4 现有 Search 方法接入 Budget

**改造**：
- `agentic_beam_search.py`：每次 LLM 评分调用前 `budget.check()`，超限抛 `BudgetExceeded`
- `plan_on_graph.py`：同上
- `drift_search.py`：同上

**示例**：

```python
# kg/search/agentic_beam_search.py 改造
async def agentic_beam_search(query, ..., budget: SearchBudget):
    for hop in range(max_depth):
        for candidate in current_beam:
            if budget.check() != BudgetStatus.OK:
                raise BudgetExceeded(reason=budget.last_violation)
            score = await llm_score(candidate, query)
            budget.consume(llm_call=True, input_tokens=..., output_tokens=...)
            ...
```

### 4.5 配置项

**新增 settings**（`app/core/config.py`）：

```python
# KG Agentic Budget
KG_AGENTIC_MAX_LLM_CALLS: int = 3
KG_AGENTIC_MAX_SECONDS: float = 5.0
KG_AGENTIC_MAX_INPUT_TOKENS: int = 8000
KG_POG_MAX_LLM_CALLS: int = 2
KG_POG_MAX_SECONDS: float = 3.0
KG_DRIFT_MAX_LLM_CALLS: int = 1
KG_DRIFT_MAX_SECONDS: float = 2.0
KG_LOCAL_MAX_SECONDS: float = 1.0
```

### 4.6 OTel Span

**改造**：每一档方法包一层 span：

```python
with tracer.start_as_current_span("kg.search.agentic_beam") as span:
    span.set_attribute("budget.max_llm_calls", budget.max_llm_calls)
    result = await agentic_beam_search(query, budget=budget)
    span.set_attribute("budget.llm_call_count", budget.llm_call_count)
    span.set_attribute("budget.total_input_tokens", budget.total_input_tokens)
    span.set_attribute("budget.elapsed_seconds", time.monotonic() - budget.started_at)
    span.set_attribute("result.decisions", json.dumps(result.fallback_log))
```

### 4.7 前端可视化

**改造**：chat trace panel（`web/components/rag-trace/`）新增"KG 降级链时间线"：
- 显示走了哪一档（agentic / pog / drift / local / hybrid_only）
- 每档耗时 + LLM call 数 + 为什么降级（timeout / tokens / error）
- 客户可信赖："你这条查询花 4.2s 因为走了 agentic + drift 两档，下一次相同查询会走 cache 0.3s"

### 4.8 工程量

| 项 | 行数估算 |
|---|---|
| `kg/search/budget.py` 新增 | ~200 |
| `kg/search/fallback_chain.py` 新增 | ~300 |
| `agentic_beam_search.py` 改造 | +60 |
| `plan_on_graph.py` 改造 | +60 |
| `drift_search.py` 改造 | +40 |
| `searcher.py`（主入口）接入 fallback chain | +80 |
| `config.py` 新增 settings | +30 |
| OTel span 接入 | +50 |
| 前端时间线组件 | ~200 |
| 单测 | ~250 |
| **合计** | **~1270 行 / 1.5 周** |

---

## 5 P0-C：intent_router 加 structured_query 类别（解决"结构化查询走 KG"误路由）

### 5.1 新增 intent 类别

**改造**：`app/rag/policy/intent_router.py` 在 7 个现有类别基础上新增 `STRUCTURED_QUERY`。

```python
# intent_router.py 新增
_INTENT_STRUCTURED_QUERY_RE = re.compile(
    r"(?:"
    # 数量/聚合关键词
    r"(?:多少|几个|总数|平均|最大|最小|最高|最低|超过|低于|大于|小于|等于)"
    # 比较 / 排序
    r"|(?:排名|前\s*\d+\s*名|top\s*\d+|排序|对比|哪些.*同时|哪些.*并且)"
    # 时间段过滤
    r"|(?:近\s*\d+\s*(?:天|周|月|年)|过去\s*\d+\s*(?:天|周|月|年)|本季度|本月|上个月)"
    # 表头/字段名引用
    r"|(?:字段|列|表|金额|数量|价格|日期|时间|状态|类型).*(?:大于|小于|超过|低于|为|是)"
    r")",
    re.IGNORECASE,
)

# 加入分类链
def classify_intent(query: str) -> str:
    # 现有规则保持顺序
    ...
    if _INTENT_STRUCTURED_QUERY_RE.search(q):
        return "structured_query"
    ...
```

### 5.2 路由到 NL2SQL 路径

**改造**：`app/rag/engine.py` 主路径根据 intent 决定是否走 NL2SQL：

```python
# engine.py 伪代码
intent = classify_intent(query)
if intent == "structured_query":
    # 检查是否有可用的结构化数据源（dataset 含表格 / 数据库 connector）
    structured_sources = await get_structured_sources(tenant_id, scope)
    if structured_sources:
        result = await nl2sql_or_table_qa(query, sources=structured_sources)
        if result.confidence > 0.7:
            return result
        # 否则降级到 RAG
    # fallback to RAG
```

### 5.3 NL2SQL 服务包装

**新增**：`app/services/structured_query_service.py` ~250 行（统一封装现有 `table_tag_service.py` + `lotus_bridge.py`）

```python
class StructuredQueryService:
    async def route_and_execute(
        self,
        query: str,
        sources: list[StructuredSource],  # 表格 dataset / DB connector
    ) -> StructuredQueryResult:
        """
        1. 判断查询是否真的可结构化（含表名/列名/聚合词）
        2. 选最合适的 source（表格 OR SQL 数据库）
        3. 调用 lotus_bridge 或 table_tag_service
        4. 把结果格式化为可解释的回答
        5. 含 confidence 评分供主路径决策
        """
```

### 5.4 训练数据（可选 ML 升级）

P0 用 regex；后续 P1 可换 fine-tuned classifier（用 chat history 自动标注 + 客户校正样本）。

### 5.5 工程量

| 项 | 行数估算 |
|---|---|
| `intent_router.py` 新增 regex + 类别 | +80 |
| `engine.py` 路由分支 | +60 |
| `structured_query_service.py` 新增 | ~250 |
| 单测（覆盖 30+ 中英文 query） | ~150 |
| **合计** | **~540 行 / 0.5-1 周** |

---

## 6 P1：在线 QA Latency SLO 体系

### 6.1 SLO 字典

| Metric | Target | 测量方式 |
|---|---|---|
| `qa.latency.p50` | ≤ 1.5s | OTel histogram |
| `qa.latency.p95` | ≤ 3.0s | OTel histogram |
| `qa.latency.p99` | ≤ 6.0s | OTel histogram |
| `qa.llm_calls.p95` | ≤ 3 | counter aggregation |
| `qa.input_tokens.p95` | ≤ 8000 | counter |
| `qa.output_tokens.p95` | ≤ 2000 | counter |
| `qa.cost_usd.p95` | ≤ $0.02 | from `core/cost_tracker.py` |
| `kg.path.usage_rate` | 15-30% | KG 触发比例 |
| `kg.fallback.rate` | < 10% | budget 触发降级比例 |
| `kg.cache.hit_rate` | > 40% | cache hit / total |
| `qa.error.rate` | < 1% | 5xx + 解析失败 |
| `qa.degradation.rate` | < 5% | hybrid_only 兜底触发 |

### 6.2 告警与降级动作

**新增**：`app/rag/policy/slo_enforcer.py` ~200 行

```python
class SloEnforcer:
    """
    实时监测 SLO 状态，超阈值时主动调整路由策略
    """

    async def evaluate(self, recent_window: timedelta = timedelta(minutes=5)) -> SloStatus:
        stats = await self._aggregate(recent_window)

        actions = []
        if stats.p95_latency > 4.0:  # 超 SLO 30%+
            actions.append(SloAction.FORCE_HYBRID_ONLY)  # 暂时关闭 KG agentic
        if stats.fallback_rate > 0.2:
            actions.append(SloAction.LOWER_AGENTIC_BUDGET)
        if stats.cache_hit_rate < 0.3:
            actions.append(SloAction.WARM_CACHE)
        if stats.error_rate > 0.03:
            actions.append(SloAction.ALERT_ONCALL)

        return SloStatus(stats=stats, actions=actions)
```

### 6.3 现有基础设施复用

| 已有 | 用途 |
|---|---|
| `app/rag/metrics_sli.py` | SLI 计算基础设施 |
| `app/services/slo_snapshot_service.py` | SLO snapshot 持久化 |
| `app/api/v1/observability.py` | 可观测 API |
| `app/core/cost_tracker.py` | 成本统计 |

**不重写**，只在其上加 KG / fallback / budget 相关 metric。

### 6.4 前端 SLO 看板

**新增**：`/observability/slo` 页面（~400 行）
- 实时显示当前 SLO 状态（绿/黄/红）
- 历史趋势（近 7 天）
- 触发的降级动作日志
- 按 tenant / dataset / intent 钻取

### 6.5 工程量

| 项 | 行数估算 |
|---|---|
| `slo_enforcer.py` 新增 | ~200 |
| 接入 `metrics_sli.py` 新指标 | +100 |
| 前端 SLO 看板 | ~400 |
| 告警接入（Slack / 飞书 / 邮件） | ~150 |
| **合计** | **~850 行 / 1 周** |

---

## 7 P2：KG 稳定性指标看板

### 7.1 指标

| Metric | 含义 | 频率 |
|---|---|---|
| `kg.build.entity_drift_rate` | 同 doc 不同 build 的实体差异率 | 每次 build |
| `kg.build.edge_drift_rate` | 边差异率 | 每次 build |
| `kg.build.ontology_violation_rate` | 抽出来不在 ontology 内的边比例 | 每次 build |
| `kg.build.evidence_missing_rate` | 缺 evidence_quote 的边比例 | 每次 build |
| `kg.build.canonical_collision_rate` | 别名归一化冲突率 | 每次 build |
| `kg.search.cache.hit_rate_per_method` | 按 agentic/pog/drift/local 分别统计 | 实时 |
| `kg.search.fallback_distribution` | 各档触发的分布 | 实时 |

### 7.2 前端

接入到现有 `/graph/diagnostics` 页面（已有 1174 行），新增"稳定性"Tab。

### 7.3 工程量

| 项 | 行数估算 |
|---|---|
| 后端 metric 计算 | ~300 |
| 前端 Tab | ~250 |
| **合计** | **~550 行 / 0.5 周** |

---

## 8 落地里程碑（4-5 周 Daily）

### Week 1：P0-A 多维版本字段

| Day | 任务 | 产出 |
|---|---|---|
| D1 | Schema + migration | `models.py` + alembic |
| D2 | `build_registry.py` 主流程 | ~250 行 |
| D3 | `pipeline.py` 接入 4 维 + 测试 | +60 行 |
| D4 | `api/v1/kg_build.py` | ~150 行 |
| D5 | 前端 build diff 视图 + e2e | ~200 行 |

### Week 2-3：P0-B Agentic Budget + Fallback Chain

| Day | 任务 | 产出 |
|---|---|---|
| D6 | `budget.py` SearchBudget 类 | ~200 行 |
| D7 | `fallback_chain.py` 主编排 | ~300 行 |
| D8 | `agentic_beam_search.py` 接入 budget | +60 行 |
| D9 | `plan_on_graph.py` 接入 budget | +60 行 |
| D10 | `drift_search.py` + `searcher.py` 接入 | +120 行 |
| D11 | OTel span + settings | +80 行 |
| D12 | 前端时间线组件 | ~200 行 |
| D13 | 集成测试（覆盖各档触发） | ~150 行 |
| D14 | 性能基准测试（50 query × 4 档） | benchmark 报告 |
| D15 | 调阈值 + 文档 | — |

### Week 4：P0-C structured_query 路由

| Day | 任务 | 产出 |
|---|---|---|
| D16 | `intent_router.py` 新增 regex | +80 行 |
| D17 | `structured_query_service.py` | ~250 行 |
| D18 | `engine.py` 路由分支 | +60 行 |
| D19 | 30+ query 单测 | ~150 行 |
| D20 | 端到端测试（包含 fallback 到 RAG） | — |

### Week 5：P1 SLO 体系（合并 P2 看板）

| Day | 任务 | 产出 |
|---|---|---|
| D21-22 | `slo_enforcer.py` + metrics 接入 | ~300 行 |
| D23-24 | 前端 SLO 看板 | ~400 行 |
| D25 | P2 稳定性指标 Tab | ~250 行 |

**总工程量**：**~4100 行 / 5 周**（含前端 + 单测）

---

## 9 测试 / 验收

### 9.1 P0-A 验收

- [ ] 新建 build → 4 维版本字段写入正确（DB 直查验证）
- [ ] 两次 build 同一 doc → diff API 返回字段级差异
- [ ] 选择 build_id 回滚 → 只删除该 build 的边
- [ ] 前端可看到"为什么这条边消失了：prompt v2 → v3"

### 9.2 P0-B 验收

- [ ] 模拟 LLM 慢调用 → budget 触发 → 降级到下一档
- [ ] 全链失败 → 兜底 hybrid_rag_only 返回
- [ ] OTel span 完整记录每档耗时 + 触发原因
- [ ] **P95 latency 从 baseline 降到 ≤ 3s**（benchmark 50 query 测试集）
- [ ] **单 query LLM call 从最坏 9-27 降到 ≤ 3**

### 9.3 P0-C 验收

- [ ] 30 个 structured_query 单测 ≥ 95% 准确率
- [ ] "哪些合同金额超过 100 万" 自动走 NL2SQL
- [ ] NL2SQL confidence < 0.7 时正确降级到 RAG
- [ ] 不误判普通问答为 structured_query（false positive < 5%）

### 9.4 P1 验收

- [ ] SLO 看板实时显示 P50/P95/P99/cost/cache hit
- [ ] 模拟 P95 超阈值 → enforcer 自动强制 hybrid_only
- [ ] 告警渠道可达（Slack / 飞书 / 邮件）

### 9.5 端到端 Benchmark

- [ ] 跑 200 query 测试集（100 RAG / 50 KG / 30 structured / 20 边缘）
- [ ] 对比 baseline（无 hardening）：P95 latency 降 ≥ 40%
- [ ] KG 路径使用率在 15-30% 之间
- [ ] 总 cost 下降 ≥ 30%（agentic 不再无限跑）
- [ ] 回归测试：答案质量 RAGAS Faithfulness 不下降（容差 ±2pt）

---

## 10 风险与陷阱清单

| # | 风险 | 缓解 |
|---|---|---|
| 1 | Migration 失败破坏现有 KG | migration 包 try/except + rollback；新字段 nullable，老数据可写 NULL |
| 2 | Budget 阈值太严 → 频繁降级 → 质量倒退 | 默认宽松（max_llm_calls=3 是初步建议）+ 灰度发布 + A/B |
| 3 | Fallback 全链失败处理不当 | 必须有 hybrid_only 兜底，永远返回结果 |
| 4 | structured_query 误判 → 误走 NL2SQL → 失败 | confidence < 0.7 自动降级 + 客户可主动切回 |
| 5 | OTel span 数据爆炸 | 采样率配置（默认 10%）+ 错误/慢 query 100% 采样 |
| 6 | SLO Enforcer 自动降级造成"看起来快但答错" | 强制保留 baseline 质量 metric；质量降 > 5pt 立即停 enforcer |
| 7 | 4 维版本字段写入失败导致整个 build 失败 | 版本字段允许为空（兼容）+ 写入失败仅 warn |
| 8 | 现有客户依赖 agentic 完整跑 → 突然限速抱怨 | 灰度 + 客户可申请提升 budget（tenant-level override） |
| 9 | 前端 build diff 视图过重 | 大 build 用分页 + 服务端 diff 计算 |
| 10 | 跨 build 回滚导致引用悬空 | 回滚前检查 chat history / 评测集是否引用 → 警告后再删 |

---

## 11 范围之外

- ✗ 重写整个 KG agentic search 算法（只加 budget）
- ✗ 改造 ontology schema（只加版本字段引用）
- ✗ 训练 ML 版 intent classifier（P0 用 regex；P1 再考虑）
- ✗ 跨租户共享 cache / build（多租户隔离严格）
- ✗ 把所有 hardcoded prompt 迁移到 prompt library（在另一份 plan）
- ✗ 替换 hybrid retriever / rerank 算法（保持不变）

---

## 12 决策门槛

| 决策 | 通过条件 | 否则 |
|---|---|---|
| 是否启动 P0-A | KG snapshot 已能完整工作 | 先修 snapshot |
| 是否启动 P0-B | 至少 1 个客户报 KG 慢 | 推迟 |
| 是否启动 P0-C | NL2SQL 路径已可用 | 先修 NL2SQL |
| Budget 默认值 | 50 query benchmark 显示 max_llm_calls=3 保留 ≥ 95% 质量 | 调整阈值 |
| 是否上线 SLO enforcer 自动降级 | 灰度 7 天质量 metric 不下降 | 仅告警不自动降级 |
| 是否 deprecate 老 pipeline_version | 4 维字段全量回填完成 + 跨 tenant 验证 | 双轨保留 6 个月 |

---

## 附录 A：架构图（升级后）

```
              用户查询
                ↓
       ┌────────────────────────┐
       │   intent_router (8 类)  │
       └─┬──┬──┬──┬──┬──────────┘
         │  │  │  │  │
       chat smalltalk
         │
         ↓
  ┌──────────────────┐
  │ rag_or_kg_branch │
  └─┬────────────┬───┘
    │            │
    │            └──► structured_query_service (P0-C)
    │                 ├ table_tag_service
    │                 └ lotus_bridge (NL2SQL)
    │                 confidence < 0.7 → fallback ↓
    ↓
  ┌────────────────────────────┐
  │ KG SearchFallbackChain     │ (P0-B)
  │ ┌────────────────────────┐ │
  │ │ Budget                 │ │
  │ │ - max_llm_calls=3      │ │
  │ │ - max_seconds=5        │ │
  │ │ - max_input_tokens=8K  │ │
  │ └────────────────────────┘ │
  │   ↓ try in order:          │
  │ ① agentic_beam_search      │ ← budget=AGENTIC
  │ ② plan_on_graph            │ ← budget=POG
  │ ③ drift_search             │ ← budget=DRIFT
  │ ④ local_search             │ ← budget=LOCAL
  │ ⑤ hybrid_rag_only (兜底)   │
  └─────────────┬──────────────┘
                ↓
         hybrid retriever
                ↓
               rerank
                ↓
       LLM 生成（1-2 次 call）
                ↓
      OTel span + SLO Enforcer (P1)
                ↓
   KG 边写入时携 4 维版本字段 (P0-A)
   - extractor_prompt_version
   - extractor_model_version
   - ontology_version
   - kg_build_id
                ↓
        用户回答 + Trace + Citations
```

## 附录 B：与已有 plan 的边界

| Plan | 边界 |
|---|---|
| `rag-kg-deep-research-2026-q2.md` | 那 plan 给方法论 + 业界对标；本 plan 给具体修复 3 个 gap |
| `rag-kg-diagnostics-deep-dive-2026-q2.md` | 那 plan 给评测；本 plan 的稳定性 metric 接入那个评测看板 |
| `rag-kg-snapshot-deep-dive-2026-q2.md` | 那 plan 给整图快照；本 plan 的 build_id 与那个 snapshot 是不同维度（snapshot=整图时刻，build_id=单次构建批次） |
| `rag-agentic-reasoning-deep-dive-2026-q2.md` | 那 plan 给 agentic 实现；本 plan 给 budget 约束 |
| `rag-evaluation-deep-dive-2026-q2.md` | 那 plan 给评测指标；本 plan 的 SLO 复用其 metric |
| `deepdoc-pipeline-implementation-2026-q2.md` | 互不影响 |
| `research-candidates-2026-q2.md` 中 #9 SLO | 本 plan **就是**那个候选的具体落地 |

## 附录 C：核心代码骨架预览

### C.1 SearchBudget 用法

```python
async def search_with_budget(query: str) -> SearchResult:
    budget = SearchBudget(
        max_llm_calls=settings.KG_AGENTIC_MAX_LLM_CALLS,
        max_total_seconds=settings.KG_AGENTIC_MAX_SECONDS,
        max_input_tokens=settings.KG_AGENTIC_MAX_INPUT_TOKENS,
    )
    chain = KgSearchFallbackChain()
    result = await chain.search(query, budget=budget)

    logger.info(
        "KG search done: method=%s, llm_calls=%d, elapsed=%.2fs, fallback=%s",
        result.method_used,
        budget.llm_call_count,
        time.monotonic() - budget.started_at,
        result.fallback_log,
    )
    return result
```

### C.2 KgBuildRecord 用法

```python
async with start_kg_build(
    tenant_id=tenant_id,
    extractor_prompt_version="kg_extract_v2_2026_05_18",
    extractor_model_version="claude-opus-4-7@2026-05",
    ontology_version=compute_ontology_hash(ontology),
) as build:
    for doc_id in doc_ids:
        await extract_and_save(doc_id, build_id=build.id, ontology=ontology)
    build.mark_finished(entity_count=..., edge_count=..., cost_usd=...)
```

### C.3 Intent Router 升级

```python
def classify_intent(query: str) -> str:
    q = query.strip()
    if _INTENT_GREETING_RE.match(q): return "greeting"
    if _INTENT_THANKS_RE.match(q): return "thanks"
    if _INTENT_SMALLTALK_RE.match(q): return "smalltalk"
    if _INTENT_STRUCTURED_QUERY_RE.search(q): return "structured_query"  # NEW
    if _INTENT_LOG_RE.search(q): return "log"
    if _INTENT_API_RE.search(q): return "api"
    if _INTENT_HOWTO_RE.search(q): return "howto"
    if _INTENT_FAQ_RE.search(q): return "faq"
    return "general"  # → 默认走 RAG + KG
```

---

## 结语

本 plan 不创造新的 KG 能力，**只把已有的 KG 能力变得"稳"与"快"**：

- 3 个 P0 修复 = 直接堵住"不稳"与"慢"的 3 个具体口子
- P1 SLO = 让"稳"与"快"从感性吐槽变成可量化 KPI
- P2 看板 = 让客户与团队都能看见稳定性数据

**预期收益**：
- QA P95 延迟 从 baseline 降 ≥ 40%
- 单 query LLM call 从最坏 9-27 降到 ≤ 3
- KG 路径的"重建图就变了"问题可归因（4 维版本字段定位根因）
- structured_query 自动走 NL2SQL，召回准确率 +20pt 以上

**5 周 / ~4100 行代码 / 零新算法、零新模型**——是典型的"已有 80 分系统升到 95 分"的硬化型 plan。
