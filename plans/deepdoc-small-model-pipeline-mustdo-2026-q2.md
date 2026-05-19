# DeepDoc 必做执行清单：小模型 Pipeline + 表格 TAG

> 更新：2026-05-19
> 当前口径：不做产品化，不做展示型 Plan，不接通用多模态大模型。
> 目标只保留真实解析能力增强：HuggingFace/ONNX 精准小模型、表格结构化与 TAG、去水印/噪声、阅读顺序、OCR 置信度、解析质量门禁。

---

## 0. 非目标

这些不做，避免把任务变成产品化工程：

| 不做 | 原因 |
|---|---|
| Review UI / 人工校正工作台 | 当前目标是解析能力，不是审核产品闭环 |
| parse decision log 前端时间线 | 属于展示层，不是必做能力 |
| 对外 SDK/API 包装 | 当前只做项目内后端解析链 |
| Qwen-VL/LLaVA/PaddleOCR-VL 这类通用 VLM 默认集成 | 不符合“精准小模型 pipeline”方向 |
| 生成式去水印资产 | 只做解析前抑制和 Markdown 噪声清理，不生成洗图文件 |

---

## 1. 必做范围

### 1.1 小模型 Runtime

目标：把本地 ONNX 与已下载 HF 小模型纳入同一 runtime，默认离线可用，缺模型时可降级。

| 必做项 | 落点 | 验收 |
|---|---|---|
| 模型 manifest | `configs/parsing_small_models.yaml` | 能声明 layout/table/ocr 小模型 |
| runtime loader | `app/parsing/models/` | 能解析本地 ONNX、本地 HF snapshot、可选下载 HF |
| HF 模型落地 | `app/deepdoc/resources/models/hf/` | TATR、PP-OCRv5 等真实 snapshot 放入项目 |
| ONNX 落地 | `app/deepdoc/resources/models/hf_onnx/` | 能加载已转换 TATR ONNX |
| metadata | DeepDoc parse metadata | 输出 `model_id/version/elapsed_ms/status` |

当前状态：

- 已落地 `app/parsing/models/manifest.py`、`runtime.py`、`hf_cache.py`。
- 已下载 TATR 表格结构模型，并转换为 ONNX。
- 已补 `table_transformer_onnx.py`，TATR ONNX 可通过本地 HF image processor 跑预测并输出统一 `TableStructureDetection`。
- 已接入 DeepDoc table media：有表格裁剪图时写入 `table_structure_model`，不可用时降级不阻断。
- PP-OCRv5 safetensors 不再作为项目资源保留；OCR 改用 HuggingFace 上现成 ONNX 版 `monkt/paddleocr-onnx`。
- 已改用 HuggingFace 上现成 ONNX 版 `monkt/paddleocr-onnx`，下载到 `app/deepdoc/resources/models/hf_onnx/ocr_pipeline__paddleocr_onnx__monkt__paddleocr-onnx/`，通过 `SmallModelRuntime.load()` 走本地 ONNXRuntime。
- Runtime 已按 CPU 可行性收口：`cpu_feasible: false` 或本地模型超过 500 MB 时不会加载/下载，返回 `cpu_inference_not_supported` 或 `model_too_large_for_cpu`。
- `paddleocr_preprocess_onnx.py` 已接入文档方向、文本行方向、UVDoc 去畸变 ONNX 推理；DeepDoc media metadata 会写入真实 `document_image_profile.models`。
- `microsoft/table-transformer-detection` 已尝试转换；当前环境缺 `timm`，按“不新增依赖、不保留不可运行权重”处理，未保留 safetensors/bin，也不进入默认执行链。
- DeepDoc 原生 OCR 已修复 CPU/ORT provider 误判：当 `torch.cuda` 可用但 `onnxruntime` 没有 `CUDAExecutionProvider` 时，自动回落 CPU，避免 `gpu:0` arena shrink 报错。
- DeepDoc 原生资源路径已收敛到 `app/deepdoc/resources/models/*`，避免运行时重复下载到 `app/resources/data_parser/qieci`。
- GPU 策略已收敛为“默认 CPU、显式开启 GPU”：DeepDoc 原生 ONNX 和 `SmallModelRuntime` 默认只选 `CPUExecutionProvider`，避免小收益带来额外复杂性；需要压测 GPU 时设置 `DEEPDOC_ONNX_USE_GPU=1`（SmallModelRuntime 也支持 `PARSING_SMALL_MODELS_USE_GPU=1`），CUDA session 初始化失败仍会自动 CPU fallback。

新增 HuggingFace ONNX 模型：

| 任务 | 模型 ID | 文件 |
|---|---|---|
| OCR detection | `monkt_paddleocr_v5_det_onnx` | `detection/v5/det.onnx` |
| 中文 OCR recognition | `monkt_paddleocr_chinese_rec_onnx` | `languages/chinese/rec.onnx` + `dict.txt` |
| 文档方向 | `monkt_pp_lcnet_doc_ori_onnx` | `preprocessing/doc-orientation/PP-LCNet_x1_0_doc_ori.onnx` |
| 文本行方向 | `monkt_pp_lcnet_textline_ori_onnx` | `preprocessing/textline-orientation/PP-LCNet_x1_0_textline_ori.onnx` |
| 文档去畸变 | `monkt_uvdoc_onnx` | `preprocessing/doc-unwarping/UVDoc.onnx` |

### 1.2 表格结构化与 TAG

目标：PDF 表格不能只停在 Markdown 文本里，必须进入现有 Table Store / TAG 链路。

| 必做项 | 落点 | 验收 |
|---|---|---|
| 表格 cell schema | `app/parsing/enrich/table_cell_schema.py` | 输出行列、表头、cell bbox/source |
| 表格标准对象 | `app/parsing/enrich/table_canonical.py` | 输出 `TableExtraction` |
| 小模型/TSR adapter | `app/parsing/enrich/table_structure_adapter.py` | 把检测框/TSR 输出归一到 `TableExtraction` |
| Markdown/HTML/CSV | `app/parsing/enrich/table_renderers.py` | 同一表支持三种输出 |
| 跨页表合并 | `app/parsing/enrich/cross_page_table_linker.py` | 相邻续表合并，不破坏单页表 |
| TAG 写入增强 | `processor.py::_import_parsed_markdown_tables_to_store()` | 写入 page/bbox/shape/source_id 等 metadata |

当前状态：

- DeepDoc media table 已标记为 table，并生成 cell-level `table_extraction`。
- Markdown/HTML/CSV 三输出已进入 metadata。
- parsed table sidecar 已兼容 `element_kind=table`，可复用现有 Table Store / TAG。
- 跨页表 linker 已接入 DeepDoc parser。
- TATR row/column 检测已可转为空 cell 表格结构，随后通过 OCR line bbox 绑定回 cell；即使 DeepDoc media payload 不是 Markdown 表格，也能在有结构检测时生成 `table_extraction`。

### 1.3 文档噪声与去水印

目标：去掉污染 OCR/Markdown 的水印、页眉页脚、导出工具标识和重复噪声，不输出“去水印文件”。

| 必做项 | 落点 | 验收 |
|---|---|---|
| 文本水印检测 | `watermark_detector.py` | 重复水印不进 Markdown |
| 水印抑制 | `watermark_suppressor.py` | OCR 临时图可 mask，原文件不改 |
| 文档噪声规则 | `document_noise_rules.py` | 微信/PDF 导出噪声可清理 |
| 页眉页脚 | `header_footer_remover.py` | 跨页重复页眉页脚删除，正文不误删 |
| 误删 fixture | tests | 表头重复、章节标题重复、页脚页码都覆盖 |

当前状态：

- 已新增 noise rules 与 watermark suppressor。
- 已接入 preprocess watermark backend 的 heuristic fallback。
- 已有文本水印、微信导出噪声、页眉页脚误删保护测试。

### 1.4 版面顺序、目录和题注

目标：DeepDoc 输出的 block 要能稳定承接定位、切块和表格 TAG。

| 必做项 | 落点 | 验收 |
|---|---|---|
| 统一 block schema | `app/parsing/utils/block_schema.py` | block 包含 kind/page/bbox/text/confidence/source |
| 阅读顺序修复 | `reading_order_fixer.py` | 双栏/三栏可重排，单栏不误伤 |
| section tree | `section_tree.py` | 中文“一、/（一）”和英文 Chapter/Section 写入 `header_path` |
| caption linker | `caption_linker.py` | 图/表题注按同页几何距离绑定 |

当前状态：

- DeepDoc text/media 已输出 `derived_elements` 和 source metadata。
- reading order 已支持双栏/三栏。
- section tree 已写入 `header_path`。
- caption linker 已按同页几何距离绑定 media/table metadata。

### 1.5 OCR 置信度与解析质量门禁

目标：把低置信 OCR、结构不稳、噪声删除风险写入后端 metadata，供入库/治理分流使用。

| 必做项 | 落点 | 验收 |
|---|---|---|
| OCR 汇总 | `processor.py` | 输出 `doc_metadata.ocr.avg_confidence/low_confidence_spans` |
| 质量 schema | `parse_quality_schema.py` | 固定字段，不散落 dict |
| 内部门禁 | `parse_quality_gate.py` | 写 metadata，不做人工 UI |
| 前端只读展示 | `/parsing` 当前详情 | 只展示真实 gate 结果，不 mock |

当前状态：

- block confidence 已提升到统一 schema。
- processor 已汇总 OCR 质量。
- parse quality gate 已接入 processor 与 parsing workspace。
- 前端解析详情读取真实 `parse_quality_gate` flags。

### 1.6 DeepDoc 二开算法追加项

目标：在已有 DeepDoc ONNX 基础上补算法能力，不继续堆通用模型服务。

| 算法 | 落点 | 当前状态 |
|---|---|---|
| 表格自动旋转 | `table_image_algorithms.select_table_rotation()` | 通过 0/90/180/270 OCR confidence 选最佳方向，写入 `table_image_algorithms.rotation` |
| cell OCR 绑定 | `bind_ocr_lines_to_table_cells()` | OCR line bbox 按重叠绑定到 cell，写入 `cell_ocr_binding`；无 bbox 时可先生成均匀 cell bbox |
| 有线/无线表分流 | `classify_table_grid_type()` | 基于图像横/竖线密度输出 `wired/wireless`，写入 `table_image_algorithms.grid` |
| 公式区域 | `document_region_algorithms.detect_formula_regions()` | DeepDoc `equation/formula` block 写入 `formula_regions`，不接通用 VLM |
| 图表区域 | `detect_chart_regions()` | 对 image/figure 的图表 caption/hint 写入 `chart_regions`，先做区域占位和 citation |
| 扫描预处理画像 | `profile_document_image_with_models()` | 调用 PP-LCNet 文档方向、文本行方向和 UVDoc ONNX，输出 orientation/textline/unwarp metadata |

当前状态：

- 已接入 DeepDoc parser：table media 自动写入 rotation/grid/cell OCR/profile metadata。
- text document 已写入公式区域 metadata。
- image/chart media 已写入 chart region 和 document image profile。
- 文档方向、文本行方向、UVDoc 为真实 ONNXRuntime CPU 推理；单模型均小于 500 MB。
- 这些能力均为后端 metadata 和结构化输出，不新增产品化页面。

### 1.7 大模型/不可 CPU 过滤规则

| 规则 | 处理 |
|---|---|
| 单模型文件或模型目录超过 500 MB | 视为大模型，runtime 返回 `model_too_large_for_cpu` |
| manifest 标记 `cpu_feasible: false` | 不加载、不下载，runtime 返回 `cpu_inference_not_supported` |
| HF snapshot 只有 safetensors/bin 且无法转 ONNX | 不保留权重，不进入默认链路 |
| 需要新增依赖才能转换 | 先记录原因，不为转换临时引入依赖 |

---

## 2. 当前必须补的验证

执行前不再扩产品功能，先把下面验证跑完：

```bash
pytest -q \
  tests/test_parsing_small_model_runtime.py \
  tests/test_bootstrap_parsing_small_models.py \
  tests/test_paddleocr_preprocess_onnx.py \
  tests/test_table_canonical_extraction.py \
  tests/test_table_structure_adapter.py \
  tests/test_cross_page_table_linker.py \
  tests/test_deepdoc_parser_blocks.py \
  tests/test_header_footer_remover.py \
  tests/test_reading_order_fixer.py \
  tests/test_watermark_detector.py \
  tests/test_document_noise_rules.py \
  tests/test_watermark_suppressor.py \
  tests/test_preprocess_watermark_heuristic.py \
  tests/test_section_tree_caption_linker.py \
  tests/test_parse_quality_gate.py \
  tests/test_processor_ocr_quality_summary.py \
  tests/test_parsing_quality_gate.py \
  tests/test_processor_parsed_table_store.py \
  tests/test_table_store_markdown_import.py \
  tests/test_dataset_tables_endpoints.py

python -m ruff check \
  app/parsing/models \
  app/parsing/enrich \
  app/parsing/preprocess/watermark.py \
  app/parsing/processors/parse_quality_gate.py \
  app/parsing/processors/parse_quality_schema.py \
  app/parsing/parsers/deepdoc_parser.py \
  app/parsing/processors/processor.py \
  app/parsing/utils/block_schema.py \
  app/api/v1/parsing.py \
  scripts/bootstrap_parsing_small_models.py

pnpm --dir web exec vitest run \
  components/parsing/parsing-active-file-pane.source.test.ts \
  components/parsing/parsing-source-guards.source.test.ts

pnpm --dir web exec tsc --noEmit --pretty false
```

当前验证记录（2026-05-19）：

| 验证 | 结果 |
|---|---|
| 后端目标测试 | `73 passed in 24.61s` |
| Ruff | `All checks passed!` |
| GPU/CPU provider 策略 | 已覆盖默认 CPU、显式 CUDA、CUDA 初始化失败回落 CPU、无 CUDA 时 CPU |
| Parsing 前端 vitest | `8 passed` |
| Web TypeScript | `pnpm --dir web exec tsc --noEmit --pretty false` 通过 |
| TATR ONNX smoke | 本地 HF image processor + ONNXRuntime 可执行；合成空白表格无高置信 detection，链路不报错 |
| PaddleOCR 预处理 ONNX smoke | 文档方向、文本行方向、UVDoc 均可 CPU ONNXRuntime 推理 |
| 模型大小清理 | 无 `*.safetensors`/`*.bin`，无单文件超过 500 MB |
| DeepDoc 真实通道 smoke | `app/deepdoc/data/picture.pdf` 解析通过：52.088s、5 docs、1 table、TATR detections 8、cell OCR 绑定 3、image profile 4 |
| 资源副作用检查 | DeepDoc smoke 后未创建 `app/resources` 重复模型目录 |
| GPU provider 选择 | 单测覆盖默认 CPU、显式 CUDA、无 CUDA 时 CPU、CUDA session 失败时 CPU fallback |
| 业务 PDF 耗时观察 | 6 MB / 49 页上传 PDF：CPU 614.764s；GPU 全 ONNX 553.350s；页级并发 2 为 536.718s。收益有限，默认回到 CPU/串行，DeepDoc 适合作为抽样/复杂版面通道，不适合默认全量快速通道 |

---

## 3. 完成判定

只有同时满足下面条件，才算完成：

| 条件 | 判定 |
|---|---|
| 不依赖外网 | 默认本地 ONNX/DeepDoc 路线可跑 |
| 小模型真实存在 | HF snapshot / ONNX 文件在项目资源目录内 |
| 表格进 TAG | PDF 表格能进入 Table Store，并保留 source metadata |
| 噪声不污染 | 水印、导出工具标识、页眉页脚不进入最终 Markdown |
| 不误删正文 | false-positive fixtures 通过 |
| OCR 可诊断 | OCR confidence 和低置信 span 可落 metadata |
| 前后端真实 | 前端只读后端真实 `parse_quality_gate`，不新增 mock 展示 |
| 回归通过 | pytest、ruff、vitest、tsc 通过 |
