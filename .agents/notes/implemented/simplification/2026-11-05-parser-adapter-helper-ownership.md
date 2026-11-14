# Agent Note: Parser adapters keep resources and pass owned results directly

Status: implemented

## Problem

The local document adapters mix parser interfaces and resource state with rendering helpers that never read instance state. Email, XPath, position and table producers already create concrete fields, but their consumers repeat casts, empty-value defaults and shape checks. Capability discovery separately maintains the same backend-family projection in its single and list responses.

## Decision

本篇保留 TCADP 的范围由[退出 XGBoost、unstructured 和腾讯云 SDK](2026-11-06-retire-parser-ml.md)部分取代：腾讯 SDK 解析器、包装与导出退出，其他解析器资源及辅助函数归属决定继续适用。

Parser classes and the registry retain their existing interfaces and modules. BaseAdvancedParser retains its framework conversion hooks, async wrapper, logger and lazy parser ownership. Excel keeps configuration and workbook lifetime; DeepDoc keeps parser caches, the lock and SmallModelRuntime; Pandoc and MarkItDown keep CLI or converter resources and optional dependencies.

基类的同步／异步公共阶段按[解析输入与结果契约](../bug-fix/2026-11-13-parser-foundation-contracts.md)共用实现，前置步骤和重工作的位置保持。无生产注册或消费者的 Mathpix 按[未注册适配器退出](2026-11-13-retire-unregistered-mathpix-parser.md)删除，两个专属配置字段同批退出；下述早期保留清单只说明当时的源码范围，不能据此恢复该孤立模块。

Stateless HTML, PDF, Excel and DeepDoc rendering and metadata helpers are ordinary functions in their original modules. Their callers name those functions directly. The existing PDF test reference follows the relocated helper; its inputs and assertions stay the same. There is no compatibility wrapper or new helper module.

OCR response extractors and pure command, reference, partition and document builders follow the same ownership rule in their existing provider modules. Request sessions, DeepSeek thread-local connections and executor flow, ZIP/MinIO processing, MagicPDF CLI/model configuration, PDF/image lifetime and parser interfaces remain with their resource owners. Marker calls the existing Markdown response utility directly; the unused MagicPDF forwarding method is absent. Provider response shape/version guards and selection order remain explicit.

GLM-OCR、olmOCR、PaddleOCR-VL 和 Qianfan-OCR 的 JSON 文本选择复用 `app.parsing.parsers.response_text.extract_markdown_from_json`，保留 `markdown`、`md`、`content`、`text`、`result` 的既有优先级与非空字符串规则。HTTP、ZIP、文件与 provider 错误政策继续由各适配器持有。

Capability discovery shares the identical backend-family dictionary projection. Single lookup keeps requested_backend first; list discovery keeps family order. Unknown lookup, tuple-to-list copies and the conditional non_pdf_extensions field keep their existing behavior.

Email body and parsed-message dictionaries declare their actual fields with TypedDict. HTML consumes DecodedText and HtmlXPathExtractResult directly. DeepDoc declares its actual seven-part section result, table result objects and media-analysis record. Only values traced to these producers, native lengths, local counters and already-normalized list levels lose repeated conversion or shape fallback. Raw SDK/HTTP data, version reflection, constructor coercion and optional provider guards retain their existing handling.

应用 DeepDoc 包装层读取当前 vendored PDF 的完整字符串 sections 及固定媒体 tuple，DOCX 的 style.name 仍可为 None；不把只在旧测试出现的另一套 private shape 当作生产版本合同。Paddle 已通过统一产物归一化入口工作，失去生产 caller 的旧归一化支链退出；DeepSeek 的线程 local、执行器与 Future 所有权和 ETL 的原始 HTTP／图像边界保持。

Requests 原生 JSON 解码已经处理编码选择，Marker／MagicPDF 不再再次手工解码并覆盖原始异常。Docling 多表识别使用真实单词边界，Pandoc 已支持的 XLS/XLSX 转成 HTML 后继续进入原转换器，不因内部 allowlist 遗漏误拒绝；CLI 模式、命令参数、超时及资源顺序保持。本次只改应用维护的包装层，app/deepdoc 上游目录按贡献指南和 Ruff 显式排除登记保留，源码哈希逐路径核对；保留不表示上游实现通过本项目风格或部署验收。

Docling 直接消费固定 LangChain SDK 的 Document metadata、content 和 id。GLM 使用归一化结果中必有的 Markdown 路径和图片数；ETL4LLM 使用已解析裁剪坐标、自有配置标志及合并／图片回退构造的数据；DeepSeek 的 Future[str] 与原生页面／图片／并发计数来自实际字符串生产者。原始 HTTP／JSON、multipart 请求、重试／超时、产物路径和文档顺序保持。音频、视频、图片、ColPali 与 MinerU 保留实际接口；Mathpix 与 TCADP 按对应退出决定处理，旧测试不构成生产消费者。

## Alternatives considered

Keeping every helper as an instance or class method preserves its old spelling, but leaves state-free transformations coupled to parser objects. All current references to the moved private helpers are local except the synchronized PDF test call, so ordinary same-module functions express their actual dependencies without adding an interface layer.

Converting entire parsers to functions would remove more classes, but factory construction, framework extension points, configuration and owned clients or locks require the parser interfaces. Replacing SDK guards based only on annotations would be smaller to write; those boundaries still accept provider and version differences, so this change consumes only already-owned results directly.

## Consequences

Resource ownership and the factory/parser contract remain explicit. Text, Markdown, encoding, metadata keys and copies, document ordering, coordinates, assets, fallback selection, exceptions and logging follow their existing paths. The capability projection has one maintenance location.

[插件合同与内部结果](2026-11-05-plugin-contract-owned-results.md)在相邻插件链中保留实际 registry 导入和迭代执行上下文，只收敛已有等价 helper 与平台已构造结果；本篇 parser 决定保持。

The source proof compares complete frozen and current ASTs with exact helper relocations and narrowly scoped expression replacements. Ruff and Python 3.11 source parsing validate the category. This static validation does not measure parsing quality on real documents. No Python tests, application imports, parser or SDK execution, model execution, network calls or services run. Closed producer and factory modules are partial read-only dependencies; their coverage is not reopened.
