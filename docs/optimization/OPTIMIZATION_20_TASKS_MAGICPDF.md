# MimirQ：20 个优化任务（MagicPDF 支持）

> 目标：在不影响现有解析链路的前提下，引入可选的 `magic-pdf` 高级 PDF 解析后端，并补齐配置、可观测性与前端接入。

## 已完成清单（20/20）

1. ✅ 增加解析器后端别名归一化（`magic-pdf/magic_pdf → magicpdf` 等）（`app/parsing/backends.py`）
2. ✅ 后端配置新增 MagicPDF 相关参数（开关/CLI/方法/语言/超时/产物保留）（`app/core/config.py`）
3. ✅ 更新后端 `docker/.env.example`：补充 MagicPDF 配置项与说明（`docker/.env.example`）
4. ✅ 新增 MagicPDF 解析器适配层：通过 `magic-pdf` CLI 产出 Markdown（`app/parsing/parsers/magic_pdf_parser.py`）
5. ✅ ParserFactory 接入 `magicpdf` 后端并支持选择/自动回退（`app/parsing/factory.py`）
6. ✅ PDF 分流策略纳入 MagicPDF：在扫描件/低质量场景可作为自动选择候选（`app/parsing/routing.py`）
7. ✅ 解析结果统一补齐 `parser_source` 元数据，减少前后端字段不一致（`app/parsing/factory.py`）
8. ✅ Inline 图片上传阶段支持 per-doc `asset_base_dir`（便于 MagicPDF 的 `images/*` 相对路径解析）（`app/parsing/processors/processor.py`）
9. ✅ Inline 图片路径解析支持 `origin_path` 为目录（适配解析产物目录作为 base_dir）（`app/parsing/processors/processor.py`）
10. ✅ Ingest 流程跟踪解析产物目录（用于后续清理）（`app/parsing/processors/processor.py`）
11. ✅ Ingest 完成后 best-effort 清理 `.magicpdf/` 解析产物（可通过开关保留）（`app/parsing/processors/processor.py`、`app/core/config.py`）
12. ✅ `/documents/preview` 预览接口 best-effort 清理 MagicPDF 产物目录，避免临时目录堆积（`app/api/v1/documents.py`）
13. ✅ Settings API 增加 `magicpdf_enabled` 功能开关字段（`app/api/v1/settings.py`）
14. ✅ Settings API 增加 `magicpdf` 配置对象（method/lang/timeout/keep_artifacts 等）（`app/api/v1/settings.py`）
15. ✅ Settings 更新：写入 `.env` 后 best-effort 同步到内存 settings（支持 MagicPDF 配置热更新）（`app/api/v1/settings.py`）
16. ✅ Settings 状态接口补齐解析器可用性输出（含 magicpdf CLI 检测）（`app/api/v1/settings.py`）
17. ✅ 增加 `scripts/check_parsers.py`：快速查看解析器可用性（`scripts/check_parsers.py`）
18. ✅ Makefile 优化：统一使用 `python3`，新增 `make parser-status`（`Makefile`）
19. ✅ 文档补齐：MagicPDF 指南，并在根 README 链接（`docs/guides/magicpdf_guide.md`、`README.md`）
20. ✅ 增加单测：覆盖 MagicPDF 归一化/路由/工厂解析后端选择（`tests/test_parsing_routing.py`、`tests/test_parser_backend_normalization.py`、`tests/test_parser_factory_magicpdf.py`）

