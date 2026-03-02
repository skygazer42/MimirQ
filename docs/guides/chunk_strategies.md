# 切块策略速查（Chunk Strategies）

本页用于快速选型：当你不知道该用哪种切块策略时，先从这里开始，再到「切块预览」页面做可视化验证。

## 快速推荐

- **通用文档（Markdown/说明文/博客/制度）**：`auto` 或 `langchain_recursive`
  - `chunk_size`：600-1500（chars）
  - `chunk_overlap`：10-25%
- **PDF（版式/双栏，且解析结果包含位置标签 @@page\tl\tr\tt\tb##）**：`pdf_layout`
  - 目标：按“版面块”聚合切片，保留 bbox/columns 元数据用于 PDF 高亮与可解释性。
  - 建议：配合 `parser_backend=docling`（表格/版式优先）或 DeepDoc/MinerU 等能输出位置标签的解析器。
- **结构化 Markdown（标题层级清晰）**：`markdown_outline` 或 `markdown_header`
  - 目标：优先按标题边界切分，并保留 `header_path` / `outline_path`
- **FAQ / Q&A**：`qa_pairs` 或 `qa_markdown`
  - 目标：保证每组问答不被拆散
- **合同/法律/制度条款**：`laws_structured`
  - 目标：按条款结构切分，减少跨条款混淆
- **会议纪要/访谈/对话**：`transcript` / `meeting_minutes` / `chat_history`
  - 目标：尽量保留发言轮次/行动项上下文
- **代码/配置/变更**：`smart_code` / `code` / `diff_patch` / `kv_config`
  - 目标：避免在语法/块边界中间切开
- **按分隔符切分（段落/标题/---）**：`separator`
  - 目标：保留原始结构边界；对超长块使用 `separator_max_chunk_size` 兜底拆分
  - 注意：separator 策略不使用 overlap，建议设为 0（切块预览页会自动归零）。

## 什么时候用 Token 切块？

当你希望 **严格控制上下文长度**（尤其是模型上下文较小、或检索预算敏感），可以选择：

- `langchain_token`
  - `chunk_size`：256-1024（tokens）
  - `chunk_overlap`：约 10-25%

> 建议仍然使用「切块预览」检查：token 切块可能在句子中间断开；切块预览页会显示每条切片的 `tokens_est` 并按 tokens 口径做统计/筛选。

## 常见坑

- **overlap >= chunk_size**：会直接被拒绝（无意义的重叠）。
- **过小 chunk_size**：切片过碎，召回噪声上升；引用溯源也会变差。
- **过大 chunk_size**：召回命中率下降；单条 chunk 可能包含多个主题，影响精准匹配。
- **解析质量优先**：PDF/Office 先在「文档解析」与「数据治理」确认结构再调参。

## 下一步

- 进入 `/chunk-preview`：用真实文档验证切片质量、定位高亮与数量分布。
- 如果你有固定文档类型：把一套「策略 + 参数」固化为团队默认预设，减少反复试错。
