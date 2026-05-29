# OneKE 接入 MimirQ KG 抽取调研 plan (政务客服场景)

> 创建日期: 2026-05-29
> 关联讨论: 群里专家关于"GraphRAG ≠ KG 工具"的讨论 + 推荐 KnowLM OneKE
> 语料: `/path/to/gov-service-knowledge`(常州市政务客服 27 文件)

## Context

群里专家批评 GraphRAG 不是真正的 KG 工具,我们当前 KG 抽取走 LLM(`kg_extract_graphrag_zh` prompt)+ GraphRAG 风格社区聚合,虽然已有 ontology + entity resolution + provenance + quality 4 层补强,**但抽取这一步仍是裸 LLM 一遍出**,缺少 IE 任务专项微调模型的精度护城河。

本调研评估接入 **OneKE**(ZJUNLP, WWW 2025, MIT, 基于 Chinese-Alpaca-2-13B 双语 IE 大模型)作为 MimirQ KG 抽取的第二条 backend,与现有 LLM/GLiNER/Hybrid/Heuristic 4-backend 并存,**不替换**任何现有抽取器。语料用 `/path/to/gov-service-knowledge`(常州市政务客服 27 文件:8 区事项清单 / 12345 QA / 一件事 / 6 业务部门 QA 含公积金/不动产/医保/应急局)。

### 用户决策

| 决策点 | 选定 |
|---|---|
| 部署方案 | 调研含 vLLM 本地 / HF transformers / API 三者对照 + 决策门槛 |
| 微调深度 | 全栈三阶段:P0 零样本 ICL → P1 LoRA 微调(500 条标注) → P2 IEPile-zh 增量预训 |

---

## OneKE 项目摘要(WWW 2025)

| 项 | 内容 |
|---|---|
| 论文 | KnowLM/OneKE: A Bilingual IE LLM (WWW 2025) |
| 仓库 | github.com/zjunlp/OneKE,v0.1.0 (2025-02-15) |
| 模型 | 基于 Chinese-Alpaca-2-13B,双语,13B 参数 |
| 任务 | NER + RE + EE + 三元组抽取 + 网页 IE + 书籍 KG |
| 后端 LLM | 兼容 OpenAI / DeepSeek / LLaMA3 / Qwen2.5 / ChatGLM4-9B / MiniCPM3-4B / DeepSeek-R1 |
| 部署 | HF transformers / vLLM / API / Docker |
| 微调 | 自定义 Schema 库 + Case 库(ICL); LoRA 支持需自接 PEFT |
| 训练数据 | JSON: `{instruction, schema, input, output}` |
| License | MIT,商用 OK |
| 中文支持 | ⭐⭐⭐⭐⭐(政务文档天然友好) |
| 相关 | 引用 IEPile(ZJUNLP 25M 中英 IE 训练集,ACL'24) |

---

## 关键复用(不动现有 MimirQ KG 栈)

| 资产 | 路径 | 复用方式 |
|---|---|---|
| `backend_router.py::resolve_extraction_backend()` | `app/rag/kg/extraction/backend_router.py:29` | **核心接入点**:新增 `"oneke"` backend 名,无需改路由逻辑 |
| `BackendExtractor` 接口 `extract_from_sections(sections, batch_index, max_events, max_entities)` | `app/rag/kg/extraction/gliner_extractor.py:15`(参考实现) | OneKE backend 实现同名方法 |
| `LLMProcessor` 默认 backend | `app/rag/kg/extraction/extractor.py` | 不动,作为对照基线 |
| `RelationProcessor.normalize_predicate()` | `relation_processor.py:83` | OneKE 输出走相同 normalize 链 |
| `EntityValueParser.normalize_type()` | `parser.py` | OneKE 实体类型映射到 10 类枚举 |
| `KgPredicateOntology` 表(per-tenant 谓词本体) | `app/rag/kg/models.py` | OneKE 谓词约束直接读这张表 |
| `kg_entities` / `kg_relations` / `kg_source_events` / `kg_event_entities` 表 | 同上 | OneKE 输出落库 schema 不变 |
| arq 队列异步执行 | `app/tasks/queue.py::enqueue_kg_extraction()` + `app/tasks/jobs.py:997::extract_kg_job()` | 走相同异步路径,backend 切换不影响调度 |
| `ExtractConfig.extraction_backend` 字段 | 现有 | 添加 `"oneke"` enum 值即可 |
| `KG_EXTRACTION_BACKEND` 环境变量 | `app/core/config.py` | 同上,加值不加字段 |
| `app/rag/evaluation/kg_search_diagnostics.py` | 1082 行已有 | 改造为支持双 backend 对照(P/R/F1) |
| `app/rag/llm/prompts/builtin_library.py` 中 `kg_extract_graphrag_zh` | 现有 | 作为对照基线 prompt(不动) |

---

## 三阶段落地路线图(共 6-10 周)

### 阶段 P0 — 零样本接入 + Schema/Case 库(2 周)

**目标**:OneKE 跑通 + 政务 schema + 30 条 Case → 端到端能抽出第一批三元组 + 评测基线确立

#### P0.1 部署对照实验

并行验证三种部署方案,跑相同 5 个测试文档(从 `/data/temp50` 抽样:`常州市本级12345QA.txt` / `常州市事项清单.txt` / `一件事指南.txt` / `不动产常见问答.xlsx` 转 markdown / `应急局日常问题汇总.docx` 转 markdown),记录单文档抽取延迟 / 显存占用 / 单文档成本。

| 方案 | 软件栈 | 硬件 | 单文档延迟 | 单 token 成本 | 优势 | 劣势 |
|---|---|---|---|---|---|---|
| **A. vLLM 本地** | vLLM 0.6+ + OneKE-13B FP16 / AWQ-4bit | 1×A100 80GB **or** 2×A6000 48GB **or** 4×3090 24GB | 估 1.5-3s / 1KB | 仅电费 | 高吞吐 / 全控 / 易微调对接 | 需 GPU 资产 |
| **B. HF transformers** | transformers + bitsandbytes 4-bit | 1×3090/4090 24GB | 估 5-15s / 1KB | 仅电费 | 24GB 即可 / 易调试 | 低吞吐,不能并发 |
| **C. API** | 自部 vLLM 在其他机器对外暴露 `/v1/chat/completions`(OpenAI-compatible) | 远端 GPU | 估 2-5s / 1KB + 网络 | 内部计费 | 零本地 GPU 压力 / 解耦 | 网络抖动 / 难微调 |

**决策门槛(本环节产出)**:
- 若 vLLM 单文档 ≤ 3s 且 GPU 可用 → 选 A(生产首选)
- 若仅 24GB GPU → 用 B 做 PoC,**当数据量 > 100 文档时升级 A**
- 若 GPU 在另一组服务器 → 选 C(走 OpenAI-compatible client,与 LLM provider 框架对齐)

#### P0.2 政务客服 schema 设计

抽出政务垂直专用 schema,落地到 `app/rag/kg/ontology/gov_service_ontology.py`(新文件):

**实体类型(10 类,扩展现有 10 类不动 + 政务垂直 6 类)**:
| 类型 | 示例 | 来源 |
|---|---|---|
| Department(部门) | 常州市公积金管理中心 / 江苏省人社厅 / 常州市市监局 | `来源部门:`字段 |
| ServiceItem(政务事项) | 不动产登记 / 公积金提取 / 营业执照变更 | `事项名称:`字段 |
| District(行政区域) | 天宁区 / 钟楼区 / 新北区 / 武进区 / 金坛区 / 溧阳市 / 经开区 / 常州市本级 | 8 个文件名 + 单元内 |
| Regulation(法规依据) | 《劳动合同法》/ 《特种设备安全监察条例》/ 常政办发〔2021〕17号 | 答案内文引用 |
| Material(办理材料) | 户口簿 / 身份证 / 残疾人证 / 营业执照 | `办理材料:`字段 |
| Channel(办理渠道) | 苏服办 APP / 江苏政务服务网 / 12345 政务服务热线 / 政务服务中心窗口 | 高频提及 |
| Person(人员)、Organization(机构)、Time、Money | (沿用现有 10 类) | |

**关系类型(15 类,扩 `_DEFAULT_RELATION_PREDICATES` 17 条到 32 条)**:
| 关系 | 主语 → 谓语 → 宾语 | 示例 |
|---|---|---|
| owned_by | ServiceItem → Department | 不动产登记 owned_by 常州市不动产登记交易中心 |
| applicable_in | ServiceItem → District | 残疾人证新办 applicable_in 江苏省 |
| requires_material | ServiceItem → Material | 小学入学 requires_material 户口簿 |
| handled_via | ServiceItem → Channel | 营业执照办理 handled_via 苏服办 APP |
| governed_by | ServiceItem → Regulation | 劳务派遣经营 governed_by 《劳务派遣暂行规定》|
| similar_to | ServiceItem → ServiceItem | 残疾人证补办 similar_to 残疾人证换领 |
| has_contact_phone | Department → Time/Phone(text) | 市监局 has_contact_phone 0519-12345 |
| has_location | Department → Location | 公积金中心 has_location 锦绣路2号 |
| valid_from / valid_to | ServiceItem → Time | 医保新政 valid_from 2025-11-20 |
| ...(沿用现有 17 类) | | |

#### P0.3 Case 库(从 27 个文件抽 30 条政务示例)

格式按 OneKE 要求的 JSON:
```json
{
  "instruction": "提取实体和关系",
  "schema": {"entities": [...], "relations": [...]},
  "input": "问题:[小学入学需要哪些材料?]\n答案:凭户口簿(儿童和一名监护人须在同一户口簿)、合法固定住所证件,到所在学区小学办理报名手续。\n来源部门:常州市教育局",
  "output": {
    "entities": [
      {"name": "小学入学", "type": "ServiceItem"},
      {"name": "户口簿", "type": "Material"},
      {"name": "学区小学", "type": "Channel"},
      {"name": "常州市教育局", "type": "Department"}
    ],
    "relations": [
      {"subject": "小学入学", "predicate": "requires_material", "object": "户口簿"},
      {"subject": "小学入学", "predicate": "handled_via", "object": "学区小学"},
      {"subject": "小学入学", "predicate": "owned_by", "object": "常州市教育局"}
    ]
  }
}
```

存到 `app/rag/kg/extraction/oneke/cases/gov_service/*.jsonl`,**30 条覆盖 6 类场景**:5 条事项清单 / 5 条 12345QA / 5 条一件事 / 5 条业务部门 / 5 条法规引用 / 5 条 refusal(无可抽内容)

#### P0.4 OneKE backend 集成代码

新建 4 个文件,**不动现有 4-backend 任何代码**:

1. **`app/rag/kg/extraction/oneke_extractor.py`** (~250 行)
   ```python
   class OneKEExtractor:
       def __init__(self, mode: Literal["vllm", "hf", "api"], schema_path, cases_path): ...
       async def extract_from_sections(self, sections, batch_index, max_events, max_entities):
           # 1. 拼 prompt: instruction + schema + case 库前 3-5 条 + input
           # 2. 调 LLM (vLLM/HF/API)
           # 3. parse JSON output → normalize 谓词/实体类型
           # 4. 返回与 LLMProcessor 同 shape 的 EventEntityRelation 元组
   ```

2. **`app/rag/kg/extraction/oneke/schemas/gov_service.json`** — 政务 schema 定义
3. **`app/rag/kg/extraction/oneke/cases/gov_service/*.jsonl`** — 30 条 Case
4. **`app/rag/kg/extraction/backend_router.py`** — 一行追加:`"oneke": OneKEExtractor`

#### P0.5 评测基线

改造 `app/rag/evaluation/kg_search_diagnostics.py` 加双 backend 对比:
- 同样 5 文档,LLMProcessor vs OneKEExtractor,计算:
  - 实体 P/R/F1(用 P0.3 中 6 条手标 ground truth 集)
  - 关系 P/R/F1
  - 实体类型分布(检查 OneKE 是否更精细)
  - 谓词分布(检查 OneKE 是否在 ontology 内)
  - 抽取耗时
- 报告产出:`reports/oneke_baseline_2026-Q2.html`

**P0 工作量**: ~10 工作日,2 周可见基线数据。

---

### 阶段 P1 — LoRA 微调(2-4 周)

**目标**:从 P0 OneKE 0-shot 基线 + 评测,**找到 F1 短板** → 标注 500 条 → LoRA 微调 → F1 提升 ≥+5 pt

#### P1.1 数据标注(500 条)

**预算分配**(基于 P0 评测短板):
- 200 条:F1 最低的 1-2 个实体类型(可能是 ServiceItem 或 Channel 的边界)
- 150 条:关系类型(尤其 requires_material / handled_via 这类高价值多跳)
- 100 条:negative/refusal(没有可抽取实体的段落)
- 50 条:跨实体复杂句(一句含 3+ 实体 + 2+ 关系)

**标注流程**:
1. 从 `/data/temp50` 抽 800 条候选(每文件 30 条)
2. **LLM 辅助预标注**:用 `kg_extract_graphrag_zh` + GPT-4 / Claude 出初版
3. **人工 review + 修正**:用 `app/rag/kg/extraction/oneke/annot_review/` 简易 UI(可前端复用 `/data-annotator` 页面)
4. 标注 spec 文档:`docs/oneke_annotation_guide.md`,严格定义边界 case(如"苏服办 APP"算 Channel 还是 Product)

**人力估算**:1 人标注师 + 1 人 review,**~2 周完成 500 条**

#### P1.2 LoRA 训练栈

栈选择:
- **PEFT 0.10+** (HuggingFace) + **transformers 4.40+** + **accelerate 0.30+**
- LoRA target_modules:`q_proj, k_proj, v_proj, o_proj`,rank=16,alpha=32
- 量化:QLoRA 4-bit(显存 24GB 可训 13B)
- 训练数据格式:转 OneKE JSON → ChatML / Alpaca 模板
- batch_size=4 × gradient_accumulation=8 ≈ effective 32
- learning_rate=2e-4,epochs=3-5,warmup 50 step
- 估算时长:**500 条 × 5 epochs ≈ 3-5 小时 on 1×A100**

新建文件:
- `scripts/oneke_finetune.py` (~200 行,基于 `transformers.Trainer` + `peft.LoraConfig`)
- `data/oneke_finetune/gov_service_train.jsonl` / `gov_service_val.jsonl` (80/20 split)

#### P1.3 LoRA 适配器加载

OneKEExtractor 加 `lora_adapter_path` 参数:
```python
def __init__(self, ..., lora_adapter_path: str | None = None):
    base_model = load_oneke_base(...)
    if lora_adapter_path:
        self.model = PeftModel.from_pretrained(base_model, lora_adapter_path)
```

适配器存到 `models/oneke/lora/gov_service_v1/`,在 `KG_EXTRACTION_BACKEND_ONEKE_LORA` 环境变量指定路径。

#### P1.4 P1 评测

- **同 P0 评测集 + 100 条 holdout**(P1 标注里留)
- 对比四组:LLMProcessor / OneKE 0-shot / OneKE +ICL Case / OneKE +LoRA
- **决策门槛**:
  - OneKE LoRA F1 > OneKE 0-shot +5pt → 投产 P1
  - OneKE LoRA F1 > LLMProcessor +3pt 且延迟 ≤ 2× → 投产为政务场景默认 backend
  - 否则继续 P2 或维持 LLMProcessor 默认

**P1 工作量**: ~3-4 周(2 周标注 + 1 周训练调参 + 0.5 周评测)

---

### 阶段 P2 — IEPile-zh 增量预训练(1-2 月,按需做)

**目标**:用 IEPile-zh 公开数据(ZJUNLP 提供,约 1.3M 条中文 IE 训练样本)继续训练 OneKE-13B,**通用中文 IE 能力提升**,然后在 P1 政务 LoRA 上接续训练。

#### P2.1 IEPile-zh 数据

- 数据集:`huggingface.co/datasets/zjunlp/iepile`(2024-05 公开),含 NER / RE / EE 任务
- 中文部分约 100 万条
- 转换为 OneKE 训练格式

#### P2.2 训练方案

| 阶段 | 方式 | 时长 | 硬件 |
|---|---|---|---|
| 2a. 通用 IE 增量预训 | LoRA on IEPile-zh,r=32,batch=8 × ga=16,1 epoch | ~3-7 天 on 1×A100 | A100 80GB / 2×A6000 |
| 2b. 政务领域续训 | 在 2a 适配器上继续训 P1 的 500 条政务数据 | ~3-5 小时 | 同上 |

#### P2.3 决策门槛(P2 是否做)

仅当满足以下全部:
- P1 LoRA F1 提升 < 5pt(说明 500 条不够)
- 客户场景需要更通用的中文 IE 能力(不仅政务)
- 有 ≥ 1 周连续 GPU 资源

否则 **P2 跳过**,继续累积政务标注到 2000+ 条直接做 P1.5 大规模 LoRA。

**P2 工作量**: 4-6 周(数据准备 1 周 + 训练 1-2 周 + 评测 + 政务续训 + 投产)

---

## 修改/新建文件清单

### 新建(7-9 个)

| 文件 | 行数估 | 用途 |
|---|---|---|
| `app/rag/kg/extraction/oneke_extractor.py` | ~250 | OneKE backend 实现(vLLM/HF/API 三路) |
| `app/rag/kg/extraction/oneke/schemas/gov_service.json` | ~150 | 政务 schema 16 类实体 + 32 类关系 |
| `app/rag/kg/extraction/oneke/cases/gov_service/*.jsonl` | ~30 条 | Case 库(P0) |
| `app/rag/kg/ontology/gov_service_ontology.py` | ~150 | 实体类型扩展常量 + 关系预填 |
| `scripts/oneke_finetune.py` | ~200 | LoRA 训练脚本(PEFT + Trainer) |
| `scripts/oneke_eval.py` | ~150 | 双 backend P/R/F1 对比 runner |
| `data/oneke_finetune/gov_service_train.jsonl` / `val.jsonl` | ~500 条 | P1 标注数据 |
| `docs/oneke_annotation_guide.md` | ~300 行 | 标注规范 + 边界 case |
| `models/oneke/lora/gov_service_v1/`(目录) | 适配器权重 | P1 训练产物(LFS) |

### 修改(3 个)

| 文件 | 改动 |
|---|---|
| `app/rag/kg/extraction/backend_router.py:29` | 路由表加 `"oneke": OneKEExtractor` 一行 |
| `app/core/config.py` | 加 `KG_EXTRACTION_BACKEND_ONEKE_*` 环境变量(mode/endpoint/lora_path/schema_path) |
| `app/rag/evaluation/kg_search_diagnostics.py` | 加 `compare_backends(["llm", "oneke", "oneke+lora"])` 模式 + P/R/F1 |

### 不动(关键架构)

- `_DEFAULT_RELATION_PREDICATES`(只追加,不改原 17 条)
- `LLMProcessor` / `GLiNERExtractor` / `HybridExtractor` / `HeuristicExtractor`(都不动)
- `RelationProcessor.normalize_predicate()`(OneKE 输出走相同 normalize)
- `kg_entities` / `kg_relations` 表 schema
- arq 异步队列调度
- 任何前端代码(本期纯后端)

---

## 政务数据规模与可行性

| 维度 | 数据 |
|---|---|
| 总文件数 | 27(17 txt + 9 xlsx + 1 docx) |
| 总 QA 单元数估算 | ~3000-5000(按 `==##########==` 分隔统计) |
| 平均 QA 单元长度 | 150-500 字 |
| 抽取目标三元组(P0 基线估算) | 30000-80000 |
| GPU 资源需求 | P0:1×24GB GPU 即可;P1:1×40GB+ 训练;P2:1×80GB 通用增量预训 |
| 标注成本 | P1 500 条人工 = 1 标注师 × 2 周 |
| 评测集 | P0:5 文档手标 ground truth(初版);P1:100 条 holdout(同标注流程) |

---

## 风险

| 风险 | 缓解 |
|---|---|
| OneKE 13B 在小 GPU 跑不动 | P0 三对照实验先验证;退路:走 API 模式或缩为 7B 模型 |
| LoRA 微调 500 条不够 | P1 评测后看,若 F1 < 5pt 提升,扩到 2000 条或走 P2 IEPile |
| 政务 schema 设计不准 | 30 条 Case 走完 PoC 后,**和 1-2 个政务客户共建**再固化 |
| OneKE 中文输出格式不稳(JSON 偶发坏) | 用 Pydantic + structured output 校验 + 失败 fallback 到 LLMProcessor |
| 与现有 LLMProcessor 冲突 | backend_router 解耦,**只在 dataset 级或租户级开 OneKE**,不全局替换 |
| 训练数据质量参差 | 标注 spec 严格 + 双人 review + 模糊 case 进 ambiguous 队列 |
| 微调后泛化下降(过拟合政务) | P1 训练加 dropout=0.1 + 验证集监控 + IEPile 通用数据混入 ≥ 30% |
| 决策门槛误判(P2 投入回报低) | 每阶段强制有量化决策门槛(F1 / 延迟 / 成本 3 维) |

---

## 与既有 plan 协同

| 已有 plan | 关系 |
|---|---|
| `plans/rag-kg-deep-research-2026-q2.md` | 本 plan 是其 P0-IE-Backend-Diversify 落地 |
| `plans/rag-kg-diagnostics-deep-dive-2026-q2.md` | 评测基建复用,加 OneKE 列 |
| `plans/rag-evaluation-deep-dive-2026-q2.md` | 用其 P/R/F1 + Citation 框架 |
| `plans/industry-rules-productization-2026-q2.md` | 政务 schema 与行业规则库 schema 互补,可双向引用 |
| `plans/cn-benchmark-baseline-2026-q2.md` | OneKE 在 CRUD-RAG / 中文金融自建集上的 KG 召回也可对比 |

---

## Verification

P0 完成后,按顺序跑 7 步:

1. **OneKE 模型加载冒烟**
   - `python -c "from app.rag.kg.extraction.oneke_extractor import OneKEExtractor; e = OneKEExtractor(mode='hf', ...); print(e.health_check())"`
   - 输出 `{ok: True, mode: 'hf', model: 'OneKE-13B'}`

2. **backend_router 注册验证**
   - `python -c "from app.rag.kg.extraction.backend_router import resolve_extraction_backend; print(resolve_extraction_backend('oneke'))"` 应返回 `OneKEExtractor` 类

3. **政务 schema 加载**
   - `python -c "from app.rag.kg.ontology.gov_service_ontology import GOV_SERVICE_ENTITY_TYPES, GOV_SERVICE_RELATIONS; print(len(GOV_SERVICE_ENTITY_TYPES), len(GOV_SERVICE_RELATIONS))"` 应输出 `16 32`

4. **端到端 5 文档抽取**
   - 上传 5 个测试文件到 MimirQ dataset,设置 `extraction_backend=oneke`
   - 触发 ingestion,等 arq 异步完成
   - 查询 `kg_entities` / `kg_relations` 表,应有 ≥ 100 entity + ≥ 50 relation

5. **三 backend 对照评测**
   - `python scripts/oneke_eval.py --backends llm,oneke,oneke+lora --dataset gov_service_test --report-html reports/oneke_baseline.html`
   - 输出三组 P/R/F1 + 延迟

6. **P1 LoRA 训练冒烟**
   - `python scripts/oneke_finetune.py --train data/oneke_finetune/gov_service_train.jsonl --val ...val.jsonl --output models/oneke/lora/gov_service_v1/ --epochs 1`
   - 1 epoch 应在 1 小时内完成

7. **P1 评测达标**
   - 用 P1 LoRA 适配器 + 100 条 holdout
   - F1 vs OneKE 0-shot 提升 ≥ +5pt,vs LLMProcessor 提升 ≥ +3pt → 投产
   - 否则进入 P2 评估或扩标注

---

## 工作量与时间线

| 阶段 | 时长 | 关键产出 |
|---|---|---|
| P0 部署 + Schema + Case + Baseline | 2 周 | OneKE 接入 + 政务 schema + 30 Case + 评测基线 |
| P1 标注 + LoRA + 评测 | 3-4 周 | 500 条标注 + LoRA 适配器 + F1 提升 ≥ 5pt |
| P2 IEPile 增量预训(条件触发) | 4-6 周 | 通用 IE 增强 + 政务续训 + 二次评测 |
| **总计** | **6-10 周**(若 P2 跳过则 5-6 周) | OneKE 作为政务 dataset 默认 backend |

## 一句话总结

OneKE 接入是 **添加第二条 backend 而不是替换**,通过 `backend_router.py` 一行注册即可上线,P0 两周出基线;P1 LoRA 政务微调是真正的 KG 质量护城河;P2 IEPile 增量是锦上添花,**只有 P1 不达标时才需要做**。
