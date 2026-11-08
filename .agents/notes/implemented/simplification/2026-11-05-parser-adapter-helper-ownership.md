# Agent Note: Parser adapters keep resources and pass owned results directly

Status: implemented

## Problem

The local document adapters mix parser interfaces and resource state with rendering helpers that never read instance state. Email, XPath, position and table producers already create concrete fields, but their consumers repeat casts, empty-value defaults and shape checks. Capability discovery separately maintains the same backend-family projection in its single and list responses.

## Decision

本篇保留 TCADP 的范围由[退出 XGBoost、unstructured 和腾讯云 SDK](2026-11-06-retire-parser-ml.md)部分取代：腾讯 SDK 解析器、包装与导出退出，其他解析器资源及辅助函数归属决定继续适用。

Parser classes and the registry retain their existing interfaces and modules. BaseAdvancedParser retains its framework conversion hooks, async wrapper, logger and lazy parser ownership. Excel keeps configuration and workbook lifetime; DeepDoc keeps parser caches, the lock and SmallModelRuntime; Pandoc and MarkItDown keep CLI or converter resources and optional dependencies.

Stateless HTML, PDF, Excel and DeepDoc rendering and metadata helpers are ordinary functions in their original modules. Their callers name those functions directly. The existing PDF test reference follows the relocated helper; its inputs and assertions stay the same. There is no compatibility wrapper or new helper module.

OCR response extractors and pure command, reference, partition and document builders follow the same ownership rule in their existing provider modules. Request sessions, DeepSeek thread-local connections and executor flow, ZIP/MinIO processing, MagicPDF CLI/model configuration, PDF/image lifetime and parser interfaces remain with their resource owners. Marker calls the existing Markdown response utility directly; the unused MagicPDF forwarding method is absent. Provider response shape/version guards and selection order remain explicit.

GLM-OCR、olmOCR、PaddleOCR-VL 和 Qianfan-OCR 的 JSON 文本选择复用 `app.parsing.parsers.response_text.extract_markdown_from_json`，保留 `markdown`、`md`、`content`、`text`、`result` 的既有优先级与非空字符串规则。HTTP、ZIP、文件与 provider 错误政策继续由各适配器持有。

Capability discovery shares the identical backend-family dictionary projection. Single lookup keeps requested_backend first; list discovery keeps family order. Unknown lookup, tuple-to-list copies and the conditional non_pdf_extensions field keep their existing behavior.

Email body and parsed-message dictionaries declare their actual fields with TypedDict. HTML consumes DecodedText and HtmlXPathExtractResult directly. DeepDoc declares its actual seven-part section result, table result objects and media-analysis record. Only values traced to these producers, native lengths, local counters and already-normalized list levels lose repeated conversion or shape fallback. Raw SDK/HTTP data, version reflection, constructor coercion and optional provider guards retain their existing handling.

Docling consumes Document metadata, content and id fields provided by the pinned LangChain SDK. GLM consumes the normalizer's always-present Markdown path and image count. ETL4LLM consumes already-parsed integer crop coordinates, normalized configuration flags and the metadata/string values built by its own merge and image fallback. DeepSeek declares Future[str] results submitted to its own string-producing API method and uses native page/image/concurrency counts. Raw HTTP status and JSON guards, multipart/JSON payload values, retry/timeout behavior, artifact paths and ordered document output keep their existing contracts. Audio, video, image, ColPali, Mathpix, MinerU and TCADP retain their existing complete source because their parser/framework interfaces and provider boundaries already express their responsibilities.

## Alternatives considered

Keeping every helper as an instance or class method preserves its old spelling, but leaves state-free transformations coupled to parser objects. All current references to the moved private helpers are local except the synchronized PDF test call, so ordinary same-module functions express their actual dependencies without adding an interface layer.

Converting entire parsers to functions would remove more classes, but factory construction, framework extension points, configuration and owned clients or locks require the parser interfaces. Replacing SDK guards based only on annotations would be smaller to write; those boundaries still accept provider and version differences, so this change consumes only already-owned results directly.

## Consequences

Resource ownership and the factory/parser contract remain explicit. Text, Markdown, encoding, metadata keys and copies, document ordering, coordinates, assets, fallback selection, exceptions and logging follow their existing paths. The capability projection has one maintenance location.

[插件合同与内部结果](2026-11-05-plugin-contract-owned-results.md)在相邻插件链中保留实际 registry 导入和迭代执行上下文，只收敛已有等价 helper 与平台已构造结果；本篇 parser 决定保持。

The source proof compares complete frozen and current ASTs with exact helper relocations and narrowly scoped expression replacements. Ruff and Python 3.11 source parsing validate the category. This static validation does not measure parsing quality on real documents. No Python tests, application imports, parser or SDK execution, model execution, network calls or services run. Closed producer and factory modules are partial read-only dependencies; their coverage is not reopened.
