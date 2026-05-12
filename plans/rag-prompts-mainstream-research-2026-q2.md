# Prompt 工程主流方案调研(KG 抽取 + 内置提示词)— 2026-Q2

> 用户指出前端已有 prompt 页面(KG 抽取提示词 + 内置提示词),需要 WebSearch 业界主流做法形成详细 plan。本文覆盖 ① KG 抽取 prompt(GraphRAG/LightRAG/gleaning)② RAG 系统提示词模板设计 ③ 企业级 prompt 管理平台(LangSmith/Langfuse/Promptfoo/Braintrust)④ 提示词安全(Prompt Guard)⑤ 结构化输出工程化 ⑥ 中文 prompt 实践 ⑦ 评测与 CI 闭环。

---

## 1. Context

### 1.1 起因

用户提示词页面 = 前端有 `/prompts` + `/[locale]/prompts` 模块 + `kg-extract-prompt-settings.tsx`(325 行),后端有 `PromptTemplate` ORM + 470 行 CRUD + A/B 路由器,但**默认内容偏薄**(`system_prompts.py` 仅 26 行)且**安全/评测/中文行业版本 缺位**。

### 1.2 调研问题

1. KG 抽取最先进的 prompt 范式是什么?Microsoft GraphRAG / LightRAG 怎么写?
2. RAG system prompt 怎么设计才不幻觉、强引用?
3. 业界企业 prompt 管理平台横向对比?MimirQ 现有 DB 模型够不够工业级?
4. Prompt injection 怎么防?MimirQ 现在 36 行正则够吗?
5. 中文 prompt 行业实践有什么差异化?

---

## 2. MimirQ 现状盘点

### 2.1 后端 prompt 文件清单(行数实测)

| 文件 | 行数 | 现状评级 |
|---|---|---|
| `app/api/v1/prompt_templates.py` | **470** | ✅ CRUD 完整,A/B 字段 |
| `app/api/schemas/prompt_template.py` | 142 | ✅ Pydantic 完整(template_key/name/content/variables/category/tags/is_active/version/parent_id/ab_experiment_key/ab_variant/ab_weight) |
| `app/models/prompt_template.py` | 90 | ✅ DB ORM 完整 |
| `app/services/prompt_resolver.py` | 99 | ✅ SHA256 稳定 hashing 做 A/B 路由,优先级 id > key > ab |
| `app/services/prompt_defaults.py` | 68 | ✅ dataset-level fallback merge |
| `app/rag/llm/prompts/system_prompts.py` | **26** | ❌ **3 个 prompt,英文 4 句话,无 XML/citation/refusal/conflict** |
| `app/rag/llm/prompts/tagger_prompts.py` | 37 | △ 中文 + JSON schema 完整,但只一个用途 |
| `app/rag/llm/prompt_cache.py` | 92 | ✅ 缓存层 |
| `app/rag/middleware/dynamic_prompt.py` | 305 | ✅ 动态拼装 middleware |
| `app/rag/core/prompt_preview_metrics.py` | 60 | △ 预览指标 |
| `app/rag/safety/prompt_guard.py` | **36** | ❌ **2 条正则 toy**(MEMORY 已记此为 P0 短板) |
| `app/rag/kg/extraction/processor.py` | 172 | △ 单轮抽取,默认 prompt 含 `evidence_quote` 要求(好),**但无 gleaning 多轮** |
| `app/rag/kg/extraction/extractor.py` | **2556** | ✅ 42+ 处 prompt selector 引用,支持 id/key/ab |
| `app/rag/kg/extraction/relation_processor.py` | 266 | 同 processor |
| `app/rag/evaluation/datasets/stage3_adversarial/prompt_injection.jsonl` | n/a | ✅ 已有红队数据集 |

### 2.2 前端 prompt 页面

| 路径 | 用途 |
|---|---|
| `web/app/prompts/` | 默认语言版页 |
| `web/app/[locale]/prompts/` | i18n 多语言版 |
| `web/components/kg-extract-prompt-settings.tsx`(**325 行**) | KG 抽取 prompt 选择器(id/key/ab) |

### 2.3 关键发现

- **基建优秀**:DB schema + Pydantic + A/B 路由 + cache + middleware + 前端选择器全栈齐备
- **内容偏薄**:仅 3 个英文系统提示词 + 1 个中文 tagger;**没有 KG 抽取的默认 prompt 模板**(processor.py 走 hard-coded fallback)
- **安全玩具级**:`prompt_guard.py` 36 行只有两条正则("忽略.*规则|ignore" / "DAN|越狱"),Llama Prompt Guard 2 86M 实测能区分 benign/injection/jailbreak 三类多语言
- **无评测闭环**:有 `prompt_preview_metrics.py` 60 行预览,但**没有 Promptfoo/Braintrust 风格的 regression**
- **KG 抽取无 gleaning**:Microsoft GraphRAG 经验是单轮丢一半 entity,需要多轮"还有遗漏吗?"自反思

---

## 3. 业界主流方案横向矩阵(10 维 × 10 家)

| 厂商/项目 | 默认 KG prompt | XML 标签 | 多轮 gleaning | A/B 实验 | 评测集成 | 版本管理 | 安全分类器 | 中文 |
|---|---|---|---|---|---|---|---|---|
| **Microsoft GraphRAG** | 标准 + FastGraphRAG | 否(用 `{tuple_delimiter}`) | ✅ 1-3 轮 | ❌ | ❌ | YAML config | ❌ | 部分 |
| **LightRAG** | dual-level + dedup | 否 | ✅ + 增量删除 | ❌ | ❌ | git | ❌ | ✅ |
| **LlamaIndex GraphRAG V2** | Cookbook 模板 | 部分 | ❌ | ❌ | trulens 集成 | git | ❌ | △ |
| **LangChain** | n/a | 框架级 | n/a | ✅ LangSmith | ✅ | ✅ | ❌ | △ |
| **Claude / Anthropic** | n/a | **★XML 是官方推荐** | n/a | n/a | n/a | n/a | ❌ | ✅ |
| **LangSmith** | n/a | n/a | n/a | ✅ commits+tags | ✅ Playground | ✅ | ❌ | ✅ |
| **Langfuse**(开源) | n/a | n/a | n/a | ✅ labels | ✅ trace+eval | ✅ 自动+手动 | ❌ | ✅ |
| **Promptfoo**(开源 CLI) | n/a | n/a | n/a | ✅ YAML | ✅ **+red teaming** | git | △(red team 集成) | ✅ |
| **Braintrust** | n/a | n/a | n/a | ✅ **GitHub Action 自动** | ✅ Playground+CI | ✅ immutable snapshot | ❌ | ✅ |
| **Llama Prompt Guard 2** | n/a | n/a | n/a | n/a | n/a | n/a | **★benign/injection/jailbreak 三分类多语言** | ✅ |

---

## 4. KG 抽取 Prompt 专项(对 `/prompts` 页 KG 抽取部分)

### 4.1 Microsoft GraphRAG 标准抽取范式

**Prompt 四段式结构**(arXiv 2404.16130v2):
1. **Extraction instructions**:抽取指引(实体类型清单 + 关系定义)
2. **Few-shot examples**:示例 3-5 个,**质量比数量重要**
3. **Real data**:`{input_text}` 占位符
4. **Gleanings**:多轮自反思 prompt

**Token-replacement 标准** (GraphRAG 已落定):
```
{tuple_delimiter}    # 字段分隔(默认 <|>)
{record_delimiter}   # 记录分隔(默认 ##)
{completion_delimiter} # 结束标记(默认 <|COMPLETE|>)
```

**输出格式**(实体 + 关系两种 tuple):
```
("entity"{tuple_delimiter}<name>{tuple_delimiter}<type>{tuple_delimiter}<description>)
("relationship"{tuple_delimiter}<source>{tuple_delimiter}<target>{tuple_delimiter}<description>{tuple_delimiter}<strength_score>)
```

### 4.2 Gleaning(多轮自反思)— 这是 MimirQ 最大缺口

**机制**:抽完一轮后,把已抽实体 echo 回 LLM,问"还有遗漏吗?"(logit_bias=100 强制 yes/no);如答 yes,继续 prompt "MANY entities were missed in the last extraction"。

**实测收益**(GraphRAG paper):
- 600 tokens chunk:gleaning 0 vs 2 轮,entity 数 +47%
- **2400 tokens chunk:不开 gleaning 比 600 tokens chunk 少 50% entities**

**MimirQ 现状**(`processor.py:24-172`):**单轮 `llm_client.chat_with_schema(...)` 调用,无 gleaning 迭代**。

### 4.3 LightRAG 双层抽取(EMNLP 2025)

- **Low-level**:实体 + 邻近关系
- **High-level**:跨段实体 + 主题/概念关系
- **Dedup function**:同实体不同段融合,减小图规模
- **10x token reduction vs GraphRAG**(comparable accuracy)
- **2025-09**:Qwen3-30B-A3B 适配增强;reranker 集成;文档删除 + KG 自动 regen

### 4.4 FastGraphRAG(2025 新)

- 实体 = spaCy/NLTK noun phrases(**无 LLM**)
- 关系 = 共现 in same chunk
- 成本降 75%(LLM extraction 占整体 75% 成本)
- **代价**:图噪声大,只适合 GraphRAG 内部检索,不适合对外输出

### 4.5 LightRAG / GraphRAG 抽取 prompt 关键设计模式总结

| 模式 | 是否在 MimirQ | 改进点 |
|---|---|---|
| Few-shot 示例(3-5 个) | ❌ 默认 prompt 没示例 | P0 加 |
| `{tuple_delimiter}` token replacement | ❌(用 JSON schema) | P1 可选 |
| **Multi-round gleaning** | ❌ | **P0 必须加** |
| evidence_quote 字段 | ✅ 已有(`processor.py:75`) | 保持 |
| entity_type 受限词表 | △ 自由文本 | P1 配 enum |
| relationship_strength 分数 | △ | P1 加 |
| 增量删除时 KG 自动 regen | ❌ | P2(对照 LightRAG 2025-08) |
| Auto-tuning(GraphRAG Microsoft Research) | ❌ | P2 调研 |

### 4.6 LightRAG dedup 模式补 MimirQ

LightRAG 的 dedup 是**抽取后内部融合**(同段 vs 跨段),与 MimirQ 现有 `processor.py:125-159` 的 entity_map merge(longer description wins)思路一致,但**LightRAG 还做了跨 chunk 的实体融合(基于 KG 主键)**,MimirQ 走 `app/rag/kg/loading/` 的写入阶段处理,职责分明。

---

## 5. RAG System Prompt 设计模式

### 5.1 Claude XML 标签结构(Anthropic 官方推荐)

```xml
<instructions>
You are a retrieval-grounded enterprise knowledge assistant.
1. Answer ONLY from <context>...</context>.
2. Cite specific passages via <source idx="N"/>.
3. If context is insufficient, respond: "I cannot answer from the available materials."
4. If sources conflict, list both and indicate which is more authoritative.
</instructions>

<context>
  <document index="1" source="contract_2024.pdf" page="12">
    {chunk_1}
  </document>
  <document index="2" source="policy.md" section="3.2">
    {chunk_2}
  </document>
</context>

<question>{user_question}</question>

<thinking>
{Claude 内部 CoT,可选}
</thinking>

<answer>
{最终答案 + 引用}
</answer>
```

**关键原则**(Anthropic 文档):
- Claude 训练数据里 XML 标签密集,**比 markdown 解析更稳**
- 标签嵌套 = 自然层级(`<documents>` 含多个 `<document>`)
- `<thinking>` + `<answer>` 双标签 = 自带 CoT
- Pre-fill assistant 第一个 token 是 `{`,可强制 JSON 输出

### 5.2 RAG 三层 prompt stack(2025 主流)

```
[System Layer]  ← 域规则 + 引用要求 + 输出格式 + refusal
[Context Layer] ← <documents> 含 metadata(source/timestamp/relevance/access_level)
[User Layer]    ← <question> + <history>
```

### 5.3 引用/拒答/冲突 三件套(Stanford 法律 RAG 2025 教训)

Stanford 实证 LexisNexis Lexis+ AI 和 Westlaw AI 的法律 RAG 仍**幻觉 17-33%**——重新定义 hallucination:**引用错误也算**。

**最低标准**:
1. **强制引用**:每个事实陈述带 `<source idx="N"/>`
2. **refusal 机制**:context 不够答时,必须说"I don't know",不许编造
3. **冲突处理**:不同文档矛盾时,**列出双方 + 标注优先级理由**(时间 / 权威 / 上下文)

### 5.4 FACTUM 框架(citation hallucination 机制论 2026)

引用错误的真正原因是 **Attention(读)和 FFN(回忆)的协调失败**,需:
- **CAS**(Contextual Attention Score):看上下文权重够不够
- **BAS**(Behavioral Attribution Score):看模型是否在真用上下文还是回 parametric memory

可作为 P2 评测指标。

### 5.5 MimirQ system_prompts.py 升级清单

**现状**(`system_prompts.py` 全文 26 行):
```python
KB_ASSISTANT_SYSTEM_PROMPT = "You are a retrieval-grounded enterprise knowledge assistant.\nOnly answer from the provided context.\nIf the answer is unsupported, say you cannot answer from the available materials.\nKeep answers concise, accurate, and citation-friendly."
```
+ KB_SUMMARY + KB_ACTION_ITEMS

**目标(SKOS-XML-citation-refusal)**:见 §11.1 P0 清单。

---

## 6. 企业 Prompt 管理平台对比

### 6.1 五大平台矩阵

| 平台 | 开源 | 自部署 | A/B | Eval | Red team | CI/CD | 价格 |
|---|---|---|---|---|---|---|---|
| **Langfuse** | ✅ MIT | ✅ Docker | ✅ labels | ✅ tracing+eval | ❌ | △ 自写 | 自部署免费 |
| LangSmith | ❌ | ❌ | ✅ commits+tags | ✅ | ❌ | ✅ | $39/seat |
| **Promptfoo** | ✅ | ✅ CLI | ✅ YAML | ✅ batch | ✅ **专长** | ✅ GH Action | 全免 |
| Helicone | ✅ | ✅ | △ | △ centralize | ❌ | △ | freemium |
| **Braintrust** | ❌ | ❌ | ✅ playground | ✅ experiment | ❌ | ✅ **GH Action 最佳** | enterprise |

### 6.2 推荐路线

- **MimirQ 自带 PromptTemplate ORM + A/B 路由 + cache** 已经具备 70% Langfuse 功能
- **缺**:Eval 闭环 / Red team / CI 自动门控
- **推荐**:
  - **本地 dev/CI** 集成 **Promptfoo**(YAML + GitHub Action + red team 一体)
  - **production tracing** 走自家 `app/observability/`(已有 OTel)+ Langfuse self-host(可选,如果客户要 dashboard)

### 6.3 版本管理 6 大最佳实践(2025)

1. **Treat prompts as versioned assets**(MimirQ ✅ 已有 version+parent_id)
2. **Use labels instead of hardcoded versions**(MimirQ ✅ ab_experiment_key 已是 label)
3. **Combine auto + manual versioning**(MimirQ △ 仅手动)
4. **Integrate regression into CI/CD**(MimirQ ❌)
5. **Pair versioning with observability context**(MimirQ ✅ 有 OTel)
6. **Use SDKs for programmatic mgmt**(MimirQ ✅ 470 行 API)

---

## 7. 提示词安全 — Prompt Injection / Jailbreak 防御

### 7.1 攻击分类

- **Prompt Injection**:第三方数据/用户输入注入指令(`<context>` 被污染)
- **Jailbreak**:绕过模型安全围栏(DAN / 角色扮演 / Unicode 隐藏)

**真实事故**(Chevy 案):被改 prompt 后给客户报价 \$1 卖 Chevy Tahoe(标价 \$76k)。

### 7.2 Llama Prompt Guard 2(2025-04 发布)

| 版本 | 大小 | 多语言 | 用途 |
|---|---|---|---|
| Llama Prompt Guard 2 86M | mDeBERTa-base | ✅ 8 种(含中文场景) | benign/injection/jailbreak 三分类 |
| Llama Prompt Guard 2 22M | DeBERTa-xsmall | ❌ 仅英文 | 资源受限场景 |

**约束**:
- Context window 512 tokens — 长输入需切片+并行
- 输出仅 label,无 prompt 结构要求(比 Llama Guard 3 容易部署)
- CPU 可跑(无需 GPU)

### 7.3 双层过滤策略

| 输入源 | 应用 filter |
|---|---|
| 用户输入 | 仅 `jailbreak`(允许"prompt-like"内容) |
| 第三方 context(RAG 检索文档) | `injection` + `jailbreak`(stricter) |

### 7.4 已知绕过(2025-05 Trendyol 报告)

- Multi-lingual 混杂注入
- Unicode 隐形字符(zero-width / RTL override)
- emoji smuggling
- LlamaFirewall 现在 SQL injection 检测不全(CODE_SHIELD)

**结论**:Prompt Guard **必须配合**:
1. RAG 主路径前再过 LLM-as-judge(Claude Haiku 二次审)
2. Output guard(Llama Guard 3 content safety)
3. **Fine-tune 在自己应用分布上**(关键!Meta 文档原话)

### 7.5 MimirQ prompt_guard.py 升级(36 → 200+ 行)

**现状**:
```python
_INJECTION_RE = re.compile(r"忽略.*规则|ignore.*instruction|system prompt", flags=re.IGNORECASE)
_JAILBREAK_RE = re.compile(r"\bDAN\b|角色扮演|越狱|act as root", flags=re.IGNORECASE)
```

**P0**(对照 MEMORY 中已记录的 P0 安全短板):
- 接 Llama Prompt Guard 2 86M(transformers + CPU 部署)
- 512 token 分片 + max probability merge
- 双层 filter(input vs context)
- 保留 regex 作 fast path(避免 86M model warm-up 延迟)
- 接 `app/rag/evaluation/datasets/stage3_adversarial/prompt_injection.jsonl`(已有红队集)做 fine-tune

---

## 8. 结构化输出工程化

### 8.1 工程范式 4 件套

```
Pydantic schema  ← 类型 + Field description + 例值
       ↓
provider native(OpenAI structured_outputs / Anthropic .parse() / DashScope JSON mode)
       ↓
validation(Pydantic)
       ↓
retry on failure(Instructor 库 max_retries=3,把错误传回模型)
```

### 8.2 关键陷阱(2025 整理)

1. **`minimum/maximum` 等约束被 OpenAI strip**,要放到 description 字符串(SDK 会传过去),Pydantic 再校验
2. **首请求 grammar 编译延迟 < 10s**,后续快(同 schema 缓存)
3. **`stop_reason` 必查**(refusal / max_tokens 导致 schema bypass)
4. **temperature=0** 抽取必备
5. **Field description 而非裸 type**:`date: str` vs `date: str = Field(description='ISO 8601 date YYYY-MM-DD')`,后者命中率高很多

### 8.3 MimirQ KG 抽取 structured output 改进

**现状**:`processor.py:112` 走 `chat_with_schema`,**schema 字段无 description**:
```python
"name": {"type": "string"},
"type": {"type": "string"},
"description": {"type": "string"},
"evidence_quote": {"type": "string"},
```

**升级**:
```python
"name": {"type": "string", "description": "Entity surface form, copied verbatim from <Target>"},
"type": {"type": "string", "enum": ["Person","Org","Location","Concept","Event","Product","Date","Quantity","Other"]},  # ← 受限!
"description": {"type": "string", "description": "Comprehensive description of attributes and activities, 50-120 chars"},
"evidence_quote": {"type": "string", "description": "Exact verbatim substring from <Target> that mentions this entity (no paraphrase)"},
```

### 8.4 重试 / 修复闭环(Instructor 模式)

```python
async def extract_with_retry(messages, schema, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await llm_client.chat_with_schema(messages, response_schema=schema)
        except ValidationError as e:
            messages.append(LLMMessage(role=LLMRole.USER,
                content=f"Validation failed: {e}. Fix and retry."))
    raise
```

---

## 9. 中文 Prompt 工程实践

### 9.1 LangGPT 结构化方法论(中文社区主流)

```markdown
# Role: 法律咨询顾问

## Profile
- Author: MimirQ
- Version: 1.0
- Language: zh
- Description: 基于检索到的法律法规条款回答企业咨询

## Skills
1. 精读 <context> 内法律条款
2. 引用条款编号(如 第 N 条)
3. 拒答 context 外的问题

## Constraints
- 不能给出超出 <context> 的法律意见
- 引用必须精确到条款号
- 拒答时必须用"<context> 中未包含该信息,请补充材料"

## Workflow
1. 在 <thinking> 标签内分析问题与 <context> 的相关性
2. 在 <answer> 标签内给出引用 + 答案
3. 如果 context 不足,直接 refusal

## Examples
<example>
<question>员工试用期最长多久?</question>
<answer>根据《劳动合同法》第十九条 [src=1],试用期...</answer>
</example>
```

**对比 Claude XML**:LangGPT 用 Markdown 标题分段,**对中文 GPT/Qwen/DeepSeek 友好**;**Claude 走 XML 更稳**。MimirQ 应支持双模板,按 model_family 切换。

### 9.2 阿里云百炼 BPSC 框架

**B**ackground / **P**urpose / **S**tyle / **C**onstraints 四段式。模板生成接口在阿里云百炼控制台内置。

### 9.3 中文 RAG prompt 4 个关键差异

1. **拒答措辞**:英文"I cannot answer" → 中文"我无法基于现有材料回答该问题"(避免被理解为不会用功能)
2. **引用格式**:英文 `<source idx="1">` → 中文"[来源 1]"或"《文件名》第 N 条"
3. **冲突表述**:中文需要更明确,"两处材料存在差异" 而非 "sources differ"
4. **行业术语**:法律 prompt 用"鉴于"/"兹此",医疗用"主诉/现病史",金融用"截至报告期末" — 体现在 prompt **示例段**

---

## 10. Prompt 评测与 CI 闭环

### 10.1 评测维度(对齐 Braintrust 2025 标准)

| 维度 | 指标 | MimirQ 现状 |
|---|---|---|
| **Faithfulness** | 答案是否仅依赖 context | △ 有 RAGAS 集成 |
| **Citation correctness** | 引用是否准确映射到 chunk | ❌ |
| **Refusal accuracy** | 该拒答时是否拒答 | ❌ |
| **Conflict handling** | 冲突文档处理 | ❌ |
| **KG extraction P/R/F1** | 实体 / 关系召回精度 | △ 在 `evaluation/` 已有 |
| **Latency** | p50/p95 | ✅ OTel |
| **Cost** | tokens/USD per call | △ 部分 |
| **Format compliance** | 输出是否符合 schema | △ Pydantic 检 |

### 10.2 推荐 CI 流水线(Promptfoo + GitHub Action)

```yaml
# .github/workflows/prompt-eval.yml
on:
  pull_request:
    paths:
      - 'app/rag/llm/prompts/**'
      - 'app/api/v1/prompt_templates.py'
      - 'evaluation/prompts_golden_set/**'

jobs:
  prompt-eval:
    runs-on: ubuntu-latest
    steps:
      - uses: promptfoo/setup-promptfoo@v1
      - run: promptfoo eval -c evaluation/prompts_golden_set/promptfoo.yaml --output report.json
      - run: promptfoo eval -c evaluation/prompts_golden_set/red_team.yaml
      - uses: actions/github-script@v6
        with:
          script: |
            // Block merge if recall drops > 3pt or red-team ASR > 5%
```

### 10.3 Golden Set 三级体系(对齐 §5.3 Stanford 教训)

1. **正常问答** 50 题:基础准召
2. **应该拒答** 50 题:测 refusal(超纲 / context 缺失 / 矛盾)
3. **对抗集** 50 题:测 prompt injection + jailbreak(已有 `prompt_injection.jsonl`)

---

## 11. P0 / P1 / P2 修复清单

### 11.1 P0(2-3 周,内容补强 + 安全升级 + 评测闭环)

| 任务 | 落点 | 估算 |
|---|---|---|
| **system_prompts.py 升级 26 → ~300 行 / 8 套**(KB_ASSISTANT_V2 含 XML + citation + refusal + conflict + 3 行业版本 legal/finance/medical) | `app/rag/llm/prompts/system_prompts.py:1` | 1.5 day |
| **KG 抽取默认 prompt 升级**:四段式(instructions + few-shot 3-5 + real_data + gleanings)+ entity_type enum + relationship_strength | `app/rag/llm/prompts/kg_extraction_prompts.py`(new)+ `processor.py:99-109`(fallback)+ `extractor.py` 透传 | 2 day |
| **KG 抽取 gleaning 多轮**:max_gleanings=1-2 配置,自反思 prompt | `processor.py:24-172` 扩 | 1.5 day |
| **Schema field description 全面补全**:KG schema + tagger schema 加 `description` + `enum` | `processor.py:57-84`、`tagger_prompts.py` | 0.5 day |
| **Retry on validation failure**:Instructor 风格 max_retries=3 | `app/rag/llm/base.py` chat_with_schema 加 retry | 1 day |
| **Prompt Guard 升级**:接 Llama Prompt Guard 2 86M + 512 切片 + 双层 filter + regex fast path 保留 | `app/rag/safety/prompt_guard.py:1` 36 → ~200 行 | 2 day |
| **Promptfoo CI 集成**:`evaluation/prompts_golden_set/` 50+50+50 + `.github/workflows/prompt-eval.yml` | new | 2 day |
| **Citation correctness 评测器**:对每个答案验证 `<source idx="N"/>` 真指向被引 chunk | `app/rag/evaluation/citation_eval.py`(new) | 1 day |
| **Refusal 评测器**:50 题应拒答集 + 判定模型 | `app/rag/evaluation/refusal_eval.py`(new) | 1 day |
| **中文行业 prompt 3 套**:LangGPT 风格(legal_consultant / finance_analyst / medical_assistant) | `app/rag/llm/prompts/industry_zh/`(new) | 1.5 day |
| **A/B variant 实际跑起来**:把 `prompt_resolver.py` 路由结果写 trace(`message_metadata.prompt_variant`),对比 production 数据 | `app/rag/engine.py` 调用点 | 0.5 day |

### 11.2 P1(1 个月,平台化 + 多语言)

1. **Langfuse 自部署 + prompt sync**(MimirQ DB ↔ Langfuse;客户要 dashboard 时可启)
2. **KG 抽取 auto-tuning**(对照 Microsoft Research 2024-09):用客户 3-5 个 sample 自动调 few-shot,产出 domain-specific prompt
3. **Output Guard**(对照 Llama Guard 3):**前一份 MEMORY 已记为 P0 安全短板**,本份合并实施
4. **Multi-lingual prompt pack**:英 / 简中 / 繁中 / 日 / 韩 切换(`language` 字段已在 ORM,API 透传即可)
5. **Prompt Telemetry Dashboard**:`/observability/prompts` 页 — 每个 template 的命中率/平均 tokens/usage_count/A-B 胜率(已有 `usage_count` 字段)
6. **Citation hallucination FACTUM 评测**(CAS + BAS):需要 model internals,P1 末调研可行性

### 11.3 P2(独立调研,1-2 季度)

| 项 | 内容 |
|---|---|
| LightRAG dual-level + dedup 落地 | KG 抽取改双层(low/high) |
| FastGraphRAG 降本路径 | 提供 `extract_mode=fast` 选项,spaCy + 共现,客户大语料初次 ingest 用 |
| Tree-of-Thoughts / Self-consistency for high-stakes | 法律/医疗/金融问答可选,N=3-5 sampling + majority vote |
| Prompt Tuning(soft prompts)实验 | LoRA + Qwen2.5,客户私有部署场景 |
| Prompt Marketplace(行业模板包) | 法律 / 医疗 / 金融 / 工控 / 政务 5 个开箱即用包,对齐 industry_rules 商业化路径 |

---

## 12. 关键文件清单(将动)

### 后端 P0
- `app/rag/llm/prompts/system_prompts.py:1`(26 → ~300 行,8 套含中英 + 3 行业)
- `app/rag/llm/prompts/kg_extraction_prompts.py`(new,GraphRAG 四段式 + few-shot 3-5)
- `app/rag/llm/prompts/industry_zh/{legal_consultant,finance_analyst,medical_assistant}.py`(new)
- `app/rag/kg/extraction/processor.py:24-172`(加 gleaning 多轮,schema field description+enum)
- `app/rag/kg/extraction/extractor.py:281-303`(透传 gleaning 参数)
- `app/rag/llm/base.py`(chat_with_schema 加 retry on validation)
- `app/rag/safety/prompt_guard.py:1`(接 Llama Prompt Guard 2 86M)
- `app/rag/engine.py`(prompt_variant 写 trace)
- `app/rag/evaluation/citation_eval.py`(new)
- `app/rag/evaluation/refusal_eval.py`(new)

### 评测+CI(P0)
- `evaluation/prompts_golden_set/positive_50.jsonl`(new)
- `evaluation/prompts_golden_set/refusal_50.jsonl`(new)
- `evaluation/prompts_golden_set/adversarial_50.jsonl`(已有 `app/rag/evaluation/datasets/stage3_adversarial/prompt_injection.jsonl`,复用 + 补)
- `evaluation/prompts_golden_set/promptfoo.yaml`(new)
- `evaluation/prompts_golden_set/red_team.yaml`(new)
- `.github/workflows/prompt-eval.yml`(new)

### 前端(P1)
- `web/components/prompts/prompt-eval-history.tsx`(new,A/B 胜率 + Faithfulness 时序)
- `web/components/prompts/citation-coverage-card.tsx`(new)
- `web/components/prompts/refusal-pattern-card.tsx`(new)
- `web/components/kg-extract-prompt-settings.tsx:1`(加 gleaning_max + entity_type_enum 配置项)

### 测试
- `tests/test_kg_extraction_gleaning.py`(new)
- `tests/test_system_prompts_xml_structure.py`(new)
- `tests/test_prompt_guard_llama_v2.py`(new)
- `tests/test_citation_eval.py`(new)
- `tests/test_refusal_eval.py`(new)

---

## 13. 验证

### 13.1 P0 验证

1. `pytest tests/test_*prompt* tests/test_*kg_extraction_gleaning*` 全绿
2. KG 抽取 gleaning 开关对比:同一 600-token chunk,gleaning=0 vs 2,**实体召回 +40% 以上**(对齐 GraphRAG paper)
3. Prompt Guard 在 `prompt_injection.jsonl` 上 ASR(攻击成功率)≤ 5%
4. Golden Set 正常 50 题:Faithfulness ≥ 0.85,Citation correctness ≥ 0.90
5. Refusal 50 题:正确拒答率 ≥ 0.95
6. GitHub Action PR 改 `prompts/**` 自动跑 promptfoo,**threshold 不达就 block merge**
7. 起服务 → /prompts 页选 `legal_consultant_zh` → chat 问"什么是不可抗力" → trace 应含完整 XML 结构 + `<source idx="N"/>` + variant 写入 message_metadata

### 13.2 P1 验证

1. Langfuse self-host 上线后,选 1 个 prompt template 在 Langfuse 编辑 → MimirQ 自动同步
2. KG auto-tuning:给 3 个客户 PDF → 30 min 内产出 domain-specific prompt,实体召回比通用 baseline ≥ +10pt
3. Prompt Telemetry Dashboard 显示每个 template 7 日趋势

---

## Sources

### KG 抽取
- [Microsoft GraphRAG — GitHub](https://github.com/microsoft/graphrag)
- [From Local to Global: A GraphRAG Approach to Query-Focused Summarization (arXiv 2404.16130v2, 2025-07)](https://arxiv.org/html/2404.16130v2)
- [GraphRAG Methods Doc — entity extraction + gleaning](https://microsoft.github.io/graphrag/index/methods/)
- [GraphRAG Manual Prompt Tuning Doc](https://microsoft.github.io/graphrag/prompt_tuning/manual_prompt_tuning/)
- [GraphRAG auto-tuning — Microsoft Research](https://www.microsoft.com/en-us/research/blog/graphrag-auto-tuning-provides-rapid-adaptation-to-new-domains/)
- [LightRAG Official Site](https://lightrag.github.io/)
- [LightRAG (EMNLP 2025) — HKUDS/LightRAG GitHub](https://github.com/hkuds/lightrag)
- [langgptai/GraphRAG-Prompts — community prompt repo](https://github.com/langgptai/GraphRAG-Prompts)
- [LlamaIndex GraphRAG V2 Cookbook](https://developers.llamaindex.ai/python/examples/cookbooks/graphrag_v2/)

### Claude / XML 结构化
- [Prompting best practices — Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
- [Use XML tags to structure your prompts — Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/use-xml-tags)
- [Prompt engineering techniques with Claude 3 on Amazon Bedrock](https://aws.amazon.com/blogs/machine-learning/prompt-engineering-techniques-and-best-practices-learn-by-doing-with-anthropics-claude-3-on-amazon-bedrock/)
- [Mastering Prompt Engineering for Claude — Walturn](https://www.walturn.com/insights/mastering-prompt-engineering-for-claude)

### RAG 系统提示词 + 幻觉/引用
- [Mitigating Hallucination in LLMs: A Survey on RAG, Reasoning, and Agentic Systems (arXiv 2510.24476)](https://arxiv.org/html/2510.24476v1)
- [Advanced Prompting for RAG — System Prompts That Prevent Hallucination](https://aiamastery.substack.com/p/lesson-25-advanced-prompting-for)
- [Top 5 LLM Prompts for RAG — Scout](https://www.scoutos.com/blog/top-5-llm-prompts-for-retrieval-augmented-generation-rag)
- [Best Practices for Mitigating Hallucinations — Microsoft Azure AI Foundry 2025](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/best-practices-for-mitigating-hallucinations-in-large-language-models-llms/4403129)
- [FACTUM: Mechanistic Detection of Citation Hallucination in Long-Form RAG (arXiv 2601.05866)](https://arxiv.org/pdf/2601.05866)
- [Legal RAG Hallucinations (Stanford Empirical Study 2025)](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)
- [MEGA-RAG: multi-evidence guided answer refinement](https://pmc.ncbi.nlm.nih.gov/articles/PMC12540348/)

### Prompt 管理平台
- [Langfuse — Open Source Prompt Management](https://langfuse.com/docs/prompt-management/overview)
- [Langfuse + Promptfoo integration](https://www.promptfoo.dev/docs/integrations/langfuse/)
- [The 5 best prompt versioning tools in 2025 — Braintrust](https://www.braintrust.dev/articles/best-prompt-versioning-tools-2025)
- [The 5 best prompt evaluation tools in 2025 — Braintrust](https://www.braintrust.dev/articles/best-prompt-evaluation-tools-2025)
- [A/B testing for LLM prompts — Braintrust](https://www.braintrust.dev/articles/ab-testing-llm-prompts)
- [Best AI evals tools for CI/CD in 2025 — Braintrust](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025)
- [Prompt Management Systems Compared — Nearform](https://nearform.com/digital-community/prompt-management-systems-compared/)
- [Top Prompt Evaluation Frameworks 2025 — Helicone](https://www.helicone.ai/blog/prompt-evaluation-frameworks)

### Prompt 安全
- [meta-llama/Prompt-Guard-86M — Hugging Face](https://huggingface.co/meta-llama/Prompt-Guard-86M)
- [Llama Prompt Guard 2 — Meta Llama Docs](https://www.llama.com/docs/model-cards-and-prompt-formats/prompt-guard/)
- [Llama-Prompt-Guard-2-86M — Hugging Face](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M)
- [Llama Guard 3 — Meta Llama Docs](https://www.llama.com/docs/model-cards-and-prompt-formats/llama-guard-3/)
- [Bypassing Prompt Injection and Jailbreak Detection in LLM Guardrails (arXiv 2504.11168, 2025)](https://arxiv.org/html/2504.11168v1)
- [Bypassing Meta's Llama Firewall — Trendyol Tech 2025](https://medium.com/trendyol-tech/bypassing-metas-llama-firewall-a-case-study-in-prompt-injection-vulnerabilities-fb552b93412b)
- [Introduction to prompt injection with Prompt Guard — Ploomber Blog](https://ploomber.io/blog/prompt-guard/)
- [Meta Prompt Guard — Sascha Heyer / Google Cloud](https://medium.com/google-cloud/meta-prompt-guard-9c4d6584e75c)

### Structured Output
- [OpenAI Structured Outputs Guide](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Pydantic for LLMs — Pydantic.dev](https://pydantic.dev/articles/llm-intro)
- [LangChain Structured Output Docs](https://docs.langchain.com/oss/python/langchain/structured-output)
- [The Guide to Structured Outputs and Function Calling — Agenta](https://agenta.ai/blog/the-guide-to-structured-outputs-and-function-calling-with-llms)
- [Complete Guide to Pydantic for LLM Outputs — MachineLearningMastery](https://machinelearningmastery.com/the-complete-guide-to-using-pydantic-for-validating-llm-outputs/)
- [Structured Output AI Reliability 2025 — Cognitive Today](https://www.cognitivetoday.com/2025/10/structured-output-ai-reliability/)

### CoT / Few-shot / 中文
- [Chain-of-Thought Prompting — Prompt Engineering Guide](https://www.promptingguide.ai/techniques/cot)
- [Few-Shot Prompting — Prompt Engineering Guide](https://www.promptingguide.ai/techniques/fewshot)
- [Chain-of-thought supercharges enterprise LLMs — K2view](https://www.k2view.com/blog/chain-of-thought-reasoning/)
- [LangGPT 结构化方法论 — 知乎](https://zhuanlan.zhihu.com/p/708861388)
- [提示工程指南 中文 — promptingguide.ai/zh](https://www.promptingguide.ai/zh)
- [阿里云百炼 Prompt 工程指南](https://help.aliyun.com/zh/model-studio/prompt-engineering-guide)
- [16 种 Prompt 工程方式 — AWS 中国](https://aws.amazon.com/cn/blogs/china/sixteen-ways-of-prompt-engineering/)
- [腾讯云开发者社区 — RAG 策略下的 Prompt](https://cloud.tencent.com/developer/article/2391688)
