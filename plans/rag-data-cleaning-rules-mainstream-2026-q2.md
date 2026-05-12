# RAG 文本数据清洗规则主流方案调研(WebSearch 实证)— 2026-Q2

> 上一版调研误把"行业术语词典 (industry_rules)"当成了"清洗规则",已删除。本次专门调研 **文本数据清洗规则**:boilerplate / 去重 / PII / 规范化 / 噪声移除 / OCR 纠错 / 行业模板等。

---

## 1. Context

### 1.1 起因

用户纠正:`industry_rules` 是术语词典,**这次要看的是"文本清洗规则"**——把脏 HTML/PDF/Markdown 变成 RAG-ready 干净文本的规则集合。

### 1.2 MimirQ 现状快照(规模)

**后端 `app/rag/preprocessing/` ~5500 行**(35+ 模块):

| 类别 | 主要文件 | 行数 |
|---|---|---|
| 核心清洗 | `cleaning.py` | **805** |
| 停用词 | `stopwords.py` | **1370** |
| Markdown 规范化 | `markdown_canonical.py` | 299 |
| PII 三件套 | `pii_anonymizer.py`/`pii_presidio.py`/`pii_llm_discover.py` | 219+96+60 |
| 质量过滤 | `quality_filters.py` | 189 |
| Boilerplate | `boilerplate.py` | 166 |
| 表格 | `tables.py` | 176 |
| 密钥扫描 | `secrets.py` | 160 |
| Rule packs | `rule_packs.py`(8 套预定义包) | 119 |
| 规则编排 | `rules.py`(`DEFAULT_MARKDOWN_RULES` 13 条 + `build_governance_rules`) | 76 |
| 近重复 | `near_dedup.py` | 203 |
| 段落去重 | `paragraph_dedup.py` | 110 |
| Unicode 规范化 | `normalization.py` | 78 |
| HTML 规范化 | `html_canonical.py`/`html_xpath.py` | 69+118 |
| SimHash | `simhash.py` | 62 |
| 引用清理 | `references.py` | 107 |
| 语种识别 | `language.py` | 80 |
| 合成 QA | `synthetic_qa.py` | 68 |

**`app/parsing/preprocess/` ~850 行**(图像/水印/OCR 前置):

| 文件 | 行数 |
|---|---|
| `watermark.py` | 459 |
| `handwriting_cleanup.py` | 235 |
| `llm_noise_miner.py` | 109 |
| `industry_noise_patterns/industrial_control.py` | **22**(13 条规则) |
| `industry_noise_patterns/legal.py` | **14**(5 条) |
| `industry_noise_patterns/finance.py` | **14**(5 条) |

**关键发现:**
- 通用清洗栈业界一流(5500 行,8 套 rule packs 含 cookie 横幅/邮件免责/web 导航/Slack-Teams 导出/PDF 水印/Confluence-Jira/WeChat 公众号/PDF 中文页眉页脚/Notion/markdown 通用)
- **行业噪声规则严重不足**:industrial_control 13 条、legal 5 条、finance 5 条,远未达 production 级别
- **未接入 trafilatura/justext/readability** 这类业界 SOTA HTML 抽取器
- MinHash 实现是自研 `near_dedup.py` 203 行,需对照 `text-dedup`/Milvus 2.6 MinHash LSH 量化

---

## 2. 业界主流清洗范式七大支柱

### 2.1 Boilerplate 移除(HTML→正文)

**SIGIR 2023 横向 benchmark**(14 个抽取器):
- **Readability**: 中位数 0.970 F1(稳定性最强)
- **Trafilatura**: 平均 0.883 F1(综合最强;级联 fallback:XPath → readability-lxml → jusText)
- **jusText**: 平均较弱但语言学语料友好
- Goose3: precision 高、recall 低
- **重要结论:启发式抽取器持续优于大型神经模型**

**ScrapingHub 2025 实测 F1**:
- go_trafilatura: **0.960** ± 0.007
- go_readability_fork: 0.947
- go_readability: 0.934
- justext 3.0.2: 0.804

**生产经验**(HuggingFace/IBM/Microsoft Research/Allen Institute/Stanford 用 trafilatura):
- 默认 `fast=True` 跳过 fallback 提速 2×
- 集成投票(Readability×2 + Trafilatura×2 + Goose3)再涨 2-3 pt

### 2.2 文本去重(三档级联)

**业界共识级联**:
```
exact hash (MD5/SHA256/blake3)     ← 0 误差,毫秒级
        ↓
MinHash LSH                         ← Jaccard ≥ T 召回,毫秒级
        ↓
SimHash + Hamming distance          ← bit-level 模糊匹配
        ↓
semantic dedup(cosine > 0.95)      ← 嵌入向量,百毫秒
```

**text-dedup benchmark**(pinecone/core-2020-05-10):
| 算法 | Precision | Recall | Macro F1 | 耗时 |
|---|---|---|---|---|
| MinHash | 0.9587 | 0.9416 | **0.9518** | 11s |
| SimHash | 0.9038 | 0.7323 | 0.8515 | 626s |

**关键参数**:
- GPT-3 经验:**10 个 MinHash 值合并作分组键**(Spark MinHashLSH)
- LSH banding:rows-per-band=50, bands=2 → Jaccard ≥ 0.95 命中 80%
- DCLM benchmark 反直觉:**Bloom filter 比 MinHash 单独更好**(精度小幅下降,内存降 87.2%、速度升 38.4%)
- Milvus 2.6 已原生集成 MinHash LSH 索引(2025),可与向量检索同 API

### 2.3 PII 脱敏(Microsoft Presidio)

**Presidio 架构**(开源 SOTA):
- **Analyzer**:NER + Regex + Checksum(信用卡 Luhn / IBAN / SSN)+ Context-aware
- **Anonymizer**:redact / hash(2025 新支持 salted hash 防暴力)/ encrypt / replace
- **Image Redactor**:OCR + 检测
- **Structured**:DataFrame / CSV
- **多语言**:通过切换 NLP 引擎(spaCy/Stanza/transformers)支持新语种,**中文需自配 `zh_core_web_*` + 自定义中文 PII recognizer**(姓名/身份证/手机号/银行卡 17 位)

**2025 升级**:Surrogate operator(医疗 PHI)+ Aadhaar(印度)+ LangExtract recognizer + cryptography ≥ 46.0.4

**关键设计**:
- Presidio API 默认无认证,**必须在反向代理/网关侧加 auth**
- 自动检测保底,**不保证 100% 召回**,需配审核闭环

### 2.4 Unicode 规范化(NFC vs NFKC)

| 形式 | 行为 | 用途 | 风险 |
|---|---|---|---|
| **NFC**(规范组合) | café 等价 → 单一码点 | 显示/归档/copy-paste 保真 | 极少误伤 |
| NFD(规范分解) | é → e + ́ | 内部处理 | 字符串变长 |
| **NFKC**(兼容组合) | ﬁ → f+i、½ → 1/2、Ⅸ → IX | 检索/去重/词表压缩 | **OCR 数字陷阱**:1½ → 11/2 严重歧义,金融/科学场景灾难 |
| NFKD(兼容分解) | 同 NFKC + 分解 | LLM 训练词表压缩 | 同 NFKC |

**业界推荐**:
- RAG 入库:**NFC 安全默认**,保留 OCR-原图对应关系
- LLM 训练:NFKC 收益更大(词表压缩),但要单独跑数字保护规则
- Unicode 17.0(2025-09 发布)、`pyunormalize` 不依赖 Python 内置数据库
- ICU 提供 `NFKC_Casefold`(NFKC + casefold + 去 ignorable),适合检索

### 2.5 LLM 训练级数据清洗管线(2025 SOTA)

**主要数据集级联**(从 Common Crawl 提炼):
| 数据集 | Tokens | 关键创新 |
|---|---|---|
| C4 | 160B | "lorem ipsum" 移除 / "javascript" 提示移除 / 句末标点要求 |
| RefinedWeb | 600B | **MDR(MacroData Refinement)管线** + URL 黑名单(adult/gambling)+ 极致 dedup |
| Dolma | 3T | 公开 + 可复现 |
| **FineWeb** | 15T | **per-dump MinHash dedup** + C4 启发式 + 教育分类器 |
| FineWeb-Edu | 1.3T | Llama-3-70B 打分 500k 样本 + classifier 过滤 92% |
| RedPajama-v2 | 30T | 多维质量信号(40+ 信号) |
| DCLM | 240T → 3.8T | **fastText 分类器 > AskLLM/PPL/PageRank/top-k logits** |

**RefinedWeb 残酷淘汰率**(给 MimirQ 客户做清洗预期管理用):
- 非英文 50% 砍掉
- 质量过滤 24% 砍掉
- 去重 12% 砍掉
- **最终留下 14%**

**DCLM 决策矩阵**(谁的分类器更好):
- 文本抽取:**resiliparse ≈ trafilatura**,resiliparse 快几倍
- 去重:**Bloom > MinHash**(对 trillion 级)
- 质量打分:**fastText > AskLLM > Perplexity > PageRank**

### 2.6 ES/OpenSearch 同义词派的清洗启示

虽然 synonym 是检索期改写,但 ES `synonym_graph` token filter 的部分原则也适用于清洗规则:
- **search-time vs index-time**:规则改了不要 reindex,**MimirQ 现在所有 cleaning 都是 ingest-time 写死**,缺**清洗规则热更新通路**
- 多词组合用 `synonym_graph`,清洗规则同理要支持 multi-line 模式(目前 `RegexRule` 是 line-oriented)
- `lenient: true` 解析失败时容错而非全盘失败

### 2.7 测量清洗效果(Golden Set + Ragas/TruLens)

**业界共识**:不测就别做清洗
- **50-150 Q&A pairs Golden Set**(对照 `evaluation/poc_runner/` 已有的 50 题路线)
- 指标:Recall@k / Precision@k / Faithfulness / Answer Relevance / 归因正确率
- 清洗前后跑同一套 query,delta 必须 +5pt 才算有效;否则清洗规则可能在毁伤召回(C4 经验:**过度过滤把性少数 / 健康 / 非裔英语内容也砍掉了**)

---

## 3. MimirQ 现状 vs 业界对照矩阵

| 清洗维度 | MimirQ 现状 | 业界主流 | 差距 |
|---|---|---|---|
| **HTML boilerplate** | 自研 `html_canonical.py`(69)+ `html_xpath.py`(118)+ `boilerplate.py`(166) | trafilatura F1 0.960 / Readability median 0.970 / 集成投票 | ★★★(未集成 trafilatura) |
| **Markdown 规范化** | `markdown_canonical.py` 299 + `DEFAULT_MARKDOWN_RULES` 13 条 | 通用 | ★(已对齐) |
| **Unicode 规范化** | `normalization.py` 78 行 | NFC 默认 + NFKC 配置 + 数字保护(1½/Ⅸ/⁵) | ★★(数字保护未见) |
| **Exact dedup** | `simhash.py` 62 + `near_dedup.py` 203 + `paragraph_dedup.py` 110 | MD5/SHA256/blake3 + MinHash LSH + SimHash 三档级联 | ★★ |
| **MinHash LSH** | 自研在 `near_dedup.py` | text-dedup / Milvus 2.6 原生 / Bloom 加速 | ★★(没用现成成熟实现) |
| **PII 检测** | `pii_presidio.py` 96 + `pii_anonymizer.py` 219 + `pii_llm_discover.py` 60 | Presidio + 中文 spaCy 模型 + 自定义 recognizer | ★(已用 Presidio) |
| **PII 中文 recognizer** | 不详 | 身份证 18 位/手机号 11 位/银行卡 16-19 位/统一社会信用 18 位需自配 | ★★(需核验) |
| **密钥扫描** | `secrets.py` 160 | gitleaks / trufflehog / 自研 regex | ★ |
| **质量过滤** | `quality_filters.py` 189 | C4 启发式(句末标点/lorem ipsum/{)+ fastText 分类器(DCLM) | ★★★(无 fastText 分类器) |
| **语种识别** | `language.py` 80 | fastText lid / langid / cld3 | ★ |
| **行业噪声(通用 rule_packs)** | 8 套(cookie/邮件/web 导航/Slack-Teams/PDF 水印/Confluence-Jira/WeChat MP/PDF 中文页脚/Notion/markdown 通用) | 业界各家自己整 | ★(已完整) |
| **行业噪声(垂类)** | industrial_control 13 / legal 5 / finance 5 — **极薄** | 各行业各自 50+ 条 | ★★★★ |
| **OCR 纠错** | `paddle_doc_preprocess.py` + `handwriting_cleanup.py` 235 + `watermark.py` 459 + `deskew.py` + `orientation.py` | 图像端齐全,文本端 1½→1/2 类纠错 unclear | ★★ |
| **引用清理** | `references.py` 107 | 期刊 ref 格式 + URL 截断 + footnote 移除 | ★ |
| **表格保留/移除** | `tables.py` 176 | Docling 97.9%(P0 plan 已规划接入) | ★ |
| **段落级去重** | `paragraph_dedup.py` 110 | Anthropic Contextual 反向 / 跨文档段落 LSH | ★★ |
| **合成 QA** | `synthetic_qa.py` 68 | DCLM seed-based / FineWeb-Edu classifier | ★★★ |
| **热更新规则** | 没有(ingest-time 编译 RegexRule) | ES `updateable:true` / Coveo CMS | ★★★ |
| **清洗效果回归** | 未见 Golden Set 跑 cleaning before/after | 50-150 QA + Ragas Faithfulness | ★★★★ |
| **批量行业规则导入** | 单文件 PR 提 RegexRule | Alation 50k/day bulk import | ★★ |

---

## 4. 七个 P0 清洗修复点(2-3 周可见生产价值)

### 4.1 接入 trafilatura(P0,1 day)

`pip install trafilatura` 然后:

```python
# app/rag/preprocessing/html_canonical.py 扩容
def extract_main_content_trafilatura(html: str) -> str:
    import trafilatura
    return trafilatura.extract(
        html,
        favor_recall=False,      # 优先 precision
        include_comments=False,
        include_tables=True,      # 表格保留,后续 tables.py 处理
        deduplicate=True,         # 内置段落去重
        target_language=None,     # 自动检测
    ) or ""
```

**验证**:跑 50 个客户 HTML 样本,trafilatura vs 当前 boilerplate 的 F1 / 字符级 diff;遇到 trafilatura 抽空或异常,fallback 现有逻辑。

### 4.2 数字保护型 NFKC(P0,0.5 day)

```python
# normalization.py 扩
def normalize_unicode_safe(text: str, *, mode: str = "nfc_then_nfkc_safe") -> str:
    if mode == "nfc":
        return unicodedata.normalize("NFC", text)
    if mode == "nfkc_safe":
        # 先保护数字字面,再 NFKC,再还原
        protected = _protect_number_glyphs(text)  # ½/¼/⅓/³/Ⅸ 等映射占位符
        normalized = unicodedata.normalize("NFKC", protected)
        return _restore_number_glyphs(normalized)
    return text
```

**理由**:OCR 输出的 1½ 不能简单 NFKC 变 11/2,金融报表会爆炸。

### 4.3 中文 PII recognizer 补齐(P0,1.5 day)

`app/rag/preprocessing/pii_presidio.py` 加 4 个中文 recognizer(Presidio EntityRecognizer 子类):

```python
# 身份证 18 位 + 校验位
class CNIDCardRecognizer(EntityRecognizer):
    PATTERN = r"[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[012])(0[1-9]|[12]\d|3[01])\d{3}[\dX]"
    # + 校验位算法(GB 11643)

# 手机号 11 位
class CNPhoneRecognizer: PATTERN = r"1[3-9]\d{9}"

# 银行卡 16-19 位 + Luhn
class CNBankCardRecognizer: ... (Luhn 算法)

# 统一社会信用 18 位
class CNUSCIRecognizer: PATTERN = r"[0-9A-Z]{18}"
```

**验证**:用 `tests/test_pii_*.py` 扩 zh fixture。

### 4.4 行业噪声规则扩容(P0,2 day)

| 行业 | 当前规则数 | 目标(参考 Anthropic Contextual 中文样本) | 来源 |
|---|---|---|---|
| `industrial_control.py` | 13 | 50+(论坛/工控手册/设备说明书页脚) | 已有客户 PoC 样本 |
| `legal.py` | 5 | 60+(法院文书页脚 / 律所水印 / 当事人页 / 合同模板印章页) | 中国裁判文书网公开样本 |
| `finance.py` | 5 | 50+(招股书 / 年报 / 分析师报告免责声明 / Bloomberg 水印 / Wind 数据来源) | 巨潮资讯公开 PDF |
| 新增 `medical.py` | - | 40+(诊疗记录页脚 / 患者隐私模板 / HIS 系统导出标记) | 需医院 PoC 客户支持 |
| 新增 `government.py` | - | 50+(发文头 / 文号 / 印章 / 签发栏) | 政府公开文件 |
| 新增 `manufacturing.py` | - | 40+(SOP 模板 / 工艺卡片 / 质检报告页脚) | 制造业 PoC 客户 |

**做法**:`llm_noise_miner.py` 已经存在(109 行),让客户上传 5-10 份样本后跑 LLM mining 自动建议规则,人工 review 后入 `industry_noise_patterns/<industry>.py`。

### 4.5 切换 MinHash 到成熟库(P0,1 day)

```python
# near_dedup.py 重构
from datasketch import MinHash, MinHashLSH

def near_dedup_documents(docs, threshold=0.85, num_perm=128):
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    sigs = {}
    for doc_id, text in docs.items():
        m = MinHash(num_perm=num_perm)
        for shingle in _shingles(text, k=5):
            m.update(shingle.encode())
        lsh.insert(doc_id, m)
        sigs[doc_id] = m
    # 返回每个 doc 的近重复候选
```

**理由**:`datasketch` 库已在工业界(Spark MinHashLSH 也是这个原型)成熟,自研 203 行容易踩 banding 参数错或 hash 碰撞坑。

### 4.6 清洗效果 Golden Set 回归(P0,1.5 day)

```bash
evaluation/cleaning_bench/
├── corpus/                     # 50-150 段原始文本(HTML/PDF/Markdown)
├── golden/                     # 人工标的"应该被清洗"和"应该保留"
├── runners/
│   ├── trafilatura_vs_self.py
│   ├── minhash_dedup_recall.py
│   ├── pii_zh_coverage.py
│   └── industry_noise_pack_<industry>.py
└── reports/                    # 单文件 HTML 报告(对齐 PoC plan 三原则)
```

**指标**:
- Boilerplate F1 ≥ 0.92(对标 trafilatura 0.960)
- Near-dup Macro F1 ≥ 0.94(对标 MinHash text-dedup 0.95)
- PII 中文召回 ≥ 0.95(身份证/手机号/银行卡)
- 行业噪声 precision ≥ 0.98(不能误删正文)

### 4.7 接入 trace SSE(P0,0.5 day)

`/processing` 期间在 SSE trace 上透出每条规则命中率:

```
🧹 governance.cleaning
  - DEFAULT_MARKDOWN_RULES: 13 rules, 142 matches
  - pack:pdf_header_footer_cn: 23 matches
  - industry:legal: 8 matches, 5 rules fired
  - removed_lines: 173 (total input 5,243 lines, retained 96.7%)
```

让客户看到每条规则确实在生效,出错时一眼定位是哪条规则误伤。

---

## 5. P1(1 个月,接入 LLM-driven 增强)

### 5.1 fastText 质量分类器(DCLM 派)

参考 DCLM 决策:`fastText > AskLLM > Perplexity > PageRank`,训一个 ~1 小时的 fastText 二分类(seed-based 标 5000 高质量 + 5000 低质量),给每个 chunk 打 0-1 score。

落点:`app/rag/preprocessing/quality_classifier_fasttext.py`(new,~200 行)

### 5.2 LLM-driven 行业规则挖掘 V2

`llm_noise_miner.py`(109 行)已有雏形,扩成:
- 客户上传 20 份样本 → Claude Haiku 4.5 跑两阶段(候选挖掘 + 规则去重合并)
- 输出 candidate RegexRule + 命中示例 + 置信度
- 写入 `industry_noise_patterns/<industry>.candidates.py`,前端 review 后 promote

成本:¥0.005/规则 × 50 = ¥0.25/客户的一次性 onboarding。

### 5.3 段落级跨文档 dedup(Anthropic Contextual 反向)

跨文档查重,识别"被复制粘贴 N 份"的段落(法律/合规文档常见免责声明 templates),给 dedup 加 `cross_doc_paragraph_lsh` 模式。

### 5.4 OCR 后处理纠错(LLM 辅助)

针对 OCR 残留(1½ / 〇 / 鈤 / 朩):
- 规则层:字典映射 + 正则修复
- LLM 层:Claude Haiku 看上下文判定(成本 ¥0.001/页)
- 落点:`app/rag/preprocessing/ocr_postcorrect.py`(new,~300 行)

### 5.5 热更新规则通路

规则改了不重 ingest 也能立刻生效:
- 规则存 Postgres(对齐 `industry_rules` 模式)
- `RuleEngine` 单例 + Redis pubsub 通知重载
- 配 `updateable: true` 语义

### 5.6 清洗规则 CMS(前端)

`/governance/cleaning-rules/` 页(对照 Alation/Collibra Steward 工作流):
- 三 Tab:DEFAULT_MARKDOWN_RULES / Rule Packs / Industry Patterns
- 每条规则状态:draft → review → approved → deprecated
- 命中预览(把候选规则跑在 50 段样本上看 diff)
- 批量导入 CSV(对齐 Alation 50k/day)

---

## 6. P2(独立调研,1-2 季度)

### 6.1 trafilatura/resiliparse benchmark 对照

按 DCLM 经验,**resiliparse 比 trafilatura 几倍速度,F1 相近**。MimirQ 处理客户大规模历史数据时(几十 GB 网页存档),resiliparse 可能是更优选。

### 6.2 Bloom filter dedup(trillion-scale)

如果未来客户语料达到 100M 文档以上,引入 LSHBF(Bloom 加速的 MinHash LSH),内存降 87%、速度升 38%(Preferred Networks 2025)。

### 6.3 多模态清洗(图像水印 + 印章)

`watermark.py`(459)已处理水印,但**印章去除 / 红章保留(法律要保留印章作证据)** 是法律金融场景独立赛道,可独立 plan。

### 6.4 清洗规则作为 Open Source Pack

参考 Presidio 的开源 recognizer pack 模式,把 MimirQ 8 套 governance + 行业 noise 开源(只开通用层,行业层做付费包)——既建社区影响力又不损护城河。

---

## 7. 不该做的事(基于业界教训)

- ❌ **不要默认 NFKC**:OCR 1½ → 11/2 / Ⅸ → IX 在金融场景会造数据事故
- ❌ **不要过度过滤**:C4 教训是把性少数/健康/非裔英语过度清洗掉,**RAG 客户的 DEI/医疗/合规文档不能用通用激进过滤**;quality_filters 默认应"宁松勿严"
- ❌ **不要把 PII anonymizer 默认 redact 用在所有 dataset**:有的合规客户*恰恰需要保留*姓名/工号做检索,redact 模式应可按 dataset 切换(目前 MimirQ 状态需核验)
- ❌ **不要重复造 MinHash 轮子**:`datasketch` / Spark MinHashLSH / Milvus 2.6 都有成熟实现
- ❌ **不要把 trafilatura 当唯一**:虽然 F1 最高,但对 Salesforce/Confluence 这类 SPA 渲染前的 HTML 失败率很高,要有 fallback
- ❌ **不要清洗后不跑 Golden Set 回归**:不测就改清洗规则等于 random walk,Vectara 2024 NAACL 论文已经实证过"过度清洗反而毁伤检索"

---

## 8. 关键文件清单(将动)

### 后端(P0)
- `app/rag/preprocessing/html_canonical.py:1`(接 trafilatura)
- `app/rag/preprocessing/normalization.py:1`(数字保护型 NFKC)
- `app/rag/preprocessing/pii_presidio.py:1`(中文 PII recognizer 4 个)
- `app/rag/preprocessing/near_dedup.py:1`(切 `datasketch.MinHashLSH`)
- `app/parsing/preprocess/industry_noise_patterns/{industrial_control,legal,finance}.py`(扩容至 50+ 条 each)
- `app/parsing/preprocess/industry_noise_patterns/{medical,government,manufacturing}.py`(new)
- `evaluation/cleaning_bench/`(new,Golden Set + 4 个 runner)

### 后端(P1)
- `app/rag/preprocessing/quality_classifier_fasttext.py`(new)
- `app/rag/preprocessing/ocr_postcorrect.py`(new)
- `app/parsing/preprocess/llm_noise_miner.py:1`(扩成两阶段挖掘 + candidates promote)
- `app/api/v1/cleaning_rules.py`(new,CRUD + hot reload)

### 前端(P1)
- `web/app/governance/cleaning-rules/page.tsx`(new)
- `web/components/cleaning-rules/cleaning-rules-workbench.tsx`(new)
- Trace SSE 渲染:`web/components/chat/trace-renderer.tsx`(扩 🧹 governance.cleaning)

### 测试
- `tests/test_html_trafilatura_integration.py`(new)
- `tests/test_normalization_number_protection.py`(new)
- `tests/test_pii_zh_recognizers.py`(new)
- `tests/test_near_dedup_datasketch.py`(new)
- `tests/test_industry_noise_pack_<industry>.py` × 6(new)
- `tests/test_cleaning_golden_set_regression.py`(new)

---

## 9. 验证

### 9.1 P0 验证

1. `pytest evaluation/cleaning_bench/runners/*.py` 全绿,各项指标达标(见 §4.6)
2. 起服务 → upload 客户 PDF(法律合同/工控手册/财报)→ 处理 trace 显示每条规则命中率
3. 清洗前后跑同一个 50 问 Golden Set,**检索 Recall@5 不降反升 +3pt 以上才算 P0 完工**
4. 中文 PII:身份证/手机号/银行卡/统一社会信用召回 ≥ 95% on test fixture

### 9.2 P1 验证

1. fastText 质量分类器:在 5000 样本上 AUC ≥ 0.85
2. LLM noise miner:20 份新样本 30 min 内产出 ≥ 30 条 candidate 规则,人工 approve 率 ≥ 60%
3. 跨文档段落 dedup:在 1000 篇法律合同样本上,识别 ≥ 90% 的"复制粘贴免责声明段"
4. 热更新:规则改完 5s 内全实例生效

---

## Sources

- [Build an unstructured data pipeline for RAG — Databricks](https://docs.databricks.com/aws/en/generative-ai/tutorials/ai-cookbook/quality-data-pipeline-rag)
- [The Role of Data Preprocessing in RAG — deepset Blog](https://www.deepset.ai/blog/preprocessing-rag)
- [Mastering Data Cleaning for Fine-Tuning LLMs and RAG Architectures — The AI Alliance](https://thealliance.ai/blog/mastering-data-cleaning-for-fine-tuning-llms-and-r)
- [How to prepare data for your RAG pipeline — TechTarget](https://www.techtarget.com/searchenterpriseai/tip/How-to-prepare-data-for-your-RAG-pipeline)
- [Your RAG Bot is Stupid Because Your Data is Dirty (Medium 2025)](https://medium.com/@AgenticAri/your-rag-bot-is-stupid-because-your-data-is-dirty-here-is-the-cleaning-pipeline-bd639f8a7c68)
- [Ultra-FineWeb: Efficient Data Filtering and Verification (arXiv 2025-05)](https://arxiv.org/html/2505.05427v1)
- [The FineWeb Datasets — Decanting the Web at Scale (arXiv 2024)](https://arxiv.org/html/2406.17557v1)
- [DCLM / DataComp for Language Models — DatologyAI Deep-Dive](https://www.datologyai.com/blog/technical-deep-dive-curating-our-way-to-a-state-of-the-art-text-dataset)
- [Trafilatura — Web Content Extraction with Python](https://www.contextractor.com/trafilatura/)
- [Trafilatura Evaluation — Official Docs](https://trafilatura.readthedocs.io/en/latest/evaluation.html)
- [An Empirical Comparison of Web Content Extraction Algorithms (SIGIR 2023)](https://dl.acm.org/doi/pdf/10.1145/3539618.3591920)
- [scrapinghub/article-extraction-benchmark — GitHub](https://github.com/scrapinghub/article-extraction-benchmark)
- [jusText — PyPI](https://pypi.org/project/jusText/)
- [go-trafilatura — markusmobius/go-trafilatura](https://github.com/markusmobius/go-trafilatura)
- [MinHash LSH in Milvus 2.6 — Milvus Blog](https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md)
- [ChenghaoMou/text-dedup — All-in-one text de-duplication](https://github.com/ChenghaoMou/text-dedup)
- [Improve MinhashLSH for Deduplication at Scale — Preferred Networks 2025](https://tech.preferred.jp/en/blog/improve-minhashlsh-for-deduplication-on-large-scale-dataset/)
- [Data Deduplication at Trillion Scale — Zilliz Blog](https://zilliz.com/blog/data-deduplication-at-trillion-scale-solve-the-biggest-bottleneck-of-llm-training)
- [MinHash — Wikipedia](https://en.wikipedia.org/wiki/MinHash)
- [Document Deduplication with LSH — Matti Lyra](https://mattilyra.github.io/2017/05/23/document-deduplication-with-lsh.html)
- [microsoft/presidio — GitHub](https://github.com/microsoft/presidio)
- [Microsoft Presidio Home](https://microsoft.github.io/presidio/)
- [Presidio Multi-Language Support docs](https://microsoft.github.io/presidio/analyzer/languages/)
- [Presidio 2025 Releases](https://github.com/microsoft/presidio/releases)
- [Preventing PII leakage when using LLMs — Ploomber Blog](https://ploomber.io/blog/presidio/)
- [Unicode Normalization Forms — UAX #15](https://www.unicode.org/reports/tr15/)
- [ICU Normalization Documentation](https://unicode-org.github.io/icu/userguide/transforms/normalization/)
- [pyunormalize — Unicode 17.0 (2025)](https://github.com/mlodewijck/pyunormalize)
- [OCRmyPDF NFC vs NFKC issue #1282](https://github.com/ocrmypdf/OCRmyPDF/issues/1282)
- [Text Normalization: Unicode Forms, Case Folding & Whitespace — Michael Brenndoerfer](https://mbrenndoerfer.com/writing/text-normalization-unicode-nlp)
