# 切块预览（Chunk Preview）

切块预览页面用于在「入库前」快速验证切块质量：是否过碎/过长、overlap 是否合理、章节/问答结构是否被破坏，以及是否能正确定位回原文。

页面地址：`/chunk-preview`

切块策略选型速查见：[docs/guides/chunk_strategies.md](./chunk_strategies.md)。

## 推荐工作流

1) 文档解析（`/parsing`）：将 PDF/Office/网页等解析为 Markdown/纯文本（可预览解析结果）。

2) 数据治理（`/data-governance`）：对解析后的文本做清洗、去噪、去页眉页脚、语言检测等（可预览 diff）。

3) 切块预览（`/chunk-preview`）：选择解析器/切块策略/参数，预览 chunks，并确认入库。

提示：解析/治理/切块/对话页面顶部会显示「入库流程 Stepper」，可一键跳转到对应环节。

## 关键参数与建议

- `chunk_size`
  - 文本（chars）模式：常见 600-1500（视内容密度而定）。
  - token 模式：常见 256-1024（视模型上下文和检索策略而定）。
- `chunk_overlap`
  - 常见经验值：`chunk_size` 的 10-25%（过小容易断语义；过大浪费向量与检索预算）。
- `chunk_strategy`
  - 预设/结构化策略更适合：FAQ/Q&A、章节文档、合同条款、会议纪要、代码 diff 等。
  - 通用策略适合：普通长文、博客、说明文等。
- `separator`（当 `chunk_strategy=separator`）
  - 适用于：Markdown/讲稿/段落明显的长文、PPT（`---` 分隔）、按标题 `#`/`##` 切分等。
  - 关键参数：
    - `separator_preset`：预设分隔符（`paragraph|line|sentence_cn|sentence_en|markdown_hr|markdown_h1|markdown_h2|custom`）。
    - `separator`：自定义分隔符内容（仅当 `separator_preset=custom` 时生效）。
      - 支持用 `\n` / `\t` 等转义写法（前端会在发送前解析为真实字符）。
    - `keep_separator`：是否保留分隔符（附在前一块末尾），便于还原原始结构。
    - `separator_max_chunk_size`：单块最大长度（超过则会按句子/换行等边界拆成子块）；0 表示自动（`chunk_size × 3`）。
- `parent_child`?? `chunk_strategy=parent_child`?
  - Form: `child_ratio`, `min_child_size`
  - ???child chunk ????/??? parent chunk ????? multi-vector / parent-child retriever??
    - `child_size = max(chunk_size * child_ratio, min_child_size)`
    - `child_overlap = min(chunk_overlap * child_ratio, child_size // 4)`
  - Response: `params.strategy_params` ??????????????/???????
  - UI: Sidebar ?? parent-child ???Chunk List ?? Flat/Hierarchy ???? `metadata.parent_id` ???????

- `parser_backend`
  - 不同解析器会影响原文结构（尤其是 PDF/Office），建议先在「文档解析」页验证解析质量，再进行切块调参。

## 页面操作与快捷键

### 切片列表

- 悬停切片：高亮原文对应区间（原文面板开启时）。
- 点击切片：锁定选中，便于上下对比与检查。
- 键盘导航：`↑ / ↓` 或 `J / K` 选择上一/下一条，`Esc` 清除锁定。
- 快捷搜索：在列表区域按 `/` 聚焦搜索框；`G` 跳转首/尾（`Home/End` 同理）。
- 支持搜索与排序（原顺序 / 长度升序 / 长度降序）；当使用 `langchain_token` 时，长度口径会切换为 tokens。
- 支持“复制引用”：在切片卡片上复制带文件名/Chunk# /页码的 Markdown 片段，便于评审与溯源。

- ????? chunk ??? `SKIP`???????
  - `SKIP` chunk ????????Confirm/submit????? manual payload
  - chunks.* ?????? `SKIP` chunk?????????????? "Include SKIP chunks in exports"

### 原文面板

- 支持「源码/渲染」切换（渲染模式不支持高亮定位）。
- 若后端未返回原文（原文过大时会省略返回以避免传输过大）：
  - 前端会提示是否因超过阈值而省略（`original_text_max_chars`）。
  - 对于文本类文件（md/txt/json/csv 等），可尝试从本地文件读取原文用于定位。
  - 对于二进制文档（pdf/docx 等），建议在「解析/治理」阶段先缩短或清洗，再来做精确定位。

### 顶部栏

- `Ctrl/Cmd + Enter`：强制重新生成预览（忽略缓存）。
- `Ctrl/Cmd + S`：确认入库（提交 chunks）。
- 可隐藏/显示原文面板。
- 点击“指南”：打开切块指南（策略速查 / 参数建议 / 快捷键）。
- “更多操作”里支持：
  - 复制预览配置（便于复现）
  - 导出配置.json / 从文件导入配置 / 从剪贴板导入配置（JSON）
  - 导出 chunks.json / chunks.csv / chunks.md / chunks.jsonl
  - 复制手动入库 payload（用于 `POST /api/v1/documents/manual`）
  - 预览对比（A/B）：从同一文件的历史预览里选择一个基线，对比 chunk 数量/长度分布/内容重合度（估算）
  - 复制 chunk-preview 的 cURL 示例

## API 调用（用于脚本化调参）

切块预览接口：

- `POST /api/v1/documents/chunk-preview`
  - Query: `chunk_size`, `chunk_overlap`, `include_original_text`, `original_text_max_chars`, `max_chunks`, `use_parse_cache`
  - Response（新增字段，可忽略）：
    - `file_sha256`, `parse_cache_hit`, `parse_cache_age_ms`
    - `preview_duration_ms`（server_total）
    - `upload_duration_ms`, `parse_duration_ms`, `governance_duration_ms`, `chunking_duration_ms`, `stats_duration_ms`
    - `quality_gate`（pass/warn/fail + reasons）、`recommendations`
    - `stats.coverage_ratio / overlap_waste_ratio / gap_count`（用于评估 overlap 与定位覆盖）
    - 同时会返回 `Server-Timing` header（用于浏览器 devtools 性能排查）
  - Form: `file`, `parser_backend`, `chunk_strategy`, `pipeline`（可选，JSON string）

- `POST /api/v1/documents/chunk-preview/by-sha`
  - 免上传复用解析缓存（企业级调参体验：只要解析缓存还在，就可以快速 A/B）。
  - 用法：先调用一次 `/chunk-preview` 让后端缓存解析结果；拿到响应里的 `file_sha256`，再用它调用该接口。
  - Query: 同 `/chunk-preview`
  - Form: `file_sha256`, `file_type`, `filename`, `parser_backend`, `chunk_strategy`（其余同 `/chunk-preview`）

示例（请替换 `X-User-ID` 与文件路径）：

```bash
curl -X POST "http://localhost:8000/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200" \
  -H "X-User-ID: demo" \
  -F "file=@/path/to/your-file" \
  -F "parser_backend=auto" \
  -F "chunk_strategy=langchain_recursive"
```

by-sha 示例（先上传预览一次，取 `file_sha256`，再免上传调参）：

```bash
# 1) 先上传一次，拿到 file_sha256（示意：你可以用 jq 提取）
file_sha256="$(curl -s -X POST \"http://localhost:8000/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200\" \
  -H \"X-User-ID: demo\" \
  -F \"file=@/path/to/your-file\" \
  -F \"parser_backend=auto\" \
  -F \"chunk_strategy=langchain_recursive\" | jq -r .file_sha256)"

# 2) 免上传，直接复用解析缓存做 A/B 调参
curl -X POST \"http://localhost:8000/api/v1/documents/chunk-preview/by-sha?chunk_size=1200&chunk_overlap=160\" \
  -H \"X-User-ID: demo\" \
  -F \"file_sha256=${file_sha256}\" \
  -F \"file_type=pdf\" \
  -F \"filename=your-file.pdf\" \
  -F \"parser_backend=auto\" \
  -F \"chunk_strategy=langchain_recursive\"
```

separator 策略示例（按段落分隔，保留分隔符）：

```bash
curl -X POST "http://localhost:8000/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200" \
  -H "X-User-ID: demo" \
  -F "file=@/path/to/your-file" \
  -F "parser_backend=auto" \
  -F "chunk_strategy=separator" \
  -F "separator_preset=paragraph" \
  -F "keep_separator=true"
```
