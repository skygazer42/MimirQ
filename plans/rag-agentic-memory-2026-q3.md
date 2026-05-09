# 长期 Agentic Memory（能力 P1 #4，2026 Q3）

> 把现有 *会话内 memory*（`structured_memory_service` 抽 entity + fact / `summary_memory` / `enable_long_term_memory`）升级为 **Episodic / Semantic / Procedural 三层 Agentic Memory**。让 RAG 记住用户 —— "上次类似问题给的答案 / 偏好简洁回答 / 喜欢从财报第 3 章查"。
>
> 创建日期：2026-05-08
> 来源：`rag-gap-and-recommendations-summary-2026-q2.md` 第 5.2 节真 GAP / 用户对话 2026-05-08 聚焦能力
> 优先级：P1（能力 #4）
>
> **核心一句话**：现有 chat 已有 3 种 memory（long_term / summary / structured），但**仅会话内 + 实体级**；缺的是 *episodic 跨会话相似检索 / procedural 行为模式记忆 / 三层架构 + memory consolidation*；2 周 ~800 行可形成完整 Agentic Memory 框架。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 现状盘点（已有 vs 期望） |
| 第 2 章 | 三层 Memory 定义 |
| 第 3 章 | 落点设计（4 个） |
| 第 4 章 | Memory 生命周期 |
| 第 5 章 | 与现有 chat / RAG 集成 |
| 第 6 章 | 评测 |
| 第 7 章 | 2 周里程碑 |
| 第 8 章 | 风险 + 范围之外 |

---

## 1 现状盘点

### 1.1 已有能力（不重做）

| 模块 | 文件 | 能力 |
|---|---|---|
| LangGraph checkpointer | `app/rag/checkpointer/memory.py` | ✅ 短期会话状态（Thread + State） |
| Structured Memory | `app/services/structured_memory_service.py` | ✅ 抽 entity tokens + fact sentences |
| Summary Memory | `app/api/v1/chat.py` 中 `enable_summary_memory` | ✅ 会话摘要持久化 |
| Long-term Memory | `app/api/v1/chat.py` 中 `enable_long_term_memory` | ✅ 跨会话基础 |

### 1.2 关键缺失

```bash
$ grep -rln "EpisodicMemory\|SemanticMemory\|ProceduralMemory" app/
# 0 命中
```

具体差距：
- ❌ **Episodic memory**：不能 *相似度检索* 历史对话（"上次类似问题给过什么"）
- ❌ **Semantic memory**：用户 *偏好 / 事实知识图谱*（"用户偏好简洁回答 / 用户公司是 X"）
- ❌ **Procedural memory**：用户 *使用模式*（"用户高频从财报第 3 章查 / 习惯先查再追问"）
- ❌ **Memory consolidation**：短期 → 长期的 *自动迁移*（防止无限增长）
- ❌ **Memory pruning**：过期 / 重复 memory 自动清理
- ❌ **Memory retrieval API**：现有 RAG 不能 query memory

### 1.3 业界对标

| 系统 | 强项 |
|---|---|
| **MemGPT** (Berkeley) | 三层 OS-style memory |
| **Letta** (former MemGPT) | Long-term + agent memory |
| **Mem0** (开源) | Personal AI memory |
| **Zep** (开源) | Conversation memory |
| **OpenAI Memory** | ChatGPT 用户记忆 |

### 1.4 学术参考

- **MemGPT** (NeurIPS'24)：三层 memory + page in/out
- **A-MEM** (arXiv 2024)：Atkinson-Shiffrin 心理学模型
- **Generative Agents** (UIST'23)：Episodic + Reflection

---

## 2 三层 Memory 定义

### 2.1 Episodic Memory（情景记忆）

**定义**：跨会话的对话历史 + 检索结果 + 用户行为

**Schema**：
```python
@dataclass
class EpisodicMemory:
    user_id: UUID
    tenant_id: UUID
    timestamp: datetime
    query: str
    response: str
    retrieved_chunks: list[str]    # chunk_ids
    feedback: int | None            # 评分
    embedding: list[float]          # 用于相似度检索
```

**用途**：
- 用户问问题前，检索 *上次类似问题及答案*
- 用户给出反馈后，标记历史 episode 为 good / bad

### 2.2 Semantic Memory（语义记忆）

**定义**：用户的 *事实 + 偏好*

**Schema**：
```python
@dataclass
class SemanticFact:
    user_id: UUID
    fact_type: str        # preference / company / role / interest / domain
    key: str              # "preferred_response_style"
    value: str            # "concise"
    source: str           # 哪次对话提到
    confidence: float
    last_seen: datetime
```

**示例**：
- `preferred_response_style: concise`
- `company: 工商银行`
- `role: 投研分析师`
- `domain: 金融 / 财报`
- `language: 中文 (简体)`

### 2.3 Procedural Memory（程序记忆）

**定义**：用户的 *使用模式 / 工作流偏好*

**Schema**：
```python
@dataclass
class ProceduralPattern:
    user_id: UUID
    pattern_type: str         # query_pattern / route_preference / time_pattern
    description: str
    frequency: int
    examples: list[str]
    confidence: float
```

**示例**：
- `query_pattern: 50% queries 查财报 / 30% 查招股书`
- `route_preference: 偏好 KG agentic search 而非 vector hybrid`
- `time_pattern: 周一上午高峰 / 多步推理 query 常在下午`

---

## 3 落点设计（4 个）

### 3.1 落点 A：Memory Models + Storage

**文件**：
- `app/models/memory.py` — DB models（episodic / semantic / procedural）
- `app/rag/memory/schema.py` — Pydantic schemas
- alembic migration

**设计**：
- Episodic：PostgreSQL + 向量索引（pgvector 或 Milvus）
- Semantic：PostgreSQL JSON
- Procedural：PostgreSQL JSON + 定时计算

**新增**：~150 行

### 3.2 落点 B：三层 Memory Service

**文件**：
- `app/rag/memory/episodic.py` — 写入 + 相似度检索 + decay
- `app/rag/memory/semantic.py` — 抽取 + KV 存储 + 冲突解决
- `app/rag/memory/procedural.py` — 模式聚合 + 频率统计

**接口**：
```python
class EpisodicMemoryService:
    async def add_episode(self, episode: EpisodicMemory) -> None: ...
    async def find_similar_episodes(self, query: str, top_k: int = 5) -> list[EpisodicMemory]: ...

class SemanticMemoryService:
    async def add_fact(self, fact: SemanticFact) -> None: ...
    async def get_user_facts(self, user_id: UUID, fact_type: str | None = None) -> list[SemanticFact]: ...
    async def update_fact(self, ...) -> None: ...   # 冲突时合并

class ProceduralMemoryService:
    async def update_patterns(self, user_id: UUID) -> None: ...   # 定时调用
    async def get_user_patterns(self, user_id: UUID) -> list[ProceduralPattern]: ...
```

**新增**：~350 行

### 3.3 落点 C：Memory Consolidation + Pruning

**文件**：`app/rag/memory/consolidation.py`

**功能**：
- 短期 → 长期：会话结束 N 小时后，summary memory → semantic facts 抽取
- 重复 memory 合并：同 fact 多次出现 → 提升 confidence
- 过期清理：episodic > 90 天 + 低重要性 → 归档
- 用户主动忘记：API 支持 `forget_user_memory(user_id, criteria)`

**新增**：~200 行

### 3.4 落点 D：与 RAG 主路径集成

**文件**：`app/rag/engine.py` 修改 + 新建 `app/rag/memory/retrieval_integration.py`

**集成点**：
1. **Query 前**：检索 episodic（"上次类似问题"）+ semantic（"用户偏好"）→ 注入 prompt
2. **检索时**：考虑 procedural（"用户偏好的 retriever"）→ 调整 router
3. **回答后**：写 episodic + 抽 semantic
4. **反馈后**：更新 episodic feedback（与 P0 #5 协同）

**新增**：~150 行

### 3.5 工作量汇总

| 落点 | 行数 | 工时 |
|---|---|---|
| A Models + Schema | 150 | 2 day |
| B 三层 Service | 350 | 5 day |
| C Consolidation | 200 | 3 day |
| D RAG 集成 | 150 | 2 day |
| 测试 + 文档 | 100 | 2 day |
| **合计** | **~950 行** | **~14 day / 2 周** |

---

## 4 Memory 生命周期

### 4.1 写入路径

```
对话 turn → 会话内 (LangGraph checkpoint, 已有)
         ↓ session 结束 N 小时
         → Episodic（保留全部，向量检索）
         ↓ N 周后
         → Semantic（抽取核心 fact）
         ↓ N 月后
         → Procedural（模式聚合）
         ↓ N 年后
         → 归档 / 删除
```

### 4.2 读取路径

```
新 query 进入 →
  并行检索：
  - Episodic：相似度检索 top-5 历史对话
  - Semantic：拉用户偏好（≤ 10 条 fact）
  - Procedural：用户行为模式（≤ 3 模式）
↓
注入 LLM prompt + router decision
↓
LLM 回答 + 写入新 episodic
```

### 4.3 隐私 / 合规

- **Tenant + user 双重隔离**：每条 memory 必须含 tenant_id + user_id
- **加密存储**：semantic facts 加密（含敏感如 company / role）
- **审计**：所有 memory CRUD 入 audit log
- **用户控制**：`/api/v1/memory/forget` 支持选择性遗忘
- **GDPR**：用户删除账号 → 全部 memory 清除

---

## 5 与现有 chat / RAG 集成

### 5.1 与现有 3 种 memory 关系

| 现有 | 本 plan |
|---|---|
| `enable_long_term_memory`（chat 内 toggle） | 升级为 Episodic 后端 |
| `enable_summary_memory`（chat 内 toggle） | 仍保留，作为 episodic 的简短摘要 |
| `enable_structured_memory`（chat 内 toggle） | 升级为 Semantic 抽取 |
| LangGraph checkpointer | 保留（短期会话状态） |

### 5.2 配置

```python
RAG_AGENTIC_MEMORY_ENABLED: bool = False
RAG_MEMORY_EPISODIC_RETENTION_DAYS: int = 90
RAG_MEMORY_SEMANTIC_MAX_FACTS_PER_USER: int = 100
RAG_MEMORY_PROCEDURAL_MIN_FREQUENCY: int = 5
RAG_MEMORY_CONSOLIDATION_FREQUENCY: str = "daily"
```

### 5.3 前端 UI

- `web/app/settings/memory/`：用户可看 / 编辑 / 删除自己的 memory
- 类似 ChatGPT 的"管理记忆"功能
- 显示：episodic 数量 / semantic facts / procedural patterns

---

## 6 评测

### 6.1 评测维度

| Metric | 含义 |
|---|---|
| **Episodic recall** | 相似历史问题被检索到比例 |
| **Semantic accuracy** | 抽取的 fact 正确率（人工标注） |
| **Procedural alignment** | 模式预测与实际行为一致性 |
| **Personalization gain** | with-memory vs without-memory accuracy 提升 |
| **Memory freshness** | 平均 fact 更新延迟 |
| **Privacy compliance** | 删除请求 100% 执行 |

### 6.2 自建评测集

- 模拟 10 个用户 × 30 个 turn 的对话历史
- 标注 *预期 fact / 预期 procedural pattern*
- 评测 with-memory vs without-memory 在第 31 turn 的回答质量

---

## 7 2 周里程碑

### Week 1：Models + 三层 Service

#### Day 1-2（Models）
- [ ] `app/models/memory.py` 三表
- [ ] alembic migration
- [ ] Pydantic schemas

#### Day 3-5（Episodic + Semantic）
- [ ] `app/rag/memory/episodic.py` 写入 + 相似度检索
- [ ] `app/rag/memory/semantic.py` 抽取 + KV 存储 + 冲突
- [ ] 单测覆盖

### Week 2：Procedural + 集成

#### Day 6-7（Procedural + Consolidation）
- [ ] `app/rag/memory/procedural.py` 模式聚合
- [ ] `app/rag/memory/consolidation.py` 短→长迁移 + 清理
- [ ] arq 定时任务

#### Day 8-10（RAG 集成）
- [ ] `app/rag/engine.py` 注入 memory context
- [ ] 与 system_router 集成（procedural → 路由偏好）
- [ ] 与 P0 #5 feedback 集成（feedback 更新 episodic）

#### Day 11-12（前端 UI）
- [ ] `web/app/settings/memory/` 用户 memory 管理
- [ ] 删除 / 导出 / forget API

#### Day 13-14（评测 + GA）
- [ ] 模拟 10 用户评测
- [ ] with vs without memory 对照
- [ ] 隐私 / GDPR 合规测试

---

## 8 风险 + 范围之外

### 8.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Memory 无限增长 | 存储 / 检索成本 | consolidation + pruning |
| 隐私泄露 | 用户 fact 被错误访问 | tenant + user 双重隔离 + 加密 |
| Memory 过拟合用户 | 偏见加深 | confidence 阈值 + 用户可编辑 |
| 跨用户串扰 | 用户 A 的 fact 出现在用户 B | 严格 user_id 过滤 + 测试 |
| Memory 错误污染 | 错误 fact 写入难删 | 用户 UI 编辑 / forget 接口 |
| GDPR / 合规 | 用户要求清除 | forget API + audit log |
| 启动冷启动 | 新用户无 memory 反而拖慢 | confidence 阈值 + 默认关 |

### 8.2 范围之外（明确不做）

- 不做跨用户 memory（隐私）
- 不做组织级 memory（仅个人）
- 不做隐式 fact 抽取（不基于元数据）
- 不做 reflection 机制（Generative Agents 范畴）
- 不做 memory hierarchy 自学习（学术为主）
- 不做 memory 微调 LLM（成本太高）

### 8.3 不要的东西

- ❌ 不要默认全启用（隐私先行）
- ❌ 不要 episodic 全文存储（压缩 + 摘要）
- ❌ 不要无确认抽 semantic（用户必须知道）
- ❌ 不要让 procedural 影响 retrieval 决定权（仅作为 hint）

---

## 9 与既有 plan 协同

| plan | 协同 |
|---|---|
| `rag-feedback-loop-2026-q3.md`（P0 #5） | feedback → episodic feedback 字段 |
| `rag-cross-doc-synthesis-2026-q3.md`（P0 #1） | semantic 中存 *用户认可的来源偏好* |
| `rag-self-consistency-2026-q3.md`（P0 #2） | procedural 决定何时 SC |
| `rag-poc-attribution-framework-2026-q2.md` | episodic 5 字段埋点共用 |
| `rag-evaluation-deep-dive-2026-q2.md` | with-memory vs without-memory ablation |
| `rag-safety-compliance-deep-dive-2026-q2.md` | memory 隐私是 safety 一部分 |

---

## 10 关键洞察

1. **现有 chat memory 是基础**：`structured_memory_service` 抽 entity + fact 已是雏形
2. **三层架构借鉴 MemGPT / 心理学**：Atkinson-Shiffrin 模型 + 工程务实
3. **隐私是底线**：tenant + user 双重隔离 + 用户可编辑可删除
4. **冷启动友好**：默认关 + 累积后启用
5. **与 P0 #5 强协同**：feedback → episodic feedback → 反哺改进
