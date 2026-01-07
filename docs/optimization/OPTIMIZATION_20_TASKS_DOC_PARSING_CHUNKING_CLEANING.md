# MimirQ：文档解析 / 文档清洗 / 文档切块 20 个深度优化任务（已执行）

> 侧重点：解析质量、清洗鲁棒性、切块可控性与可观测性（metadata/调参）。

## 已完成清单（20/20）

1. ✅ 梳理现有“解析→清洗→切块→索引”链路与关键入口（`app/parsing/processors/processor.py`）
2. ✅ 文本/Markdown 解析加入自适应编码探测（`app/parsing/utils/text.py`、`app/parsing/parsers/text_parser.py`）
3. ✅ 新增 HTML 轻量正文解析器（Readability 提取 + html-text 转纯文本）（`app/parsing/parsers/html_parser.py`）
4. ✅ 新增 CSV 结构化解析器（行级 Key-Value 输出，利于检索/切块）（`app/parsing/parsers/csv_parser.py`）
5. ✅ 新增 JSON/JSONL 结构化解析器（pretty print + 基础结构元数据）（`app/parsing/parsers/json_parser.py`）
6. ✅ MarkItDown 失败自动降级到 HTML/CSV/JSON 轻量解析（`app/parsing/factory.py`）
7. ✅ 统一解析输出元数据：强制 `source=filename`，避免泄露服务端路径（`app/parsing/factory.py`、`app/parsing/parsers/base_parser.py`）
8. ✅ normalize_text 扩展 Unicode 换行/控制符/空白归一化（`app/rag/preprocessing/normalization.py`）
9. ✅ clean_markdown 识别缩进代码块为结构行，避免“去空格/换行合并”破坏代码（`app/rag/preprocessing/cleaning.py`）
10. ✅ clean_markdown 的“重复行签名”支持中文页码尾缀（更稳去页眉/页脚）（`app/rag/preprocessing/cleaning.py`）
11. ✅ 新增 `auto` 智能切块策略（按内容自动选 markdown/json/语义/递归）（`app/rag/chunking/strategies/auto.py`）
12. ✅ TokenChunker 统一单位：把 pipeline 的“字符尺寸”折算为 token（`app/rag/chunking/strategies/token.py`）
13. ✅ CodeChunker 补齐 start/end 位置追踪（用于引用高亮与调试）（`app/rag/chunking/strategies/json_code.py`）
14. ✅ SmartCodeChunker（Python）补齐 start/end 位置追踪（`app/rag/chunking/strategies/json_code.py`）
15. ✅ RecursiveChunker 开启 `add_start_index`，补齐 start/end 位置（`app/rag/chunking/strategies/recursive.py`）
16. ✅ 修复 ragflow 默认策略解析：以“resolve 后的策略”决定是否走 ragflow 分支（`app/parsing/processors/processor.py`）
17. ✅ Pipeline capabilities 输出 `auto` 策略说明（`app/api/v1/pipeline.py`）
18. ✅ 文档入库时记录 auto 的实际选择统计（selected_counts）（`app/parsing/processors/processor.py`）
19. ✅ 增加单测覆盖：编码探测、MarkItDown 降级、auto 策略、清洗代码块保护、中文页码签名（`tests/`）
20. ✅ 补齐本说明文档，便于调参和验收（本文件）

## 使用与调参要点

- **启用 auto 切块**
  - 上传时传 `chunk_strategy=auto`，或设置 `DEFAULT_CHUNK_STRATEGY=auto`。
  - auto 会在 chunk metadata 里写入：`chunk_strategy_selected`、`chunk_strategy_auto`。
  - 文档级别会在 `documents.metadata.auto_chunking.selected_counts` 记录各策略产出的 chunk 数量。

- **TokenChunker（langchain_token）单位说明**
  - 仍通过 pipeline 的 `chunk_size/chunk_overlap` 传入，但内部会用 `≈ chars/4` 转换为 token 数。
  - chunk metadata 会写入 `chunk_size_chars/chunk_overlap_chars` 和 `chunk_size_tokens/chunk_overlap_tokens` 便于核对。

- **清洗（Governance）对代码块更安全**
  - 缩进代码块（4 空格或 tab 开头）会被视为结构行，不再参与“去噪/换行合并/空白折叠”。
  - 对 PDF 页眉页脚：重复行签名会剥离中文页码尾缀（`第3页` / `第3页/共10页`）。

## 快速自检

- 运行单测：`pytest -q`
- 预览链路：
  - `POST /api/v1/pipeline/parse-preview`
  - `POST /api/v1/pipeline/clean-preview`
  - `POST /api/v1/pipeline/chunk-preview`

