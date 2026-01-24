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
  - 导出 chunks.json / chunks.csv / chunks.md
  - 复制 chunk-preview 的 cURL 示例

## API 调用（用于脚本化调参）

切块预览接口：

- `POST /api/v1/documents/chunk-preview`
  - Query: `chunk_size`, `chunk_overlap`
  - Form: `file`, `parser_backend`, `chunk_strategy`, `pipeline`（可选，JSON string）

示例（请替换 `X-User-ID` 与文件路径）：

```bash
curl -X POST "http://localhost:8000/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200" \
  -H "X-User-ID: demo" \
  -F "file=@/path/to/your-file" \
  -F "parser_backend=auto" \
  -F "chunk_strategy=langchain_recursive"
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
