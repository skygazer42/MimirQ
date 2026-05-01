# AI 自动打标服务调研 — 接入可行性与落地路径

## Context

**触发场景**:用户在 `web/app/data-governance` 页面数据清洗完成后会对内容做"自动打标"。当前实现只覆盖 keyword(jieba/HanLP/simple)+ regex 实体 + PII 三类,**未接入 LLM 路径**,标签维度单一(entity/keyword/sensitive/custom 共 4 类)。即便用户关闭 KG,治理打标也应能给出**主题、分类、领域、行业、敏感度、文档类型**等更丰富的语义标签,这是 RAG 入库前提升检索召回与权限分流的关键元数据。

**问题**:现有打标只做"字面匹配",缺三种核心能力:① LLM 生成主题/摘要/分类(语义级);② 主题模型聚类(发现性);③ 商业云 SaaS NLP API(零运维兜底)。本次调研覆盖**所有候选方案**,评估接入 MimirQ 的工程可行性,并给出 P0 方案与落地路径。

---

## 1. 现状盘点(代码已确认)

### 1.1 三种已实现路径

| 路径 | 实现文件 | 算法 | 成熟度 |
|---|---|---|---|
| **关键词** | `app/rag/preprocessing/keyword.py` | jieba TF-IDF / TextRank / HanLP / Simple regex | ✅ 成熟,5 种 provider |
| **正则实体** | `app/api/v1/pipeline.py:280-303` `_collect_entity_annotations` | `_ZH_ENTITY_RE` / `_EN_ENTITY_RE` | ⚠️ 粗糙,无类型细分 |
| **PII/敏感** | `app/api/v1/pipeline.py:306-340` + `find_pii_matches` / `find_secret_matches` | 规则正则 | ✅ 已用于治理 |

### 1.2 半实现(仅 KG 用,治理打标未复用)

- `app/rag/kg/extraction/gliner_extractor.py` — GLiNER(开源 NER 模型,默认 `urchade/gliner_multi_pii-v1`,可换中文模型)
- `app/rag/kg/extraction/hybrid_extractor.py` — GLiNER + LLM 混合抽取
- `app/rag/kg/extraction/llm_processor.py` — LLM 实体/关系抽取
- `app/rag/kg/search/searcher.py:84-98` — `llm_summary` 已有缓存

### 1.3 完全缺失

- ❌ LLM 主题/分类/领域标签(`pipeline.py` auto-annotations 完全无 LLM 调用)
- ❌ 文档级摘要(chunk 级 contextual_enrichment 明确"No LLM calls",见 `app/rag/chunking/contextual_enrichment.py:144`)
- ❌ 主题模型(BERTopic/LDA)— 跨文档主题发现
- ❌ 多模态打标(图片描述/表格类型/图表识别)
- ❌ 文档分类器(行业/政策/合同/研报/工单等垂类)
- ❌ 商业云 NLP 兜底通道

### 1.4 前端入口

- `web/components/data-governance/data-annotator.tsx` — `pipelineApi.autoAnnotations` 触发,参数 `keyword_provider` 已支持 simple/jieba/hanlp;**新增 LLM 后只需扩一个 `provider: 'llm'` 选项**
- 4 类标签 UI:entity / keyword / sensitive / custom(可扩为更多)
- `governance_extract_keywords` 配置开关贯穿 `pipeline_config.py` + `processor.py`,新增标签开关沿用此模式

---

## 2. 业界 AI 自动打标服务全景(2024-2026)

### A. 商业云 SaaS API(零运维,按量计费)

| 服务 | 能力 | 中文支持 | 计费(估) | 接入难度 |
|---|---|---|---|---|
| **阿里云 NLP 自学习** | 实体抽取 / 文本分类 / 关键短语 / 情感 / 行业模型 | ⭐⭐⭐⭐⭐ | ¥0.001-0.01/次 | 低,SDK 完善 |
| **腾讯云 NLP** | 关键词 / 摘要 / 分类 / 实体识别 / 意图 | ⭐⭐⭐⭐⭐ | ¥0.005/次起 | 低 |
| **百度智能云 UNIT/NLP** | 词法 / 主题 / 分类 / 知识图谱 / Embedding | ⭐⭐⭐⭐⭐ | ¥0.005/次起 | 低 |
| **华为云 NLP** | 命名实体 / 文本分类 / 关键词 / 摘要 | ⭐⭐⭐⭐ | ¥0.003/次 | 低 |
| **Azure Cognitive Services - Text Analytics** | KeyPhrase / NER / Sentiment / Summarization / Health / PII | ⭐⭐⭐⭐ | $1/1k 次 | 中 |
| **AWS Comprehend / Comprehend Medical** | NER / Topic / KeyPhrase / Classify (Custom) | ⭐⭐⭐ | $0.0001/100 字符 | 中 |
| **Google Cloud Natural Language API** | Entity / Sentiment / Classification / Syntax | ⭐⭐⭐ | $1/1k 单元 | 中 |

**评估**:阿里云/百度对中文文档(政策、合同、技术规范)效果最佳,且支持**行业模型微调**,适合做 P0 兜底通道。Azure Health/PII 在医疗合规场景独此一家。

### B. 开源专业模型(本地部署,可控可微调)

| 方案 | 能力 | 关键论文/项目 | 资源 |
|---|---|---|---|
| **GLiNER**(已有依赖) | Zero-shot NER,标签可在 prompt 里定义 | NAACL 2024 | 200MB,CPU 可跑 |
| **GLiNER-Multi-PII** | 多语言 PII | Hugging Face | 已在 `gliner_extractor.py` 集成 |
| **BERTopic** | 主题模型(BERT embedding + UMAP + HDBSCAN) | Grootendorst 2022 | 需 GPU 提速 |
| **KeyBERT** | BERT 关键词抽取(对比 jieba 更语义化) | Grootendorst 2020 | CPU 可跑 |
| **spaCy + zh-core-web-trf** | 工业级中文 NER + 词性 + 依存 | spaCy 3.7+ | CPU 可跑 |
| **HanLP 2.x**(已有依赖) | 词法 / NER / 依存 / 摘要 | HIT-SCIR | 已集成 |
| **PaddleNLP UIE** | 通用信息抽取(prompt-driven 实体/关系/事件) | 百度 ACL 2022 | 需 PaddlePaddle |
| **LayoutLMv3 / LayoutXLM** | 表格/版式打标(多模态) | Microsoft 2022 | GPU 推荐 |
| **ColPali / Qwen-VL** | 图像文档语义打标 | ICLR 2025 / 通义 | GPU 必须 |
| **Whisper + Speaker Diarization** | 音频打标(说话人/语种/时间) | OpenAI | GPU 推荐 |

**评估**:GLiNER 已集成,**最低成本扩展是把 KG 里的 GLiNER 暴露给治理打标接口**;BERTopic 适合做"跨文档主题发现"独立功能;UIE 在合同/工单等结构化抽取场景效果优于通用 LLM。

### C. LLM-based 方案(prompt 驱动,接现有 LLM)

| 方案 | 思路 | 优势 | 劣势 |
|---|---|---|---|
| **直接用项目内 LLM** | 复用 `app/rag/kg/extraction/llm_processor.py` 的 LLM 客户端 | 零新依赖,效果最好 | 成本最高(每文档 1k-5k tokens) |
| **Claude Haiku / GPT-4o-mini / Qwen-Plus** | 小模型批量打标 | 成本可控($0.001-0.01/文档) | 需要 prompt 设计 |
| **Anthropic Contextual Retrieval** | 给每个 chunk 加文档上下文摘要 | 召回提升 35%(Anthropic 实测) | token 成本翻倍,需 prompt 缓存 |
| **结构化输出(Outlines / Pydantic SO)** | 强类型 JSON 标签 | 可机读,可入库 | 模型需支持 JSON mode |
| **LLM Topic Modeling**(2024 新趋势) | LLM 替代 LDA 做主题发现 | 主题可解释 | 大数据量贵 |
| **Mixtral-8x7B / Qwen2.5-32B 本地** | 私有化 LLM 打标 | 数据不出域 | GPU 成本高 |

**评估**:**Claude Haiku 4.5 + Pydantic SO** 是性价比之王,$0.0008/1k input tokens,一篇 10k 字文档约 ¥0.005,生成 8-12 维标签;且与 IBM Champion Blueprint(已记入 memory)的 Prompt-as-Code 思路对齐。

### D. 集成产品(端到端打标平台)

| 产品 | 定位 | 中文 | 是否可自部 |
|---|---|---|---|
| **Label Studio** | 标注平台,可接 ML backend 自动预标 | ⭐⭐⭐⭐ | ✅ 开源 |
| **Doccano** | 文本标注 + 主动学习 | ⭐⭐⭐⭐ | ✅ 开源 |
| **Prodigy**(spaCy 团队) | 主动学习标注 | ⭐⭐⭐ | 商业,$390/seat |
| **LangChain TaggingChain** | LLM 打标链 | ⭐⭐⭐ | ✅ 库 |
| **Llama Cloud Parse + Extract** | 商业打标 API | ⭐⭐⭐ | 商业 |
| **Unstructured.io** | 文档分块 + 元数据 | ⭐⭐⭐ | 开源 + 商业 |

**评估**:Label Studio 适合做"AI 自动预打标 + 人工校正"闭环,与 MimirQ 的人工标注 UI(`data-annotator.tsx` 已有手动选区)结合效果最佳。

---

## 3. 评估矩阵:接入 MimirQ 的优先级

按"价值 / 成本 / 风险"打分(1-5):

| 方案 | 价值 | 工程成本 | 运行成本 | 风险 | 优先级 |
|---|---|---|---|---|---|
| **LLM 主题/分类标签**(项目内 LLM) | 5 | 2 | 3 | 1 | **P0** |
| **GLiNER 暴露给治理打标** | 4 | 1 | 1 | 1 | **P0** |
| **KeyBERT 替换 simple keyword** | 3 | 1 | 2 | 1 | P1 |
| **商业云 NLP 兜底**(阿里云为主) | 4 | 2 | 2 | 2 | P1 |
| **BERTopic 跨文档主题发现** | 4 | 3 | 3 | 2 | P2 |
| **PaddleNLP UIE 结构化抽取** | 3 | 3 | 2 | 2 | P2 |
| **多模态打标(ColPali/Qwen-VL)** | 4 | 5 | 5 | 3 | P3 |
| **Label Studio 主动学习闭环** | 3 | 4 | 2 | 2 | P3 |

---

## 4. 推荐方案:三层打标架构

```
┌──────────────────────────────────────────────────────────────────┐
│  治理打标统一入口  POST /api/v1/auto-annotations                 │
│  body: { text, providers: ["llm","gliner","keyword","pii"], ... }│
└────────────────┬──────────────────────────────────────────────────┘
                 │
        ┌────────┴────────┬────────────────┬───────────────────┐
        ▼                 ▼                ▼                   ▼
   字面层(已有)    语义层(P0 新增)  外部兜底(P1)   主题层(P2)
   - keyword       - LLM-tagger       - 阿里云 NLP     - BERTopic
   - regex entity  - GLiNER (复用 KG) - 百度 NLP        (跨文档异步)
   - PII / secret                     - Azure(海外)
                   3-10s,¥0.005/篇   <300ms,¥0.005/篇
```

**核心设计**:
1. `provider` 字段从单值升级为数组,允许并行调多种打标器
2. 标签类型从 4 类扩展为:`entity / keyword / sensitive / topic / category / domain / industry / doc_type / sentiment / quality`
3. **失败降级链**:LLM → 商业云 → GLiNER → keyword(始终保底)
4. 结果走 `_dedupe_auto_annotations` 统一去重(已实现)
5. 缓存策略:文档 SHA + provider 集 → Redis,TTL 30 天

---

## 5. P0 落地任务(2 周交付)

### 任务 5.1:新增 `LLMAnnotator` 打标器(~400 行)

**新建文件** `app/rag/preprocessing/llm_tagger.py`:
- 复用 `app/rag/kg/extraction/llm_processor.py` 的 LLM 客户端(已有重试/超时/JSON 修复)
- Pydantic Schema:`AutoLLMAnnotationResponse { topics, categories, domain, industry, doc_type, summary, keywords_semantic }`
- Prompt 走 IBM Champion Blueprint 思路:`app/rag/llm/prompts/tagger_prompts.py` 类组织(SystemPrompts / SchemaDefinitions / OneShots)
- 结果转 `AutoAnnotationItem`(带 `source="llm"`, `confidence` 来自 LLM logprob 或固定 0.85)
- 长文档分段策略:>3000 字截前 2000 + 后 1000(头尾摘要法,与 IBM 蓝图一致)

### 任务 5.2:`pipeline.py` 新增 LLM 路径分支

**修改** `app/api/v1/pipeline.py`:
- `AutoAnnotationRequest` 新增字段:`enable_llm_topics: bool = False`、`llm_model: str | None`
- `auto_annotations` 在 `enable_keywords/entities/sensitive` 之后追加 LLM 分支
- 失败时不抛错,转入降级(写日志 + 返回部分结果)
- 新增计费埋点:`metrics.auto_annotation_llm_tokens_total`(Prometheus)

### 任务 5.3:暴露 GLiNER 给治理打标(零成本复用)

**修改**:
- `_collect_entity_annotations` 增加 `provider` 参数,`gliner` 时调 `GLiNERExtractor.extract_entities`
- 标签类型走 `entity_types` 参数透传(默认中文实体集:人名/地名/机构/时间/产品/法规/金额)
- GLiNER 不可用时回退到正则(已有逻辑)

### 任务 5.4:前端 UI 扩展(~150 行)

**修改** `web/components/data-governance/data-annotator.tsx`:
- `ANNOTATION_TYPE_CONFIGS` 增加 `topic` / `category` / `domain` 三类
- "AI 自动打标"按钮旁加 provider 多选(checkbox 组:LLM/GLiNER/jieba/regex)
- 调用参数变 `providers: string[]`,默认 `['keyword','sensitive']`(向后兼容)
- 标签卡片新增"模型来源"小角标(LLM/规则)便于审核

### 任务 5.5:配置 + 文档

**修改**:
- `app/core/config.py` 新增 `AUTO_TAGGER_LLM_MODEL` / `AUTO_TAGGER_LLM_MAX_TOKENS` / `AUTO_TAGGER_TIMEOUT_S`
- `app/services/governance_profiles.py` 新增 `governance_llm_topics: bool` 默认 false(按 dataset 维度可开关)
- `docs/guides/data_governance.md` 增章节《AI 语义打标》

### 任务 5.6:测试

- `tests/test_pipeline_auto_annotations.py` 新增 LLM 路径用例(mock LLMProcessor)
- `tests/test_llm_tagger.py` 新建:Schema 校验 / 长文档截断 / 降级链
- E2E:跑 10 篇真实文档(政策/合同/技术规范/研报/新闻),人工 spot-check 标签准确率

---

## 6. P1 任务(1 个月)

### 6.1 商业云 NLP 兜底(¥0.005/篇)
- 新建 `app/rag/preprocessing/cloud_taggers/aliyun_nlp.py` + `tencent_nlp.py`
- ConnectorBase 风格(`app/connectors/base.py`)封装
- `provider="aliyun"` 启用,需配 `ALIYUN_NLP_AK/SK`
- 适用场景:LLM 限流时的兜底通道、特定行业模型(法律/医疗)

### 6.2 KeyBERT 替换 simple
- 依赖 `keybert` + `sentence-transformers`(已有 BGE-M3 可复用)
- 与 jieba 并行召回,RRF 融合(对齐项目内 reranker 思路)

### 6.3 文档级摘要标签
- chunk 聚合后做文档级 LLM 摘要(150 字)
- 入库 `documents.metadata.summary`
- 与 contextual_enrichment 解耦(后者是 chunk 前缀)

---

## 7. P2/P3(季度计划)

- **P2**:BERTopic 跨文档主题发现,定期任务跑库内文档,产出主题词云(给前端 `dataset_profile_service.py` 新视图)
- **P2**:PaddleNLP UIE 在"工单/合同/规章"垂类微调
- **P3**:多模态打标(图片走 Qwen-VL,表格走 LayoutLMv3)
- **P3**:Label Studio 接 ML backend,实现"AI 预标 → 人工修正 → 反哺微调"闭环

---

## 8. 关键文件清单

**修改**:
- `app/api/v1/pipeline.py`(167-340 区间打标逻辑;2211 路由)
- `app/api/schemas/pipeline.py`(`AutoAnnotationRequest/Response/Item`)
- `app/services/governance_profiles.py`(新增 governance_llm_topics 选项)
- `app/services/pipeline_config.py`(配置贯穿)
- `app/core/config.py`(LLM tagger 配置)
- `web/components/data-governance/data-annotator.tsx`(provider 多选 + 类型扩展)
- `web/lib/api-client.ts` 或 `web/lib/api/pipeline.ts`(autoAnnotations 类型)
- `web/i18n/messages/zh-CN.ts`(新标签类型文案)

**新建**:
- `app/rag/preprocessing/llm_tagger.py`
- `app/rag/llm/prompts/tagger_prompts.py`
- `app/rag/preprocessing/cloud_taggers/__init__.py`(P1)
- `app/rag/preprocessing/cloud_taggers/aliyun_nlp.py`(P1)
- `tests/test_llm_tagger.py`

**复用**(零修改):
- `app/rag/kg/extraction/gliner_extractor.py`
- `app/rag/kg/extraction/llm_processor.py`
- `app/rag/preprocessing/keyword.py`

---

## 9. 验证方法

1. **单元测试**:`pytest tests/test_llm_tagger.py tests/test_pipeline_auto_annotations.py -v`
2. **API 烟测**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auto-annotations \
     -d '{"text":"...","providers":["llm","gliner"],"enable_llm_topics":true}'
   ```
3. **前端联调**:`pnpm dev`,访问 `http://localhost:3000/data-governance`,上传一份测试文档点击"AI 自动打标",确认 ① 9-12 类标签返回 ② 加载提示正常 ③ 失败降级生效
4. **回归基线**:用 `evaluation/poc_runner/`(已规划)的 50 问评测集,对比"打标前/后"的 Top-5 召回 — 期望提升 5-10 个百分点(对齐 Anthropic Contextual 数据)
5. **成本核对**:跑 100 篇真实文档,统计 LLM tokens、阿里云调用量,核对 ≤¥0.01/文档预算
6. **完整验证**:`pnpm verify` + `pytest tests/` 全绿

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| LLM 打标 token 成本超预算 | 默认关闭(governance_llm_topics=false),用户按需开启;批量打标走 Claude Haiku 4.5 / Qwen-Turbo |
| LLM 输出不稳定(漏字段/类型错) | Pydantic SO 强类型 + 失败二次重试 + 最终降级到规则 |
| 打标延迟拉长入库流程 | 异步队列(已有 Celery/RQ?需确认);治理页面打标本就是用户点击触发非同步流水线 |
| 商业云 NLP 数据出境合规 | 默认仅启用国内云(阿里/腾讯/百度);Azure/AWS 走 enterprise 隔离区域 |
| 标签噪声污染检索 | 标签写入独立 metadata 字段,检索时可配置权重;前端可手动删除错误标签(已有 UI) |
| GLiNER 中文模型未下载 | 启动检查 + 健康检查接口;不可用时静默降级到正则 |

---

## 11. 与已有调研的关系

- 与 `plans/rag-poc-to-mvp-delivery-2026-q2.md` 的"LLM 元数据三字段(summary/keywords/questions)"同源,本计划是其**前置工程化**(治理打标层)
- 与 `plans/rag-ibm-champion-blueprint-2026-q2.md` 的 Prompt-as-Code、SO Reparser 思路一致,新建 prompts 类组织复用其规范
- 与 `plans/rag-context-expansion-rerank-2026-q2.md` 的 Contextual rerank 互补:本计划做"入库前打标",rerank 做"检索后扩展"
- 与 `plans/rag-safety-compliance-deep-dive-2026-q2.md` 的 Output Guard 协同:LLM tagger 输出经 Pydantic 校验,等价于一道轻量 guard

---

## 12. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- 后端闭环:`/api/v1/pipeline/auto-annotations` 支持 cpu、llm、gliner、keyword、regex、pii、secret providers,并返回 annotations、document_tags、summary、providers_used、warnings。
- 本地轻量打标:`cpu_tagger` 负责主题、分类、文档类型、敏感度、动作项和风险线索,作为无模型默认路径。
- LLM 语义打标:`llm_tagger` + `tagger_prompts` 已接入现有 LLM factory,用于摘要、主题、分类和重点短句。
- 前端闭环:`data-annotator` 提供本地轻量、AI 语义、敏感合规、混合增强四种打标方式,用户点击后直接调用后端 provider 组合。

暂缓:
- 暂缓商业云 NLP 兜底,避免数据出境、凭证配置和额外计费面。
- 暂缓 KeyBERT / BERTopic / PaddleNLP UIE,当前已有 CPU + LLM + GLiNER 路径足够支撑治理页面闭环。
- 暂缓批量异步文档级摘要写回,先保留为用户显式触发的治理打标建议,避免污染入库主链路。
- 暂缓 Label Studio / 主动学习闭环,这是标注平台化范围,不影响当前产品可用性。

Directive: 后续扩展自动打标必须从真实标注误差或客户行业标签需求出发建 ticket,不要再按本文档逐项推进。
