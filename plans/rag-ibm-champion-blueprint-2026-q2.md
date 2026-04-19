# IBM Enterprise RAG Challenge 冠军方案工程蓝图（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：第 10 份 RAG 专项，承接 **Ilya Rice 冠军方案的端到端工程范式**。前 9 份讲"对标业界 / 深度论文 / 分维度深化 / 运营手册 / 预检"；本文讲 **"一个已被实证的冠军方案是如何做工程化决策的"** —— 7 项可直接复用的工程经验，每一项都已在竞赛下打磨过一轮。
> **核心问题**：RAG 竞赛与生产的距离有多近？冠军方案的哪些工程抉择**可直接搬到我方生产管线**，哪些需要针对企业复杂度重写？
> **来源**：Enterprise RAG Challenge（IBM）冠军 Ilya Rice 开源实现 + 社区复现经验 + 免费栈替代方案（MiniLM / Gemini Flash）。
> **交叉引用**：前 9 份 plan 交叉（§11）。

---

## 1. Enterprise RAG Challenge 的工程约束

### 1.1 比赛难点（每一条都是生产常见痛点的极端版）

| 难点 | 对应生产痛点 |
|---|---|
| 100 份 PDF，最长 1047 页，双栏 / 旋转大表 / 图文混排 | 企业真实文档从来不标准 |
| 严格 JSON + 引用页码强制字段，遗漏即 0 分 | LLM 输出格式稳定性 |
| R 只占 1/4 权重但 R 低会拖垮 G | 检索/生成耦合 |
| 题库含"伪公司"或无意义提问 | 知识库超纲判断（呼应 POC 归因专项 §4） |
| 官方仅给"几小时"解析窗口（Ilya 40 分钟完成） | 入库吞吐 |
| 30% 题要求跨公司比较 | 多文档路由 |
| 评分脚本开源，人工抽查页码不能作弊 | 端到端可追溯 |
| 原始数据 46 GB | 资源工程 |
| 100 题 × 多次调用成本自担 | 成本约束 |

**本质**：竞赛把生产中"**精度 × 速度 × 成本**"三角约束**量化 + 透明化**——一切决策必须在量化评分下站得住脚。

### 1.2 冠军方案 5 个核心创新（一句话版）

| 环节 | 做法 | 效果 |
|---|---|---|
| **解析** | 二次开发 Docling + 4090 GPU | 40 min 解析完毕（远快于平均） |
| **切块** | **"一文一库"** + FAISS 独立 + 300/50 | 消除跨公司干扰 |
| **检索** | 30 chunk → 回页去重 → **LLM Rerank 0.7×LLM + 0.3×embed** | 成本 <$0.01/问 |
| **路由** | Regex 抽取公司名 → 选向量库 + 4 套 Prompt | 搜索空间缩小 100× |
| **生成** | **CoT + Pydantic + One-shot + SO Reparser** | 弱模型也 100% 合规输出 |
| **性能** | 25 题并发批量调用 | 100 题 2 min 完成（原要求 10 min） |

---

## 2. 七项工程经验深挖（**最核心章节**）

### 2.1 Docling 深度定制：JsonReportProcessor 范式

**问题**：Docling 原版功能分散在不同配置，无法组合使用（高质量表格解析 + 图片处理 + 结构化 JSON 不能同时拿到）。

**冠军做法**：**完全重写 JsonReportProcessor 类**

```python
# src/pdf_parsing.py
class JsonReportProcessor:
    def assemble_report(self, conv_result, normalized_data=None):
        assembled_report = {}
        assembled_report['metainfo'] = self.assemble_metainfo(data)
        assembled_report['content']  = self.assemble_content(data)
        assembled_report['tables']   = self.assemble_tables(conv_result.document.tables, data)
        assembled_report['pictures'] = self.assemble_pictures(data)
```

**四个工程突破**：

1. **统一数据格式**：Docling 的分散输出 → 单一 JSON 结构
2. **页面标准化**：`_normalize_page_sequence` 填补缺失页，**保证页码连续性**（引用关键）
3. **双格式表格**：同时产 Markdown + HTML，后续序列化可选
4. **双重容错**：
```python
def _table_to_md(self, table):
    try:
        md_table = tabulate(table_data[1:], headers=table_data[0], tablefmt="github")
    except ValueError:
        md_table = tabulate(table_data[1:], headers=table_data[0],
                           tablefmt="github", disable_numparse=True)
```

**我方对应**：`app/deepdoc/parser/docling_parser.py`（388 行）+ `app/parsing/parsers/docling_parser.py`（314 行）**已基于 Docling 改造**，但**尚未引入"JsonReportProcessor 统一装配器"模式**。

**建议**：
- **P0** 重构 `docling_parser.py` 为 JsonReportProcessor 模式，明确 `metainfo / content / tables / pictures` 四大节，**页码连续性校验作为单元测试**
- **P1** 双重容错模式推广到 MinerU / Marker 等其他 parser

---

### 2.2 "一文一库"架构：物理隔离的精度红利

**问题**：传统 RAG 把所有文档混进同一库，跨文档噪声严重。

**冠军做法**：**每个 PDF 对应独立 FAISS 数据库**

```python
# src/ingestion_free.py
faiss_file_path = output_dir / f"{sha1_name}.faiss"
faiss.write_index(index, str(faiss_file_path))
```

**配合 CSV 元数据做智能路由**：

```python
# src/questions_processing.py
def _extract_companies_from_subset(self, question_text: str) -> list[str]:
    found_companies = []
    # 关键优化：按长度倒序，避免短名误匹配（如 "Apple" 抢 "Apple Inc."）
    company_names = sorted(
        self.companies_df['company_name'].unique(),
        key=len, reverse=True
    )
    for company in company_names:
        escaped_company = re.escape(company)
        pattern = rf'{escaped_company}(?:\W|$)'   # 边界匹配避免子串
        if re.search(pattern, question_text, re.IGNORECASE):
            found_companies.append(company)
            question_text = re.sub(pattern, '', question_text, flags=re.IGNORECASE)  # 移除防重
    return found_companies
```

**三个关键细节**：
- **按长度倒序**：防止 "Apple" 抢 "Apple Inc." 匹配
- **边界匹配** `(?:\W|$)`：防止 "Apples" 被当成 "Apple"
- **匹配后移除**：防止同一公司被多次匹配

**效果**：检索空间从 100% → 1%，跨公司噪声基本消除。

**我方对应**：`app/storage/vector/milvus.py` 走 **多 tenant + 多 collection** 范式，粒度是 tenant / dataset 级，**不是文档级**。

**迁移思考**：
- **直接照搬到企业生产不合理**（文档数 100+ → 10000+ → 管理成本爆炸）
- **但"细粒度物理隔离 + 路由"思想可借鉴**：
  - Tenant-level 隔离（已有）
  - Dataset-level 隔离（已有）
  - **新增：按"业务实体"建子分区**（如每个客户、每个产品线），通过 Milvus 的 partition key 实现"逻辑上的一文一库"

**建议**：
- **P1** `retriever.py` 支持 `entity_key` 参数，路由到 partition（不是物理库，而是逻辑分区）
- **P1** 路由工具：`query → 实体抽取（复用 KG entity_verifier）→ partition_keys → 缩小检索空间`
- **P2** 正则边界匹配 + 长度倒序的**实体抽取工具函数**（可独立复用）

---

### 2.3 "小块检索，大块喂食"：精度 × 上下文完整的平衡术

**冠军做法**：

```python
# src/text_splitter.py
def _split_page(self, page, chunk_size: int = 300, chunk_overlap: int = 50):
    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        model_name="gpt-4o",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
```

**数字选择说明**：
- **300 token**：语义单元完整 + 避免碎片化
- **50 overlap**：跨块连续性
- **"小块检索"**：召回时用小粒度（300 token）保证精度
- **"大块喂食"**：召回后**回页合并**（一页 ~1000 token）给 LLM 做 MRC，保证上下文完整

**与业界对标**：
- **Microsoft Azure 推荐 512 + 128**（25% overlap）
- **Ilya 用 300 + 50**（~17% overlap）
- **Vectara NAACL 2025**（arXiv:2410.13070）证明 fixed-size 稳定优于 semantic

**没有"绝对正确"的 chunk_size**，但 300–512 + 15–25% overlap 是 2024–2026 实证有效的经验区间。

**我方对应**：`app/rag/chunking/strategies/{token,recursive,sentence_window,parent_child}.py` 均有实现；但**默认值是否在 300–512 区间、overlap 是否合理，需经 chunking_grid benchmark 实证**（解析切块专项 §13）。

**建议**：
- **P0** 解析切块专项 `chunking_grid/` runner 加入 **Ilya 的 300/50 配置**作为对照组
- **P0** 验证"**小块检索 + 回页喂食**"在我方管线是否落实（`retriever.py` 召回后是否合并同页 chunk）

---

### 2.4 多层路由 + 公司名长度逆序（可复用工具）

**三层渐进路由**：

```
Level 1: 数据库路由（公司名 → 选 FAISS 库）
Level 2: 提示词路由（问题类型 → 选 4 套 Prompt 之一）
Level 3: 复合查询处理（跨公司比较 → 展开为子问题）
```

**工程要点**：
- 每层**解耦、可独立 A/B**
- 每层**失败可降级**（路由失败 → 用默认全库 / 默认 prompt）
- 路由决策全部落日志（便于 bad case 追溯）

**我方对应**：
- `app/rag/policy/{intent_router,intent_router_model,modality_router,must_recall}.py` —— 路由骨架齐
- `app/rag/workflows/routing.py`（246 行）
- **Gap**：层次不够清晰，是否有"跨实体比较 → 子问题展开"的明确 pipeline 未确认

**建议**：
- **P0** `policy/` 统一成三层显式结构：实体路由 / 意图路由 / 复合查询展开
- **P1** 每层决策落 `trace_schema.py` + Prometheus（`router_decision_total{level="entity"|"intent"|"composite"}`）
- **P2** 抽出 `utils/entity_matcher.py`：按长度倒序 + 边界匹配 + 匹配后移除（可独立复用，工控 / 金融 / 法律各场景通用）

---

### 2.5 LLM 重排序加权融合（**具体公式可抄**）

**冠军做法**：

```python
# src/reranking.py
def rerank_documents(self, query: str, documents: list, llm_weight: float = 0.7):
    vector_weight = 1 - llm_weight
    doc_with_score["combined_score"] = round(
        llm_weight * ranking["relevance_score"] +
        vector_weight * doc['distance'],
        4
    )
```

**三个工程细节**：
1. **默认权重 0.7 × LLM + 0.3 × embed** —— LLM 主导，embed 兜底稳定性
2. **ThreadPoolExecutor** 并发跑 LLM 评分（批处理效率）
3. **LLM 响应不完整时自动填充默认评分** —— 系统稳定性

**为什么用加权而非纯 LLM**：
- 纯 LLM 评分**不稳定**（同一 query 多次跑会有分差）
- Vector distance 是**确定性的锚**，+ LLM 的语义判断，稳定性 + 精度兼得

**我方对应**：
- `app/rag/reranker/{cross_encoder,colbert,llm_based,ltr,kg,parent_child,dashscope,openai,hybrid}.py`（9 种）
- `app/rag/reranker/ltr.py` 的 v3 feature spec 已含 fusion signals
- **Gap**：`llm_based.py` 是否实现"加权融合"而不只是"LLM 独立打分"，需确认

**建议**：
- **P0** `llm_based.py` 明确支持 `llm_weight` 参数（默认 0.7）+ ThreadPool 并发
- **P0** 补 fallback：LLM 输出不完整时回填默认分，不崩溃
- **P1** 配置化：每 tenant / query_type 可调权重（简单查询 0.3×LLM，复杂 0.8×LLM）

---

### 2.6 结构化输出容错链（生产级关键）

**三层保障**：

```
Layer 1: CoT 推理字段（引导 LLM 先思考）
Layer 2: Pydantic Schema 约束（约束输出结构）
Layer 3: SO Reparser 自动修复（格式异常自动重试）
```

**Schema 示例**：

```python
# src/prompts.py
class AnswerSchema(BaseModel):
    step_by_step_analysis: str = Field(description="详细的逐步分析过程")
    reasoning_summary: str    = Field(description="推理过程的简洁总结，约50字")
    final_answer: Union[str, int, float, bool]
```

**三个关键细节**：
- `step_by_step_analysis` 字段**不是给用户看**，是**逼 LLM 在产答案前做深层推理**（token budget 给思考用）
- `reasoning_summary` 50 字约束 —— 可用于答案摘要前端展示
- `final_answer` 用 `Union` 支持多类型，**一个 schema cover 所有题型**

**SO Reparser（Structured Output Reparser）**：
- LLM 输出**不符合 schema** → 再调用一次 LLM 让它 reparse
- 比单纯重试更省 token（不用重走思考过程）
- **弱模型配合 reparser** 也能 100% 合规输出

**我方对应**：
- `app/rag/core/claim_verifier.py` + `claim_nli_verifier.py` 有部分
- `app/rag/llm/` 有 factory / prompt_cache，**缺独立的 StructuredOutput 框架**
- LangGraph 本身支持 structured outputs 但 Pydantic + SO Reparser 的组合链路需明确化

**建议**：
- **P0** `llm/structured_output.py`（~200 行）：
  - Pydantic Schema 注册表
  - CoT 字段设计 best practice 文档
  - SO Reparser（自动重试 + 反馈失败原因）
  - Prometheus metrics：`structured_output_retry_total`、`structured_output_schema_error_total`
- **P1** 全项目 structured output 迁入此框架

---

### 2.7 Prompt-as-Code（**最被低估的工程实践**）

**冠军做法**：

```python
# src/prompts.py
class SystemPrompts:
    base_instruction = "您是一个专业的财务分析师..."

class SchemaDefinitions:
    boolean_answer = BooleanAnswerSchema
    numeric_answer = NumericAnswerSchema

class OneShots:
    boolean_example = {
        "question": "示例问题",
        "step_by_step_analysis": "详细分析过程",
        "final_answer": True
    }
```

**核心原则**：
- **Prompt 是业务逻辑的核心载体，应以代码对待**
- 版本控制（Git）
- 类型化（Pydantic / dataclass）
- 单元测试（snapshot test / 回归集）
- 模块复用（SystemPrompts / SchemaDefinitions / OneShots 三层）

**对比常见反模式**：
- ❌ prompt 散落在各处 f-string
- ❌ 改 prompt 不做 A/B 对照
- ❌ one-shot 样例随意硬编码

**我方对应**：
- `app/rag/llm/prompt_cache.py` —— 有 prompt cache 但偏 LLM 侧
- `app/rag/core/query_rewrite_strategy.py` —— 部分 prompt 组织
- `app/rag/middleware/dynamic_prompt.py` —— 动态 prompt 中间件
- **Gap**：缺**统一的 Prompt 类库**（SystemPrompts / Schemas / OneShots 分层）

**建议**：
- **P0** `llm/prompts/` 目录：
  ```
  llm/prompts/
  ├── __init__.py
  ├── system_prompts.py       # 各场景系统提示词
  ├── schemas.py              # Pydantic schema 集中
  ├── oneshots.py             # Few-shot 样例集中
  ├── templates.py            # 组合模板
  └── tests/
      ├── test_prompt_snapshots.py
      └── golden_examples.jsonl
  ```
- **P0** 所有 prompt 进版本控制 + snapshot test
- **P1** Prompt A/B 框架（评测集专项 Stage 3 可加入）

---

## 3. 两个测试问题的语义设计（评测集样本借鉴）

冠军方案复现时选的两个测试问题**非常精妙**，可**直接借鉴为评测集 Stage 2 合成模板**（评测集专项 §4）。

### 3.1 Q1：股票回购计划判断（**时态辨析**）

**考验**：区分"**报告过去活动**" vs "**宣布新计划**"

**关键证据**：
> "Completed NCIB for our common stock. Under our Normal Course Issuer Bid program, launched during 2021, the company purchased 871,135 common shares for cash of $12.4 million during 2022."

**语义陷阱**：
- `Completed`（过去完成时）
- `purchased ... during 2022`（明确过去时态）
- `launched during 2021`（计划 2021 启动，2022 完成）

**系统正确答案**：**否**（有回购**历史**，但**无新计划宣布**）

**借鉴**：评测集 Stage 2 合成"**时态陷阱题**"，测试系统能否区分时态语义。

### 3.2 Q2：并购活动识别（**术语变体 + 分散信息召回**）

**考验**：
- 识别 **多种术语变体**（merger / acquisition / M&A / Business Combination）
- 信息分散在**多个章节**（About Us + Business Strategy）

**证据分布**：
- 第 5 页 About Us：具体被收购公司名单（2020–2022 三年并购案）
- 第 6 页 Business Strategy："Accelerate Growth Through Continued M&A"

**借鉴**：评测集 Stage 2 合成"**术语变体题**"，测试召回是否完整。

### 3.3 合成评测题的**语义难点维度**

基于这两道题提炼出**评测集合成维度表**（可直接用于评测集 Stage 2 的 question generator）：

| 维度 | 说明 | 示例 |
|---|---|---|
| **时态辨析** | 过去 / 未来 / 计划 / 完成 | Q1 回购计划 |
| **术语变体** | 同义词 / 专业术语 / 缩写 | Q2 M&A |
| **信息分散** | 证据在多章节 / 多文档 | Q2 多页 |
| **细粒度类型** | 数值 / 布尔 / 列表 | schema union |
| **跨实体比较** | 2+ 公司 / 产品 / 时间 | 30% 竞赛题 |
| **否定判定** | "未宣布" / "不包含" | Q1 否 |
| **数值单位** | 千 / 万 / 百万 / 十亿 | 财报 |
| **时间范围** | YoY / QoQ / 特定区间 | 财报 |

**建议**：将此 8 维表合入评测集专项 §4 Stage 2 合成 pipeline 作为 **question template library**。

---

## 4. 免费栈替代方案（成本敏感客户）

| 冠军原栈 | 免费替代 | 性能损失 | 备注 |
|---|---|---|---|
| `text-embedding-3-large` (1536 维) | `all-MiniLM-L6-v2` (384 维) | 召回精度 -5~10% | 维度差 4×，但免费 |
| GPT-4o / o3 生成 | Gemini 2.5 Flash | 生成质量略降 | 500 次/日免费 |
| GPT-4o-mini rerank | 省略 rerank | 精度 -3~5% | 或用 BGE reranker 本地 |
| `text-embedding-3-large` | **BGE-M3** | 中英双优 | 本地免费 + 三态产物 |
| 商业 LLM | **vLLM + Qwen2.5-72B** | 本地高质量 | 需 GPU |

**落地建议**：
- 我方做 **"paid / cost-aware / free" 三档 profile** 配置（呼应综合报告 §12 LLM 栈与路由）
- **付费 API / 成本感知路由 / 完全免费** 三档对应不同 tenant 或产品 SKU

---

## 5. 复现管线（本地 / 云端 GPU 两条路径）

### 5.1 本地 GPU 路径（有 NVIDIA GPU + CUDA 环境）

```bash
python -m venv venv
source venv/bin/activate          # macOS/Linux
# ./venv/Scripts/Activate.ps1     # Windows
pip3 install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 \
  --index-url https://download.pytorch.org/whl/cu121
```

### 5.2 云端 GPU 路径（glows.ai / Runpod / Lambda Labs）

```bash
apt update && apt install git -y
python3 -m venv venv && source venv/bin/activate
pip3 install torch==2.1.0 ...     # 同上
```

### 5.3 项目准备与核心流水线

```bash
git clone https://github.com/IlyaRice/RAG-Challenge-2.git
cd RAG-Challenge-2
pip install -e . -r requirements.txt

# 清除作者预处理结果（保证全链路可复现）
rm -rf data/test_set/databases data/test_set/debug_data

# 1. PDF 解析（GPU）
python ../../main.py parse-pdfs

# 2. 表格序列化（可选，Ilya 认为信噪比反而下降）
python ../../main.py serialize-tables

# 3. 入库（免费栈配置）
python ../../main.py process-reports-free --config no_ser_tab

# 4. 问答
python ../../main.py process-questions --config gemini_thinking
```

**关键 flag**：`--config no_ser_tab` 表示**用未序列化表格的数据**——Ilya 的经验是 Docling 原始表格解析已够好，额外序列化反而增加信噪比噪声。

---

## 6. 我方现状对标 + 借鉴优先级

| # | 冠军经验 | 我方状态 | 可借鉴程度 | 建议优先级 |
|---|---|---|---|---|
| 1 | Docling JsonReportProcessor 统一装配 | 已有 Docling parser 但未统一装配 | 🟢 高 | P0 |
| 2 | 一文一库物理隔离 + 公司名路由 | Milvus 多 tenant / collection | 🟡 中（改成 partition key 逻辑隔离） | P1 |
| 3 | 小块检索 + 大块喂食 + 300/50 | 有小块切块，回页合并待确认 | 🟢 高 | P0 |
| 4 | 多层路由 + 长度倒序正则 | 路由骨架齐，层次需显式化 | 🟢 高 | P0–P1 |
| 5 | LLM rerank 加权 0.7 + 0.3 | llm_based 存在但加权公式待确认 | 🟢 高 | P0 |
| 6 | 结构化输出容错链 | claim_verifier + LangGraph，缺独立框架 | 🟢 高 | P0 |
| 7 | Prompt-as-Code 类式组织 | 散落在各处 | 🟢 高 | P0 |
| 8 | 测试问题时态 / 术语变体 / 分散召回 | 评测集专项有框架，缺具体样板 | 🟢 高 | P0（合入评测集） |
| 9 | 免费栈替代（MiniLM / Gemini Flash） | 我方多 provider 支持 | 🟡 中（补 profile 管理） | P1 |

---

## 7. 企业化落地的三大挑战（冠军方案的局限）

### 7.1 数据复杂性升级

| 竞赛 | 企业现实 |
|---|---|
| 100 份 PDF（相对规整财报） | 扫描件 + 多语言 + 非标表 + 历史格式 |
| 单一 PDF 类型 | 25+ 格式（Word/Excel/PPT/图片/邮件/网页/...） |
| 英文为主 | 中英日多语 |

**迁移建议**：
- JsonReportProcessor 范式可保留
- **但具体实现需适配更多 parser**（参考解析切块专项）
- 中文长尾 → Mathpix 专用通道

### 7.2 业务逻辑深度耦合

| 竞赛 | 企业现实 |
|---|---|
| 单公司 QA + 少量跨公司比较 | 跨文档关联分析 / 历史版本对比 / 实时数据更新 |
| 公司名单固定 | 业务实体持续增长 |
| 答案类型枚举 | 开放式问题 |

**迁移建议**：
- "一文一库" → **partition-by-entity + dynamic partition 增长**
- Regex 路由 → **KG entity_verifier 路由**（呼应 KG 专项）
- 静态 schema → **动态 schema registry**

### 7.3 工程经验迁移

**冠军方案最大的价值不是特定技术栈，而是系统性工程思维**：
- **模块化**：技术栈可灵活替换
- **配置驱动**：同一套代码适配不同场景 / 成本
- **验证驱动**：迭代优化方向正确性

**迁移建议**：7 项经验**全部可迁移**，但需结合企业场景深度定制。

---

## 8. P0 / P1 / P2 建议（基于本文增量）

### 🥇 P0（立即可做，预计 2–4 周）

| # | 建议 | 来源 |
|---|---|---|
| 1 | `llm/prompts/` 类式组织（SystemPrompts / Schemas / OneShots） | §2.7 |
| 2 | `llm/structured_output.py` Pydantic + CoT + SO Reparser 框架 | §2.6 |
| 3 | `llm_based.py` rerank 明确 0.7/0.3 加权公式 + ThreadPool + fallback | §2.5 |
| 4 | `docling_parser.py` 重构为 JsonReportProcessor 装配模式 | §2.1 |
| 5 | 评测集 Stage 2 合成模板加入 8 维语义难点表 | §3.3 |
| 6 | chunking_grid runner 补入 300/50 配置作为对照 | §2.3 |

### 🥈 P1（1–2 月）

| # | 建议 | 来源 |
|---|---|---|
| 7 | `policy/` 三层路由显式化 + 决策落 trace | §2.4 |
| 8 | `retriever.py` 支持 `entity_key` → Milvus partition 路由 | §2.2 |
| 9 | `utils/entity_matcher.py`（长度倒序 + 边界匹配工具） | §2.2 |
| 10 | 免费 / 付费 / 成本感知三档 profile 配置管理 | §4 |
| 11 | Prompt A/B 测试框架（评测集配合） | §2.7 |

### 🥉 P2（长期）

| # | 建议 |
|---|---|
| 12 | 动态 schema registry（企业化迁移） |
| 13 | KG entity_verifier 作为路由器 |
| 14 | Prompt snapshot test + CI |

---

## 9. 与前 9 份 plan 的交叉引用

| 本文章节 | 相关 plan |
|---|---|
| §2.1 Docling 定制 | 解析切块专项 §2–3（MinerU 2.5 / Docling 对比） |
| §2.2 一文一库路由 | KG 专项（entity_verifier）；POC 归因专项 §7 行业规则库（意图分类） |
| §2.3 小块检索大块喂食 | 解析切块专项 §7–11（Vectara / Late Chunking / Parent-Doc） |
| §2.4 多层路由 | Agentic 专项 §7 Query 理解；评测集专项 §2.4 RAGRouter-Bench |
| §2.5 LLM rerank 加权 | 综合报告 §9 / 深度调研 §9 |
| §2.6 结构化输出 | Agentic 专项 §6 critic；安全合规专项 §7 citation consistency |
| §2.7 Prompt-as-Code | **全局** —— 所有 plan 的 Prompt 管理都应遵循 |
| §3 测试问题设计 | 评测集专项 §4 Stage 2 合成 |
| §4 免费栈替代 | 综合报告 §12 LLM 栈与路由 |
| §7 企业化挑战 | POC 归因专项 §7 行业规则库 |

---

## 10. 关键数字汇总（来自复现）

| 指标 | 冠军方案 | 我方免费栈复现 |
|---|---|---|
| 解析时间（100 份，最长 1047 页） | **40 分钟**（4090 GPU） | 可复现（本地 / 云端） |
| 成本 / 每题 | **<$0.01** | 免费（Gemini Flash 500/日） |
| 并发问答（100 题） | **2 分钟**（25 并发） | 类似（Gemini 限速略慢） |
| 路由准确率 | — | **100%**（2 题测试） |
| 答案准确率 | — | **100%**（2 题测试） |
| 引用完整性 | 比赛强制 | **100%** |
| Chunk size / overlap | 300 / 50 | 同 |
| LLM rerank 权重 | 0.7 / 0.3 | 未测（复现时省略） |

---

## 11. 参考资料

### 冠军方案
- [Ilya Rice RAG-Challenge-2 GitHub](https://github.com/IlyaRice/RAG-Challenge-2)
- Enterprise RAG Challenge（IBM 主办）
- 冠军方案复盘（公众号 / 知乎文章）

### 技术栈
- [Docling IBM](https://github.com/docling-project/docling)
- FAISS / BM25 / `text-embedding-3-large`
- Pydantic + LangChain
- GPT-4o / o3 / Gemini 2.5 Flash / `all-MiniLM-L6-v2`
- Runpod / glows.ai / Lambda Labs（GPU 分时租赁）

### 本项目相关 plan（交叉引用）
- `plans/rag-capability-gap-2026-q2.md` §6-7 检索重排、§8 生成
- `plans/rag-deep-research-2026-q2.md` §8-9 检索重排
- `plans/rag-eval-dataset-deep-dive-2026-q2.md` §4 Stage 2 合成
- `plans/rag-kg-deep-research-2026-q2.md`（实体路由）
- `plans/rag-parsing-chunking-deep-dive-2026-q2.md`（Docling / 切块）
- `plans/rag-agentic-reasoning-deep-dive-2026-q2.md` §6 critic / §7 query 理解
- `plans/rag-safety-compliance-deep-dive-2026-q2.md`（citation consistency）
- `plans/rag-poc-attribution-framework-2026-q2.md`（行业规则库）
- `plans/rag-pre-poc-scanner-2026-q2.md`（入库前预检）

---

## 12. 结论

1. **冠军方案 7 项工程经验全部可迁移**：Docling 装配器 / 一文一库 / 小块大块 / 多层路由 / 加权 rerank / 结构化容错 / Prompt-as-Code。**每一项都已在竞赛打磨过**，不是论文式假设。
2. **最被低估的经验是 Prompt-as-Code**——业界大部分 RAG 系统的 prompt 散落在各处，冠军方案把它**按代码管理**（类式组织 + 版本 + 测试）。这是最可立即落地的 P0。
3. **一文一库不应照搬**（管理成本爆炸），但"**细粒度物理 / 逻辑隔离 + 实体路由**"思想可迁移——我方走 Milvus partition + entity_verifier 路由。
4. **300/50 vs 512/128 不是非此即彼**：解析切块专项的 chunking_grid runner 应把 Ilya 的 300/50 作为对照组，让数据说话。
5. **两道测试题是评测集合成的精妙样板**：**时态辨析** 和 **术语变体**，合入评测集 Stage 2 的 8 维难点表，立刻增强评测能力。
6. **企业化迁移的关键不是技术栈**，是**模块化 / 配置驱动 / 验证驱动**的工程思维——这些原则贯穿我方前 9 份 plan。

**落地建议**：
- **本周**：启动 P0 第 1–3 项（Prompt-as-Code + Structured Output + LLM rerank 加权）—— 2 周可交付，**立即提升整个栈的工程规范度**
- **本月**：P0 第 4–6 项（JsonReportProcessor / 评测集合成模板 / chunking_grid 300/50）
- **下月及以后**：P1 7 项（路由层次化、entity_key 路由、profile 管理等）

---

> **RAG 专项体系至此共 10 份 plan，合计约 6200+ 行**：
> - 第 1–4 份：综合对标 + 深度调研 + 评测集 + KG
> - 第 5–7 份：Agentic / 解析切块 / 安全合规
> - 第 8 份：POC 归因框架（运营手册）
> - 第 9 份：Pre-POC Scanner（入库前预检）
> - 第 10 份：**IBM 冠军方案工程蓝图（本文）**
>
> 整体覆盖：**理论对标 + 量化 benchmark + 方法论 + 工程范式 + 运营手册 + 入库前 → POC → 生产 全时间线**。
