# RAG POC 归因框架与运营手册（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：第 8 份 RAG 专项，与前 7 份正交——前 7 份偏"业界对标 / 架构 / benchmark / 深度论文"，本文偏"**从 0 到 1 的工程运营手册**"：POC 交付方法 / 极简埋点 / 差评根因归一 / 超纲识别 / 行业规则库产品化。
> **灵感来源**：一线工控售后 RAG 项目的一周付费 POC 复盘（1600+ 份 Word 文档、670 轮对话、53% 反馈率、69.7% 好评率、108 差评根因拆解）。
> **核心主张**：
> 1. **选架构之前先建评测集**（呼应评测集专项）；**评测集之前先建 POC 归因框架**（本文）
> 2. 差评根因**必须拆**成"检索不到 / 答错 / 超纲"三类，**混在一起无法优化**
> 3. **行业 Know-how 可沉淀为规则库**（术语映射 + 问题模式 + 意图分类），是垂直 RAG 的真正护城河
> **交叉引用**：评测集专项（本文是 Stage 0 前置）、Agentic 专项（Query Rewrite / 澄清）、KG 专项（超纲时的兜底）、安全合规专项（反馈记录与审计）。

---

## 1. 付费 POC 的交付逻辑（为何值得系统化）

### 1.1 客户与乙方的双边困境

| 客户侧痛点 | 乙方侧痛点 |
|---|---|
| 不知道 RAG 对自家数据能跑到多少分，怕花大钱踩坑 | 不清楚客户数据质量和场景，不敢承诺交付 |
| 被多个供应商轮番 pitch，难以比较 | 被反复白嫖 demo 耗人耗时 |
| POC 想做"小 MVP"，乙方容易越做越重 | 技术团队爱堆架构，但对最终效果无保证 |

**一周付费 POC** 本质是**用可控成本买一份预期**：客户花小钱拿决策依据、乙方筛项目难度和合作意愿，POC 费用可在正式合作抵扣。

### 1.2 POC 阶段的五条"减法"原则

| 减法 | 不做什么 | 原因 |
|---|---|---|
| 1. 禁用 Rerank | 不上 cross-encoder / LLM rerank | 纯向量都召回不到的 chunk，Rerank 无能为力；**此阶段问题基本在数据清洗** |
| 2. 禁用复杂评估平台 | 不接 Langfuse / RAGAS / Phoenix | 部署复杂度远超收益；**手写 pandas + echarts 足够** |
| 3. Streamlit 前端 | 不做精美 UI | 能对话 / 展引用 / 点赞点踩即可 |
| 4. 极简埋点 | 只记 5 字段（§2） | 多记字段 ≠ 多洞察 |
| 5. 标准化脚手架 | 不从零搭前后端 | 前后端代码 ~固定模板，只留数据清洗做定制 |

**减法后的精力投向**：**80% 时间花在"数据清洗 + 差评根因分析"**，20% 花在"跑通最短链路"。

### 1.3 POC 的唯一目标

用一周回答客户**一个问题**：

> 这套数据在基础 RAG 架构下，能不能把一线同事在微信群的答复工作减轻？

——**不是**"系统完美上线"，**不是**"所有功能全上"。

---

## 2. 5 字段极简埋点（核心建议）

### 2.1 字段表（外加 session_id / created_at 基础字段）

| 字段 | 用途 | 为什么选它 |
|---|---|---|
| `original_query` | 用户原始问题 | **热词分析 + 问题聚类**，看用户到底在问什么 |
| `llm_response` | 完整回答 | 人工抽检质量，**发现"一本正经胡说八道"** |
| `final_context_filenames` | 召回的文档（文件级列表） | **文档热度统计**，发现 80/20 分布 |
| `feedback_score` | 点赞 / 点踩（+1 / -1） | 最直接的满意度信号 |
| `latency_total_ms` | 总耗时 | 宏观响应速度监测 |

### 2.2 明确**不记录**什么（POC 阶段）

| 不记录字段 | 原因 |
|---|---|
| `similarity_score` | 不做阈值调优 |
| `llm_prompt`（full） | 不做 Prompt A/B |
| `rerank_score` | Rerank 已禁用 |
| `embedding_vector` | 不做向量分析 |
| `per_chunk_metadata` | 文件级粒度足够 |

**原则**：**POC 阶段的数据只为回答"系统总体能跑到几分"**，不是为调参。调参字段留给生产版。

### 2.3 双写陷阱（一线踩坑记录）

**错误做法**：同时写 `sessions.jsonl`（追加）+ `sqlite.db`（更新）

```javascript
// 10:00:01 用户提问，写 jsonl + insert sqlite
{ session_id: "sess_abc", query: "...", feedback_score: null }  // jsonl
// 10:00:45 用户点赞 → 只更新 sqlite，jsonl 不变
| session_id | feedback_score |
| sess_abc   | 1              |  // sqlite 已更新，但 jsonl 仍是 null
```

**后果**：分析脚本若读 jsonl 会以为没反馈，读 sqlite 才对得上；两数据源**不一致**。

**原则（本文作者建议）**：**POC 阶段保持"单一数据源"**——要么全 sqlite，要么全 jsonl（但反馈时需能回溯更新），不要搞双写同步。

### 2.4 我方落地建议

- 新增 `app/rag/evaluation/poc_runner/telemetry.py`（~150 行）：
  - 5 字段 + session_id + created_at
  - 单一数据源：SQLite（`qa_sessions` 表，feedback_score 可 UPDATE）
  - 追加 JSONL 作为**只读镜像**（用于快照冻结与离线分析）
- 前端 Streamlit demo：`app/rag/demo/poc_streamlit.py`（~250 行）

---

## 3. 差评三分类根因框架（**最核心增量**）

### 3.1 三分类 taxonomy（来自一线 670 轮项目实证）

| 类别 | 占比 | 定义 | 表现 |
|---|---|---|---|
| **A. 检索不到** | ~24% | 压根没召回相关文档 | 召回列表空或与问题不沾边 |
| **B. 检索到但答错** | ~35% | 找到了 chunk 但回答质量不行 | 理解错 / 格式乱 / 答非所问 |
| **C. 超出知识库范围** | ~37% | 知识库本身无相关文档 | 老师傅脑里的 / 群聊未成文 |
| 剩余 | ~4% | 用户误点 / 环境问题 | — |

**关键洞察**：**37% 的差评其实是"文档不全"，不是模型问题**。修正后的"系统本身好评率" = `(正评 + 超纲差评) / 全量 = (69.7% + 30.3% × 37%) ≈ 79%`，在 POC 阶段已可接受。

### 3.2 A（检索不到）的典型根因

| 根因 | 表现 | 修复方向 |
|---|---|---|
| 口语化 vs 标准术语 | "光电" ≠ "光电耦合器" | **Query Rewrite + 术语映射表**（§7） |
| 切片边界切散关键信息 | 标题与内容分在两块 | 切块策略调整（评测集 + 切块专项） |
| embedding 领域不匹配 | 通用 embedding 不懂工控黑话 | 领域微调 / 术语扩展 |

### 3.3 B（检索到但答错）的典型根因

| 根因 | 表现 | 修复方向 |
|---|---|---|
| LLM 理解错 | 答与问反向 | Few-Shot prompt / RankGPT 抬相关 chunk |
| 输出格式错 | JSON 解析失败 | structured outputs / constrained decoding |
| 答非所问 | 答了相关但非对应 | intent classifier + prompt 指令收紧 |
| top-k 里无相关 chunk 但还是答了 | hallucination | 加 "若无关拒答" 约束 + Citation consistency（安全专项） |

### 3.4 C（超出范围）的典型根因

- 客户以为的**全量文档**实际覆盖 80% 场景
- 老师傅脑里 / 群聊记录 / 未成文 SOP
- 新型号未入库

### 3.5 LLM 辅助标注 + 人工抽检（分工原则）

| 任务类型 | 执行者 | 原因 |
|---|---|---|
| 数值型指标（好评率 / P50 / 文档热度） | **脚本直接统计** | 快、可复现 |
| 语义型分析（差评根因 / 问题模式 / 意图） | **LLM 标注** | 结合 query + response + 召回文档 + 用户评论，效果不比人工差 |
| 终审 | **人工抽检** | 100 条中抽 20 条复核 |

**成本**：108 条差评跑 LLM 分类 ≈ 几块钱 API。

**提示词模板**（供参考）：

```
请根据下列 [用户问题 / 系统回答 / 召回文档 / 用户点踩评论]
判断此差评的根因，从以下三类中选一：
1. retrieval_miss：召回文档与问题不相关
2. generation_error：召回相关但回答错误
3. out_of_scope：知识库中明显缺相关资料
输出 JSON：{"category": "...", "rationale": "...", "confidence": 0.0~1.0}
```

### 3.6 我方落地建议

- **P0** `app/rag/evaluation/poc_runner/attribution_classifier.py`（~200 行）：
  - 按 3 分类 LLM 标注
  - 置信度 < 0.7 的进人工队列
  - 产出分类占比图 + 每类 top 样例
- **P0** `reports/attribution_report.py`：
  - 三分类占比饼图
  - "系统本身好评率"（剔除超纲后）vs "原始好评率" 对比
  - 每分类 top 10 样例
- **交叉引用**：评测集专项 §4 Stage 2 的"hard negative / abstain rate"指标实际对应这里的 A / C 类

---

## 4. 超纲问题的三级验证（给客户的"自证方法"）

当客户质疑 "是模型烂" 还是 "文档不全"，需要**可复现的三级证据链**：

### 4.1 L1：术语展开后关键词零命中

- 对用户 query 做**术语映射**（缩写 / 别名展开，§7 规则库）
- 用展开后的**所有关键词**做 **BM25 / ES 关键词检索**
- 若**仍然零命中** → "可能超纲" 的强信号

### 4.2 L2：向量检索 Top1 相似度阈值

- 向量检索的 **Top1 cosine similarity**
- 如果 **显著低于** 正常匹配分布区间
- **阈值需按 embedding 模型 + 业务数据校准**；工控项目实测经验值 **0.3–0.5**
- 低于阈值 → 语义上根本不沾边的"无人区"

### 4.3 L3：HyDE 反向检索（假设性文档）

- 让 LLM 生成**假设的回答文档**（"如果知识库有，大概会写成什么"）
- 用这段**假设文档**作为新 query 向量检索
- 仍然**零命中**或相似度极低 → 确认超纲

### 4.4 UMAP 向量可视化（客户沟通工具）

- 把全部 chunk 的 embedding 用 **UMAP 降维到 2D**
- 把**正常问题**（绿）与**超纲问题**（红）投射到同一图
- 红点落在**远离所有簇的"无人区"** → 客户一看就懂

**实现**：~50 行 Python（sentence-transformers + umap-learn + matplotlib）。

### 4.5 我方落地建议

- **P0** `app/rag/evaluation/poc_runner/out_of_scope_verifier.py`（~300 行）：
  - 三级验证串联调用
  - 输出 JSON：`{"l1_keyword_hit": bool, "l2_top1_sim": float, "l3_hyde_hit": bool, "verdict": "in_scope" | "ambiguous" | "out_of_scope"}`
  - 阈值参数化（每项目校准）
- **P0** `reports/umap_scatter.py`：生成"知识库向量分布 + 超纲问题投射"的 PNG，客户沟通即用
- **交叉引用**：这与 Agentic 专项的"澄清 agent"对应——**系统**判定超纲时可主动告知用户"此问题超出知识库范围"而非编造答案

---

## 5. 问题模式分析（提炼 query 规律）

### 5.1 三大典型模式（一线观察）

| 模式 | 表现 | 处置 |
|---|---|---|
| **缩写泛滥** | "头子" = 控制器；"485" = RS-485 通讯；"光电" = 光电耦合器；"KS / 组态王" = 同一软件 | 术语映射表 Query Rewrite |
| **多意图 / 模糊意图** | "X 怎么配置，另外上次那个报错" = 2 问题；"系统老是报错" = 缺版本 / 场景 / 型号 | 意图拆分 + 追问 agent |
| **80/20 热点文档** | 1600 份文档里 50 份被反复引用（~80% 流量） | **先把热点 50 份切块 / QA 精调**，再扩长尾 |

### 5.2 工程结论

- **"对全量文档做精细化切分" 是反经济的**
- **先攻高频**（80/20 热点）再扩长尾，是一线实测性价比最高的策略
- 切块专项 §13 的 `chunking_grid/` runner 可扩展"按文档热度分层跑不同策略"

### 5.3 我方落地建议

- **P0** `app/rag/evaluation/poc_runner/query_pattern_miner.py`（~200 行）：
  - 关键词 TF-IDF + 聚类
  - 检测缩写（长度 ≤ 4 字 + 出现频次 ≥ 5）
  - 检测多意图（句子含多个疑问词 / 连接词）
  - 文档热度直方图（final_context_filenames 聚合）
- **P0** 发现的缩写反向填入**术语映射表**（§7）
- **P1** 多意图检测 → Agentic 专项 §7 澄清 agent 的训练数据

---

## 6. 性能归因：排队 vs 真实推理（踩坑记录）

### 6.1 问题场景

- 原始脚本拉出 **P50 = 57s** 延迟
- 客户直觉：模型太慢，需换硬件
- 实际分析：
  - 真实推理首字延迟 **3–5s**
  - 端到端吐完 **20–30s**（Mac Mini 内存带宽所限）
  - 但若 2–3 人同时请求 → **排队叠加** → P50 被拉到 57s，偶发触发 180s 网关超时

### 6.2 修正统计口径

```python
# 过滤超时异常请求，仅统计正常范围
normal_latencies = [l for l in latencies if l['total'] < 150000]  # < 150s
sorted_normal = sorted(normal_latencies, key=lambda x: x['total'])
p50 = sorted_normal[len(sorted_normal) // 2]
```

### 6.3 生产性能优化路径（按客户偏好）

| 客户偏好 | 方案 |
|---|---|
| 成本敏感、部分数据可走云 | **端云协同 router**：敏感查询本地，通用查询走云 API |
| 坚持全私有、并发上来 | **加硬件**（Mac Mini 集群 / 推理加速卡 / vLLM 多卡） |
| 对延迟极敏感 | speculative decoding / FlashAttention / continuous batching |

### 6.4 我方落地建议

- **P1** `app/rag/evaluation/poc_runner/latency_decomposer.py`：
  - 分离 wait_in_queue / model_prefill / model_decode 三部分
  - 输出"真实推理延迟 + 排队延迟"两列
  - 判定是**硬件问题** or **并发问题**

---

## 7. 行业规则库（**产品化关键资产**）

### 7.1 三大组件

#### 7.1.1 术语映射表（Glossary）

| 用户可能表达 | 标准术语 |
|---|---|
| KS / ks | KxxSCADA |
| KIO / kio / io 服务 | KxxIOServer |
| KV / kv / 组态王 | 组态王 (KxxView) |
| 485 / 四八五 | RS-485 通讯线 |
| 头子 / 控制头 | 控制器 |
| 深思锁 / 圣天锁 | 加密锁（具体型号） |

**工程落地**：
- YAML / JSON 存储
- Query Rewrite 模块首先展开
- 同义词可级联（头子 → 控制器 → 具体型号）

#### 7.1.2 问题模式库（Pattern Library）

| 问题模式 | 示例 | 需补充的信息 | 追问模板 |
|---|---|---|---|
| XX 没数据 | "io 没数据" | 哪个软件？采集不到 or 显示不出？ | "请问是 [A/B] 软件？故障表现是 [X/Y]？" |
| XX 崩溃/闪退 | "KS 软件闪退" | OS 版本 / 软件版本 / 崩溃前的操作 | "请提供操作系统版本 + 软件版本 + 崩溃前的操作步骤" |
| 授权失效 | "授权失效了" | 软授权 or 硬件锁 / 具体错误提示 | "请问是 [软授权/硬件锁] 环境？错误提示截图" |

#### 7.1.3 意图分类规则（Intent Taxonomy）

一线工控项目实测 6 类意图：
1. **故障排查与问题解决**（需先确认版本 + 报错信息）
2. **配置与操作指导**（可直接给步骤）
3. **授权与加密锁问题**（需区分软硬授权）
4. **功能咨询与产品介绍**（走产品文档 top-k）
5. **数据存储与历史库**（走专用子集合）
6. **Web 发布与客户端问题**（走专用子集合）

**每类意图对应不同的**：
- 检索策略（偏向哪类文档）
- 回答模板（需包含哪些字段）
- 追问逻辑（若信息不足先追问哪项）

### 7.2 跨行业迁移性（**重要洞察**）

| 组件 | 跨行业迁移度 | 理由 |
|---|---|---|
| **术语映射表结构** | 🟢 高 | 结构通用，换行业只换一批术语 |
| **问题模式库逻辑** | 🟢 中-高 | "追问模板"范式可复用 |
| **意图分类规则** | 🟡 中 | 类目数量相近（通常 5–8 类），具体语义需重定义 |
| 术语 / 模式 / 意图**内容** | 🔴 低 | 必须每行业从 0 积累 |

### 7.3 我方落地建议（最有价值的产品化）

- **P0** `app/rag/industry_rules/` 目录：
  ```
  industry_rules/
  ├── schema.py            # 三大组件的数据模型
  ├── loaders/
  │   ├── yaml_loader.py
  │   └── db_loader.py
  ├── rulesets/            # 每个行业一个子目录
  │   ├── industrial_control/
  │   │   ├── glossary.yaml
  │   │   ├── patterns.yaml
  │   │   └── intents.yaml
  │   ├── water_treatment/
  │   └── ...
  └── appliers/
      ├── query_rewrite.py       # 术语展开
      ├── pattern_matcher.py     # 问题模式匹配 + 追问
      └── intent_classifier.py   # 意图分类 + 策略路由
  ```
- **P0** 接入点：
  - `query_rewrite.py` → `orchestrator.py` 前置
  - `pattern_matcher.py` → 低置信度时触发追问
  - `intent_classifier.py` → 路由到不同检索 profile（对应 Agentic 专项 §7）
- **P1** CMS：
  - `app/api/v1/industry_rules.py`：让业务人员增删改术语 / 问题模式 / 意图规则
  - 版本化 + diff + audit（与安全合规专项 lineage 联动）
- **P1** 自动挖掘：
  - `evaluation/poc_runner/query_pattern_miner.py`（§5）发现的新缩写 / 新问题模式自动建议给 CMS

### 7.4 为什么这是真正的护城河

| 能力 | 是否易被复制 |
|---|---|
| RAG 框架技术栈（LangChain / LlamaIndex / RAGFlow） | 🟢 开源 |
| Embedding / LLM 模型 | 🟢 API / 开源 |
| 切块策略 / Rerank | 🟢 业界已成熟 |
| **行业规则库内容** | 🔴 **需要在具体场景反复打磨**，跨企业难迁移，跨行业不可迁移 |
| **对行业用户表达习惯的理解** | 🔴 **现场工程师 + 客服记录 + 老师傅经验的沉淀** |

垂直 SaaS 的真正壁垒：**"专注一个行业不是局限，而是只有在具体场景反复打磨才能真正深化对技术边界的理解"**——不做通用框架，做专门针对 [工控 / 水处理 / 法律 / 医疗] 的垂直 RAG SaaS。

---

## 8. 好评率修正口径（**评估方法论关键**）

### 8.1 直接好评率的误导

- 原始好评率：**69.7%** —— 看起来及格线
- 剔除 C（超纲，37% of diff）后：**(正评 + 超纲差评) / 全量 ≈ 79%** —— 实际"系统本身能做到"
- **两个数字讲的不是一件事**

### 8.2 建议的评估报表必备字段

| 指标 | 公式 |
|---|---|
| 原始好评率 | 正评 / 全量 |
| **系统可控好评率** | （正评 + 超纲差评）/ 全量 |
| 知识库覆盖率 | 1 - (超纲差评 / 全量) |
| 检索准确率 | 1 - (检索不到差评 / 全量) |
| 生成准确率 | 1 - (答错差评 / 相关召回全量) |

### 8.3 我方落地建议

- **P0** 评测报表模板必包含**以上 5 指标并列**
- 客户沟通时用**"系统可控好评率"**解读，用**"知识库覆盖率"**引导客户补文档
- **交叉引用**：与评测集专项 §5 的 11 维矩阵整合

---

## 9. POC 阶段反馈率的保障（组织配合）

### 9.1 痛点

- 反馈（点赞点踩）**全凭用户自觉**通常反馈率 < 20%
- 样本量不够 → 根因分析失真

### 9.2 解决方案（本项目实证）

| 措施 | 效果 |
|---|---|
| POC 合作协议**明确写入反馈率要求**（≥ 50%） | 客户管理层配合 → 实测反馈率 **53%** |
| **不做系统层强制**（强制拦截会伤用户体验） | 保留用户真实使用习惯 |
| 行政要求 + 轻提醒（系统不拦） | 既拿到数据又不失真 |

### 9.3 我方落地建议

- POC 合同模板加一条："反馈率 ≥ 50%，客户 IT / 业务部门 **行政保障**"
- 周度汇报 "本周反馈率 / 目标反馈率" 趋势图
- Streamlit demo 加 **"点赞点踩才显示下一条"** 的可选开关（某些客户偏好）

---

## 10. 我方落地路径（与前 7 份 plan 的整合）

### 10.1 依赖图

```
Stage -1: 文档摸底 (已有外部工具)
   ↓
Stage 0: POC 一周交付 + 5 字段埋点 + 三分类根因  ←【本文】
   ↓
Stage 1: 真实流量种子 50–200 条（评测集专项）
   ↓
Stage 2: 合成扩展 500–1000 条（评测集专项）
   ↓
Stage 3: 领域 3000–5000 条 + hard negative
   ↓
Stage 4: 动态 / 对抗 / Shadow eval
```

### 10.2 立即可搭建的骨架

```
app/rag/evaluation/poc_runner/
├── telemetry.py                   # 5 字段单源埋点
├── attribution_classifier.py      # 三分类 LLM 标注
├── out_of_scope_verifier.py       # 三级超纲验证
├── query_pattern_miner.py         # 问题模式挖掘
├── latency_decomposer.py          # 延迟分解（排队 vs 推理）
└── reports/
    ├── attribution_report.py      # 三分类报表
    ├── umap_scatter.py            # UMAP 可视化
    ├── coverage_heatmap.py        # 文档热度
    └── feedback_metrics.py        # 5 指标修正口径

app/rag/industry_rules/
├── schema.py
├── loaders/
├── rulesets/
│   └── industrial_control/        # 首个行业模板
│       ├── glossary.yaml
│       ├── patterns.yaml
│       └── intents.yaml
└── appliers/
    ├── query_rewrite.py
    ├── pattern_matcher.py
    └── intent_classifier.py

app/rag/demo/poc_streamlit.py      # POC 演示前端
```

### 10.3 与 7 份现有 plan 的交叉引用

| 本文章节 | 交叉 plan |
|---|---|
| §2 5 字段埋点 | 评测集专项 Stage 0 前置（本 plan 补齐） |
| §3 三分类根因 | 评测集专项 §5 维度矩阵（实证化） |
| §4 三级超纲验证 | KG 专项（超纲时走 web search）+ Agentic 专项 §3 CRAG |
| §5 问题模式挖掘 | Agentic 专项 §7 query 理解 |
| §7 行业规则库 | Agentic 专项 §7 Query Rewrite / 意图路由 + 评测集专项 §2.4 路由 |
| §8 好评率修正 | 评测集专项 §5 dashboard 11 维 |
| §6 性能归因 | 综合报告 §15（观测与成本） |
| §3.5 分工原则 | 评测集专项 §10 陷阱清单 |

---

## 11. 产品化与商业模式（次要但值得记录）

### 11.1 垂直 SaaS 路线（非通用框架）

- **通用 RAG 框架已饱和**（RAGFlow / Dify / FastGPT / LlamaIndex）
- **真正能沉淀的是"对行业数据与用户习惯的理解"**
- 每个垂直领域（工控 / 水处理 / 法律 / 医疗）有自己的规则库

### 11.2 项目类型选择（技术积累均衡）

| 类型 | 技术重点 |
|---|---|
| 知识库问答 | 检索 + 生成 |
| 报告生成 | 长文本 + 格式控制 |
| 合规审查 | 精准匹配 + 风险识别 |
| 隐患识别 | 多模态 |

**建议**：有意识地选项目覆盖不同技术方向，避免单一能力固化。

### 11.3 合作模式

- 一周付费 POC（抵扣正式合作）
- 正式合作：一次性交付 + 年度顾问 / 按次咨询
- **培训客户自主运维知识库**（比长期运维托管更健康）
- 复杂问题按需咨询（灵活）

---

## 12. 总结：本文的 P0 落地清单

| # | 建议 | 预计行数 | 对应章节 |
|---|---|---|---|
| 1 | `evaluation/poc_runner/telemetry.py`（5 字段单源埋点） | ~150 | §2 |
| 2 | `evaluation/poc_runner/attribution_classifier.py`（三分类 LLM 标注） | ~200 | §3 |
| 3 | `evaluation/poc_runner/out_of_scope_verifier.py`（三级超纲验证） | ~300 | §4 |
| 4 | `evaluation/poc_runner/query_pattern_miner.py`（问题模式挖掘） | ~200 | §5 |
| 5 | `evaluation/poc_runner/latency_decomposer.py`（延迟分解） | ~100 | §6 |
| 6 | `reports/{attribution_report,umap_scatter,coverage_heatmap,feedback_metrics}.py` | ~400 | §3 / §4 / §5 / §8 |
| 7 | `industry_rules/` 目录 + schema + appliers + 首个工控 ruleset | ~800 | §7 |
| 8 | `demo/poc_streamlit.py` | ~250 | §1.2 |

**合计 ~2400 行**，4 周可交付；与前 7 份 plan 的 P0 建议**完全正交**，直接补齐"一周 POC 运营工具包"。

**优先做 #1 + #2 + #3**：**5 字段埋点 + 三分类根因 + 三级超纲验证是最小可独立闭环**，两周即可为下一个客户 POC 复用。

---

## 13. 参考资料

### 来源
- 工控售后 RAG 项目复盘（1600+ Word 文档 / 670 轮对话 / 53% 反馈率 / 69.7% 原始好评率 / 79% 系统可控好评率）

### 可视化工具
- [UMAP-learn](https://umap-learn.readthedocs.io/)
- [sentence-transformers](https://www.sbert.net/)
- matplotlib / echarts / streamlit

### HyDE
- [HyDE: Hypothetical Document Embeddings (arXiv:2212.10496)](https://arxiv.org/abs/2212.10496)

### 分析范式
- Pandas 数据分析 + SQLite / JSONL 双存储
- LLM-as-judge 用于语义标注

### 本项目相关 plan
- `plans/rag-capability-gap-2026-q2.md` §14 评测体系
- `plans/rag-deep-research-2026-q2.md` §19 评测与 observability
- `plans/rag-eval-dataset-deep-dive-2026-q2.md`（本文是 Stage 0 前置）
- `plans/rag-kg-deep-research-2026-q2.md`（超纲 fallback 兜底）
- `plans/rag-agentic-reasoning-deep-dive-2026-q2.md`（澄清 agent / Query Rewrite）
- `plans/rag-parsing-chunking-deep-dive-2026-q2.md`（80/20 热点文档切块优先）
- `plans/rag-safety-compliance-deep-dive-2026-q2.md`（反馈 audit / citation consistency）

---

## 结论

1. **POC 归因框架是从 0 到 1 的核心资产**：5 字段埋点 + 三分类根因 + 三级超纲验证 = **任何 RAG 项目都能立即套用**的运营工具包
2. **差评"超纲"占比 37%** 是反直觉但普遍的发现 —— 若不做三分类，会误判"模型不行"
3. **行业规则库是真正的护城河**：技术栈开源、模型可替换，但**术语 / 问题模式 / 意图规则**需要在具体场景反复打磨
4. **垂直 SaaS > 通用框架**：专注一个行业不是局限，是唯一的深度护城河
5. **本文与前 7 份 plan 正交互补**：前 7 份讲"对标谁 / 做什么架构 / 哪个论文要抄"，本文讲"**一周拿结论的标准化方法**"

---

> **可独立拆的子 plan**（按建议顺序）：
> - `plans/poc-telemetry-5-fields.md`（5 字段埋点）
> - `plans/poc-attribution-three-class.md`（三分类根因）
> - `plans/poc-out-of-scope-verifier.md`（三级超纲验证）
> - `plans/poc-query-pattern-miner.md`（问题模式挖掘）
> - `plans/industry-rules-schema.md`（规则库 schema）
> - `plans/industry-rules-industrial-control.md`（首个行业模板）
> - `plans/poc-umap-scatter.md`（客户沟通可视化）
> - `plans/poc-streamlit-demo.md`（POC 前端模板）
