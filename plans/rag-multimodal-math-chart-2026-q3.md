# Math / Formula / Chart RAG（能力 P1 #3，2026 Q3）

> 把现有 *文本 + 表格 RAG* 升级为 **数学推理 + 公式求解 + 图表数据抽取** 三位一体的多模态 RAG。客户问"这张柱状图 2023 年增长多少 / 这个公式怎么推导 / 财报附表里 ROE 排第几" —— 当前 RAG 只能返回 chunk 文本，本能力让其能 *实际推理*。
>
> 创建日期：2026-05-08
> 来源：`rag-gap-and-recommendations-summary-2026-q2.md` 第 5.2 节真 GAP / 用户对话 2026-05-08 聚焦能力
> 优先级：P1（能力 #3）
> 状态：**Stage 0 PASS（2026-05-08）**
> Stage 0 验收：复用现有 Chart-to-Data / Formula OCR / Vision Reader / TAG table bridge，不新建多模态大架构；修复图表数值问题的 modality routing；补齐回归测试。
>
> **核心一句话**：MimirQ 已有 deepdoc 解析公式 / 表格 / 图表 *形态*，并且已经有 Chart-to-Data、Formula OCR、Vision Reader 与 TAG 表格桥接的雏形；后续重点不是重造 `app/rag/multimodal/*`，而是把现有能力收敛成可评测、可引用、可回归的 Math / Formula / Chart RAG 链路。

## Stage 0 PASS 记录（2026-05-08）

| 项 | 结论 | 验收 |
|---|---|---|
| Chart RAG 基础 | 已有 `app/parsing/enrich/chart_to_data.py`，可把图表图片追加为 `Chart data:` JSON 块 | 通过既有 `tests/test_chart_to_data.py` |
| Formula OCR 基础 | 已有 `app/parsing/enrich/formula_ocr.py`，可把公式图片转为 LaTeX 并产出 equation elements | 通过 `tests/test_formula_ocr.py` / `tests/test_formula_elements.py` |
| Vision Reader | 已有 `app/rag/core/vision_reader.py`，可在 image evidence 命中后调用 VLM 读取图像证据 | 通过 `tests/test_vision_reader_context_docs.py` |
| Chunk 类型 | 已有 `chart_data` / `formula` 子索引分类与 query chunk type boost | 通过 `tests/test_chunk_type_labels.py` / `tests/test_chunk_type_subindex.py` |
| Table-Math 基础 | 已有 `app/api/v1/dataset_tables.py` 的 NL2SQL / TableAsk / Lotus sem-filter；RAG engine 已有 TAG bridge | 通过源码核对，后续 Stage 1 补端到端评测 |
| Router 修复 | 图表数值问题不再被“多少/占比”等表格词误路由成 table，显式 SQL 仍保持 table 优先 | 通过 `tests/test_modality_router.py` |

Stage 0 的 PASS 含义：**接线和事实校准通过**，可以进入 Stage 1（schema 收敛 + Golden 评测 + 端到端演示）。这不代表 Wolfram / SymPy / 大规模多模态评测已经 GA。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 现状盘点（已识别形态，缺推理） |
| 第 2 章 | 三个子能力（Math / Formula / Chart） |
| 第 3 章 | 落点设计（4 个） |
| 第 4 章 | 业界对标 |
| 第 5 章 | 评测集 |
| 第 6 章 | Stage 0 / Stage 1 里程碑 |
| 第 7 章 | 风险 + 范围之外 |

---

## 1 现状盘点

### 1.1 已有底层能力

| 能力 | 文件 | 状态 |
|---|---|---|
| 表格识别（vision） | `app/deepdoc/vision/table_structure_recognizer.py` | ✅ 597 行 |
| 表格 OCR | deepdoc | ✅ |
| Layout 识别 | `app/deepdoc/vision/layout_recognizer.py` | ✅ 254 行 |
| Text-to-SQL（结构化表 QA） | `app/api/v1/dataset_tables.py` | ✅ 1049 行（含 LotusSemFilter / TableAsk） |
| 公式 LaTeX 识别 | deepdoc 部分支持 | ⚠️ 部分 |
| 图表识别（vision） | deepdoc | ⚠️ 形态识别；结构化抽取由 Chart-to-Data 增强补齐 |
| Chart-to-Data 解析增强 | `app/parsing/enrich/chart_to_data.py` | ✅ 已有 HTTP backend 接入、`Chart data:` JSON 注入、审计信息 |
| Formula OCR 解析增强 | `app/parsing/enrich/formula_ocr.py` | ✅ 已有公式图片 → LaTeX、equation elements、审计信息 |
| Vision Reader | `app/rag/core/vision_reader.py` | ✅ 已有 VLM-as-Reader，读取 image evidence 并注入文本上下文 |
| Chunk 类型子索引 | `app/rag/chunking/roles.py` / `app/rag/retriever.py` | ✅ 已识别 `chart_data` / `formula` 并支持 query type boost |
| TAG 表格桥接 | `app/rag/engine.py` + `app/services/chat_tag_service.py` | ✅ 表格 query 可注入 TableAsk / TAG 结果 |

### 1.2 真正缺失的"推理层"

- ✅ **图表数据抽取入口**：已存在 `chart_to_data.py`，但 schema、缓存、引用呈现仍需统一
- ❌ **公式求解**：已识别 LaTeX，但**不做数值/符号求解**
- ❌ **数学推理**：纯文本数学题（"X 增长多少%"）能力弱
- ⚠️ **表格 + 文本 联合推理**：dataset_tables / TAG 已有桥接，缺 Golden 评测与差距分析
- ⚠️ **图表/公式端到端评测**：已有局部单测，缺 dataset 级 Golden 回归集

### 1.3 客户场景痛点

- **金融场景**：财报附图 / 公式（PE 比率公式 / 现金流公式）/ 跨表汇总
- **学术场景**：公式推导 / 数学题
- **工程场景**：技术参数图表 / 趋势线
- **保险 / 法律场景**：精算公式 / 计算条款

### 1.4 Stage 1 真正缺失的 4 件事

1. **图表 schema 收敛**：把 `Chart data:` JSON 统一成可引用、可缓存、可评测的结构
2. **公式 → 轻量求解**：LaTeX / 文本公式 → 安全 calculator；SymPy / Wolfram 放到 Stage 2
3. **跨表数学评测**：复用 dataset_tables / TAG，补排名、占比、Top N、CAGR 的 Golden 样本
4. **多模态回归评测**：把 chart/formula/table-math 加入 Golden 回归与 badcase 分析

---

## 2 三个子能力

### 2.1 子能力 A：Chart RAG（图表数据抽取 + 推理）

**输入**：用户 query + 含图表的文档 chunk
**输出**：用户问题答案 + 图表数据来源

**Pipeline**：
1. 解析时识别图表区域（deepdoc 已支持）
2. 用现有 Chart-to-Data backend / Vision LLM 抽取 (x, y) 数据点
3. 数据 cache（避免重复调用）
4. RAG 时根据 query 匹配图表 + 回填数据
5. LLM 基于结构化数据回答

**示例**：
```
Query: "X 公司研发投入趋势"
检索：找到含柱状图的 chunk
Chart-to-Data: 抽出 (2020, 1.2亿), (2021, 1.5亿), (2022, 2.1亿), (2023, 3.0亿)
Answer: "2020-2023 研发投入从 1.2 亿增至 3.0 亿，CAGR 35.7%"
        + 引用图表 [chart_id]
```

### 2.2 子能力 B：Formula RAG（公式求解）

**输入**：用户 query + 含公式的文档 chunk
**输出**：求解结果 + 推导步骤

**Pipeline**：
1. 解析时识别公式区域（LaTeX / MathML）
2. 公式分类：
   - **数值公式**（"PE = price / EPS"）→ Stage 1 轻量安全 calculator
   - **符号推导**（"求导"）→ Stage 2 SymPy（可选）
   - **复杂数学**（积分 / 微分方程）→ Stage 2 Wolfram Alpha API（可选）
   - **文本推理**（"这个公式说明什么"）→ LLM CoT
3. 求解 + 注入 LLM context
4. LLM 输出含公式渲染（KaTeX）

**示例**：
```
Query: "如果 EPS 涨 10%，PE 下降 5%，价格怎么变？"
检索：找到含 PE 公式的 chunk
Formula calculator: PE = price / EPS → price = PE × EPS
                    price' = (1-0.05) × (1+0.10) × price = 1.045 × price
Answer: "价格上涨 4.5%"
```

### 2.3 子能力 C：Table-Math RAG（跨表数学推理）

**输入**：用户 query + 跨表数据（dataset_tables）
**输出**：聚合 / 计算 / 排名 结果

**Pipeline**：
1. 现有 dataset_tables 1049 行 LotusSemFilter / TableAsk 已有底层 SQL
2. 加层语义路由：query → 哪些表
3. 跨表 join + 聚合（SQL）
4. 数学计算（分位 / 排名 / CAGR）
5. 输出 + 数据出处

**示例**：
```
Query: "招股书前 10 大股东中 QFII 占几个？"
路由：→ shareholders 表
SQL: SELECT shareholder_type FROM shareholders ORDER BY ratio DESC LIMIT 10
计算: count where type = 'QFII'
Answer: "前 10 大股东中有 3 个 QFII（占 30%）"
```

---

## 3 落点设计（Stage 0 已完成，Stage 1 待做）

### 3.1 Stage 0 已完成落点

| 落点 | 文件 | 状态 |
|---|---|---|
| Chart-to-Data 解析增强 | `app/parsing/enrich/chart_to_data.py` | 已有，保留为入口 |
| Formula OCR 解析增强 | `app/parsing/enrich/formula_ocr.py` | 已有，保留为入口 |
| Vision Reader | `app/rag/core/vision_reader.py` | 已有，RAG image evidence 可走 VLM-as-Reader |
| Table-Math 基础 | `app/api/v1/dataset_tables.py` + TAG bridge | 已有，不重写 |
| Query Router | `app/rag/policy/modality_router.py` | 已修复图表数值问题路由 |

### 3.2 Stage 1 落点 A：Chart Schema 收敛

**不新建 `chart_extractor.py`。**

继续复用 `app/parsing/enrich/chart_to_data.py`，补：
- `Chart data:` JSON schema 版本号，例如 `mimirq.chart_data.v1`
- `chart_id` / `source_image` / `page` / `series` / `units` / `confidence`
- 缓存键：`image_hash + backend + prompt_version`
- Golden 评测：数值点误差、单位一致性、引用可追溯

### 3.3 Stage 1 落点 B：Formula Lightweight Solver

**先不引 Wolfram，不默认加 SymPy。**

补一个小范围 query-time calculator：
- 仅处理 `a = b * c`、百分比变化、CAGR、排名/占比等业务公式
- 输入来自 LaTeX / text formula / chart data / table result
- 输出包含 `result`、`steps`、`assumptions`、`source_refs`
- 复杂积分、微分方程、符号证明进入 Stage 2

### 3.4 Stage 1 落点 C：Table-Math Golden 回归

**不新建 `table_math.py`。**

继续走 `dataset_tables.py` / TAG bridge，补：
- 20-30 条 Golden 样本：Top N、占比、排序、CAGR、跨 sheet 简单 join
- 每条样本绑定数据集、标准答案、标准证据
- 指标接入 Golden 回归页：answer exact/tolerance、evidence hit、SQL/plan trace

### 3.5 Stage 1 工作量汇总

| 落点 | 行数 | 工时 |
|---|---|---|
| Chart schema + cache key | 150-220 | 2-3 day |
| Lightweight formula calculator | 180-260 | 3-4 day |
| Table-Math Golden cases | 120-180 | 2 day |
| Multimodal eval/report | 160-220 | 2-3 day |
| **合计** | **~600-880 行** | **~9-12 day** |

---

## 4 业界对标

### 4.1 商业产品

| 产品 | 强项 | 弱项 |
|---|---|---|
| **Mathpix** | 公式 OCR / LaTeX | API 计费 |
| **DocAnalyzer (开源)** | 多模态文档 | 中文弱 |
| **Reducto** | 表格 + 图表抽取 | 推理弱 |
| **Microsoft Math Solver** | 数学题求解 | 不接 RAG |
| **Wolfram Alpha** | 复杂数学 | API 计费 |

### 4.2 学术参考

| 论文 | 会议 | 重点 |
|---|---|---|
| **DocGenome** | NeurIPS'24 | 多模态文档 benchmark |
| **ChartQA** | ACL'22 | 图表 QA 评测 |
| **MathQA** | NAACL'19 | 数学题数据集 |
| **TableQA-LLM** | EMNLP'25 | LLM 表格推理 |
| **PlotQA** | WACV'20 | 复杂 plot 理解 |

### 4.3 选型决策

| 任务 | 选择 | 理由 |
|---|---|---|
| Chart 抽取 | Vision LLM（Claude Vision / GPT-4V） | 成熟、多语言、高准确 |
| 公式简单求值 | Stage 1 轻量 calculator | 无新依赖、可控、便于先接 Golden |
| 公式复杂数学 | SymPy / Wolfram Alpha（Stage 2 可选） | 开关，不进入 Stage 0 / Stage 1 默认路径 |
| 表格 SQL | 现有 dataset_tables | 复用 |
| Math text reasoning | Claude / GPT CoT | 已有 LLM |

---

## 5 评测集

### 5.1 自建 multi-modal 评测集

`evaluation/poc_runner/multimodal_bench/`：
- 50 题 chart QA（财报附图）
- 50 题 formula 求解（PE / CAPM / DCF / ROE 公式）
- 50 题 table-math（前 N 大股东 / 主营业务占比）
- 50 题混合推理（图 + 文 + 公式）

### 5.2 评测维度

| Metric | 含义 |
|---|---|
| **Chart accuracy** | (x, y) 抽取准确率 |
| **Formula accuracy** | 数值答案正确率（± tolerance） |
| **Table-math accuracy** | SQL + 计算 final 答案 |
| **Multimodal F1** | 跨模态联合答题 |
| **Cost per query** | Vision LLM × N 调用成本 |

### 5.3 业界 benchmark

- ChartQA：图表 QA 标准
- DocGenome：多模态文档
- MathQA-zh（如有）：中文数学

---

## 6 里程碑

### Stage 0：接线校准（PASS，2026-05-08）

- [x] 确认 Chart-to-Data / Formula OCR / Vision Reader / TAG bridge 已存在
- [x] 确认 `chart_data` / `formula` chunk type 已有分类和子索引
- [x] 修复图表数值 query 被“多少/占比”等表格词误路由成 table 的问题
- [x] 保持显式 SQL / 聚合 table query 仍走 table
- [x] 跑局部回归测试

### Stage 1：Schema + Golden（建议 9-12 天）

- [ ] Chart data schema v1 + cache key
- [ ] 轻量 formula calculator（不引 Wolfram，SymPy 作为后续选项）
- [ ] 20-30 条 multimodal Golden 样本
- [ ] Golden 回归页接 chart/formula/table-math 切片
- [ ] 报告展示：数值误差、证据命中、成本

### Stage 2：复杂数学与规模化评测（后续）

- [ ] SymPy / Wolfram 可选接入
- [ ] ChartQA / PlotQA / DocGenome benchmark 适配
- [ ] 大规模 badcase 反哺与缓存成本治理

---

## 7 风险 + 范围之外

### 7.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Vision LLM 成本 | 比文本贵 5-10× | 缓存 + 仅在含图表 chunk 启用 |
| 中文图表 | 中文 label 识别质量 | Claude Vision 中文支持已较强 |
| 公式 OCR | LaTeX 转换失败 | 多种 OCR fallback（Mathpix / deepdoc） |
| Wolfram 依赖 | 外部 API 需备案 | 可选开关 |
| 跨模态联合 | 多步推理难 | 与 P0 #2 SC 协同投票 |
| 表格 schema drift | 客户表结构变 | 自动 schema 探测 + audit |

### 7.2 范围之外（明确不做）

- 不做 LaTeX 渲染（前端用 KaTeX 现成库）
- 不做手写公式 OCR（Mathpix 主战场）
- 不做 PDF 公式编辑（Adobe 范畴）
- 不做实时数学题解答（C 端教育产品）
- 不做 3D 图表（罕见）
- 不做动态图（视频 RAG 范畴）

### 7.3 不要的东西

- ❌ 不要每 chunk 都跑 Vision LLM（成本爆炸）
- ❌ 不要同步阻塞解析流程（异步 enrichment）
- ❌ 不要替代 dataset_tables（联动不重做）
- ❌ 不要做"AI 教师"叙事（专业越界）

---

## 8 与既有 plan 协同

| plan | 协同 |
|---|---|
| `rag-parsing-chunking-deep-dive-2026-q2.md` | deepdoc 解析为基础 |
| `rag-cross-doc-synthesis-2026-q3.md`（P0 #1） | 数值冲突时联动 Math 验证 |
| `rag-self-consistency-2026-q3.md`（P0 #2） | 数学题 SC voting |
| `rag-feedback-loop-2026-q3.md`（P0 #5） | bad case 反哺 Vision 训练数据 |
| `rag-evaluation-deep-dive-2026-q2.md` | 多模态 metric 加入 |
| `rag-pre-poc-scanner-2026-q2.md` | 大 Excel >5000 行走 SQL（已规划） |

---

## 9 关键洞察

1. **解析层已有**：deepdoc 与 parsing enrich 已覆盖图表 / 公式 / 表格入口，本 plan 不重做识别
2. **缺的是推理与评测**：从"看见"升级到"算清楚"，同时要能用 Golden 样本证明
3. **不要新建大架构**：Chart-to-Data / Formula OCR / Vision Reader / TAG bridge 先收敛，再扩展
4. **客户场景刚需**：金融 / 学术 / 工程 / 法律 / 保险 五大 vertical
5. **与 P0 #1 #2 #5 强协同**：数值冲突识别 / SC 投票 / feedback 反哺
