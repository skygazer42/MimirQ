# RAG 解析域质量基准计划（2026-Q3）——parse_bench harness 落地 + Docling 装配 + 置信度传播

> 日期：2026-07-13 ｜ 前置调研：`plans/rag-parsing-chunking-deep-dive-2026-q2.md`、`plans/deepdoc-api-productization-2026-q3.md`
> 定位：解析资产极厚（30 parser 6364 行 + deepdoc vision 10161 行 + enrich 26 模块 + 表格全家桶），**但没有一把统一的尺子**——parse_bench 至今是 13 行空壳，"哪个 parser 对哪类文档最好"全凭经验。DeepDoc 要 API 化产品化（Q3 既定方向），没有 benchmark 就没有定价与 SLA 的底气。

## Context（2026-07-13 核实）

- **parse_bench 空壳确认**：`app/rag/evaluation/parse_bench/` 仅 grits.py(10 行 re-export)+__init__(3 行)
- **指标件齐**：`app/parsing/quality/` 已有 benchmark.py / competition.py / scorer.py / grits.py / ocr_validator.py / reading_order.py / text_quality.py / document_quality.py——缺的是 harness（数据集+跑批+报告+CI 门禁），不是指标
- 表格资产：table_transformer_onnx / cross_page_table_linker / formula_ocr / table_canonical / table_cell_schema / table_structure_adapter（`app/parsing/enrich/`）
- Docling 已集成但 **JsonReportProcessor 统一装配缺**（2026-07 核对小缺）；解析路由在 `app/parsing/routing.py`
- pre_poc_scanner 三档判定已接主管线（processor.py drop_if_low_density）

## 落地设计

### P0-1 parse_bench harness（把已有指标串成尺子）
- 结构：`parse_bench/{datasets,runner.py,report.py}`；runner 复用 evaluation runners 的 registry 模式（`runners/registry.py` 先例）。
- **标注集三层**（中文为主，对齐 OmniDocBench 维度但自建）：
  1. 版面层 30 篇：政务红头文/扫描件/双栏论文/合同——评 reading_order + 版面还原（NID）
  2. 表格层 30 张：跨页表/合并单元格/无线表——评 TEDS/GriTS（指标已有，`parse_bench/grits.py` 指向 parsing/quality）
  3. 公式&OCR 层 20 篇：评 formula_ocr 准确率 + ocr_validator 置信度校准
- 输出：**parser × 文档类型矩阵报告**（每格 = 得分+延迟+成本），直接回答"该类文档路由给谁"——报告喂给 `routing.py` 做数据驱动路由（现状路由规则是否数据驱动待此验证）。
- CI 门禁：核心 20 篇进 `pnpm verify` 级别的解析回归，parser 升级/换版必须过。

### P0-2 Docling JsonReportProcessor 统一装配（既定小缺，顺手清）
- Docling 的结构化报告（表格/图/标题层级/置信度）统一进 parse 结果 schema，与 MinerU/deepdoc 输出对齐到同一中间表示——**这是 parser 对照矩阵可比的前提**。落点：`app/parsing/factory.py` + `subprocess_worker.py`。

### P1-1 OCR/解析置信度传播（创新项：解析质量影响检索权重）
- 现状：ocr_validator 的置信度停在解析层。做法：置信度写入 chunk metadata（`parse_confidence`），下游两用——
  1. 检索融合时低置信 chunk 小幅降权（接召回计划的融合信号位）
  2. 答案引用低置信来源时 citation 带"扫描件识别，建议核对原文"标注——政务场景免责刚需
- 延迟成本 ≈0（纯 metadata 透传）。

### P1-2 表格问答专项回归
- 表格全家桶资产多但缺端到端验证：30 张标注表 × "单元格定位/跨页聚合/数值计算"三类问题，跑 表格解析→切块→召回→答案 全链路，定位丢分层。
- 已知风险点：表格切块与 table_canonical 的衔接、跨页表 linker 的召回可见性。

### P2 进阶
- 版面结构进检索：标题层级/章节路径已在 enrich，验证 section-path 作为 metadata filter 的收益（法规"第 X 章第 Y 条"精确定位）。
- 解析失败归因自动分类接 IngestDeadLetter（与入库域 plan 衔接）。
- DeepDoc API 化的 benchmark 报告模板（三档定价对应三档质量 SLA，`deepdoc-api-productization-2026-q3.md` 落地前置）。

## 优先级矩阵

| 优先级 | 任务 | 工作量 | 落点 |
|---|---|---|---|
| P0 | harness（runner+report+CI） | ~5 人日 | `evaluation/parse_bench/` |
| P0 | 标注集 80 篇三层 | ~5 人日（含标注） | `parse_bench/datasets/` |
| P0 | Docling 统一装配 | ~2 人日 | `parsing/factory.py` |
| P1 | 置信度传播两用 | ~3 人日 | chunk metadata + 融合信号 + citation |
| P1 | 表格问答端到端回归 | ~4 人日 | parse_bench + 全链路 case |

## 验证与门槛
- harness 上线标志：任意 parser 一条命令出矩阵报告；路由变更必须引用报告数据。
- 置信度传播：低置信降权 A/B 过显著性检验才默认开（judge 版本按验证域 plan 标注）。

## 不做什么
- 不追 OmniDocBench 榜单本身（自建集贴业务）；不再新增 parser（30 个够了，先测清楚再谈增）；不做全文档 VLM 重解析兜底（成本失控，保留 vision 定向路由）。
