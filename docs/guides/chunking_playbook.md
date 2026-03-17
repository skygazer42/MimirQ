# Chunking Playbook（切块调参与反模式）

本文是 MimirQ 的「工业化切块」操作手册：如何在不破坏 citations/溯源的前提下，把 chunking 调到可检索、可解释、可回归。

相关参考：
- Chunk Preview 页面与 API：[docs/guides/chunk_preview.md](./chunk_preview.md)
- 策略速查表：[docs/guides/chunk_strategies.md](./chunk_strategies.md)

---

## 0. 你在调什么？

切块（chunking）在 MimirQ 里不是“把文本切小点”这么简单，它直接影响：
- **召回**：chunk 太大/太碎都会降 recall 或造成冗余候选。
- **重排/融合**：重复 chunk 会稀释 TopK；过度 overlap 会浪费预算。
- **引用（citations）**：chunk 变动会导致引用粒度变化，影响回归稳定性。
- **可解释性**：能否定位回原文（start/end offsets、coverage、gaps）。
- **多模态**：图片/OCR、表格、版面解析的结构能否保留并可控（chunk_role）。

你需要的不是“看起来不错”，而是可量化、可回滚、可审计的配置。

### Hierarchy Overlay（本波新增）

这一波的 hierarchy 不是新的存储模型，也不是要求把所有文档重建成固定树数据库。
MimirQ 当前做的是 retrieval-time overlay：
- 继续复用现有 chunk / vector / BM25 / trace 体系
- 在 chunk metadata 上补稳定的 hierarchy 键，供 recall-first profile、family collapse、tree dedup、parent/sibling expansion 复用
- 不改变现有 parser backend 和主索引结构

当前约定的核心字段：
- `hierarchy_basis`：层级来源，例如 `parent_child`、`markdown_hierarchy`、`chunk_sequence`
- `hierarchy_level`：节点级别，例如 `parent`、`child`、`paragraph`、`sentence`、`chunk`
- `hierarchy_node_key`：稳定节点键
- `hierarchy_family_key`：family collapse 的主键
- `hierarchy_parent_key`：父节点键
- `hierarchy_sibling_index` / `hierarchy_prev_sibling_key` / `hierarchy_next_sibling_key`：兄弟邻接信息

family collapse key 的解析优先级：
1. `hierarchy_family_key`
2. `parent_id`
3. 其他稳定 fallback（如 parent node key / `document_id:chunk_index`）

这意味着：
- parent-child 文档可以直接按 parent family 折叠
- 普通线性 chunk 文档也能保留稳定 adjacency，后续做 sibling expansion
- 没有 hierarchy metadata 的旧数据仍能通过 fallback 逻辑工作

---

## 1. 成功标准（建议）

在一个 dataset 上确定“可用”的 chunking preset 时，建议至少满足：
- Chunk Preview 的 `coverage_ratio` 足够高（典型目标：`>= 0.98`，视策略而定）
- `gap_count` 接近 0（或明确解释：例如某些解析器会丢掉装饰性噪声行）
- `overlap_waste_ratio` 不离谱（经验：不要长期 > 30%）
- chunk 长度分布合理：`p10/p90/p95` 不要过分极端
- 生成质量上：检索结果不“跳文/跳段”，引用不重复
- 能被 **A/B 对比** 与 **回归测试** 复现（同样输入得到同样输出）

---

## 2. 推荐工作流（从粗到细）

### Step 1: 先确认 parsing 是否靠谱

不要在 parsing 很差时强行通过 chunking “修复”：
- PDF 解析如果页眉页脚混入正文、列布局错乱，任何 chunker 都会被污染。
- 对 PDF/Office，先在 `/parsing` 与 `/data-governance` 里验证文本结构与清洗效果。

### Step 2: 选策略（优先结构化）

优先级建议：
1) **结构化/领域策略**（FAQ/Q&A、会议纪要、代码 diff、手册章节、schema 等）
2) **markdown_aware / outline / transcript**（当内容结构明显且能被解析保留）
3) **langchain_recursive**（通用兜底）
4) **auto**（当你希望“尽量正确”且愿意接受策略选择的变更风险时）

> 提示：`auto` 会在不同文档类型/密度上调整 chunk_size 与策略，适合大规模数据集；但在 CI 回归时要特别注意固定输入与版本。

### Step 3: 调 chunk_size / overlap（先稳后快）

建议先用“可解释 + 不过拟合”的参数起步：
- chars 模式：`chunk_size=800~1500`，`chunk_overlap=chunk_size*0.15~0.25`
- tokens 模式：`chunk_size=256~1024`，`chunk_overlap=chunk_size*0.15~0.25`

然后用 Chunk Preview 的 A/B：
- **一次只改一个变量**（先 size 再 overlap，再 strategy_params）
- 看 `Δp95` 与 `Δcoverage_ratio`，不要只看 chunk_count

### Step 4: 看 coverage heatmap / gap / overlap

Chunk Preview 的关键检查点：
- Sidebar 的 coverage cards（`coverage_ratio/gap_count/largest_gap`）
- 原文面板的 **coverage heatmap**（快速看“有没有明显空洞/过密 overlap”）
- Chunk List 的 filters：`GAP / OVR / SHORT / DUP`

> 经验：如果 `coverage_ratio` 低但你“看起来没有缺字”，通常是 offsets rebasing / page_index / parser position tags 链路不一致导致，需要优先修 ingest/preview 的 offsets，而不是调 chunk_size。

### Step 5: 多模态与结构化资产的处理（别混在一起）

推荐做法：
- 图片 chunk 与 OCR chunk 需要显式可区分（例如 `metadata.chunk_role=image|ocr`）。
- OCR 重复（页眉/水印）要做去重（避免 TopK 被噪声占满）。
- 表格如果走 NL2SQL/TAG 注入，要注意 citations 的可读性与稳定性。

### Step 6: 保存 preset（并做治理）

把“可用配置”固化成 preset，避免每次手动调参：
- 以 dataset 为单位保存（dataset-scoped preset）
- 用 A/B 对比与导出报告作为审批/评审材料
- 仅允许有编辑权限的成员修改 dataset preset（避免意外改坏整库）

---

## 3. 回归套件（不要只靠感觉）

MimirQ 提供 deterministic chunking regression fixtures（golden fixtures）：
- 输入：`tests/fixtures/chunking_regression/*`
- Case 定义：`tests/fixtures/chunking_regression/cases.json`
- 期望输出：`tests/fixtures/chunking_regression/expected.json`
- 测试：`pytest -q tests/test_chunking_regression_fixtures.py`

当你**有意**修改 chunker 行为时：
1) 先跑全量测试 `make test`
2) 明确说明变化原因（为什么更好）
3) 更新 golden 期望（并在 PR/commit message 里说明）

---

## 4. 常见反模式（Anti-Patterns）

1) **只看 chunk_count，不看覆盖率与重复**
   - chunk_count 下降不代表更好，可能是漏了内容（coverage 下降）或 chunk 过大（p95 飙升）。

2) **overlap 设得太大**
   - 结果：overlap_waste_ratio 上升、嵌入成本上升、TopK 更容易被重复段落占满。

3) **把“结构丢失”的问题当作 chunker 的锅**
   - PDF 两列错乱、页眉页脚混入正文：优先修 parsing/governance。

4) **parent-child 的 parent_id 不稳定**
   - 结果：回归难做、对比难做、缓存难做。
   - 正确：parent/child 关系应可复现（至少在同输入同版本下稳定）。

4.1) **把 hierarchy overlay 当成新主索引**
   - 结果：工程面会不必要膨胀，parser / index / retrieval / UI 一起重构，收益不成比例。
   - 正确：优先把 hierarchy 当作 metadata contract，用于 recall control、trace 和 explain。

5) **把 OCR 噪声当正文**
   - 水印/页眉页脚 OCR 重复会让检索看起来“有很多证据”，但全是噪声。

6) **切块跨章节边界**
   - 如果 chunker 能提供 `header_path`，检索邻居扩展/拼接应尽量不跨 section。

7) **在未启用回归前频繁改策略**
   - 没有 regression gate 时，任何“看起来更好”的改动都可能在另一个数据集上变坏。

---

## 5. Troubleshooting 速查

- `coverage_ratio < 0.98`：
  - 检查 chunk preview offsets 是否按 joined-text rebasing（page_index/start_char）一致。
  - 检查 parser 是否输出 position tags（PDF 高亮链路）。

- `gap_count > 0` 且 gaps 很大：
  - 常见原因：解析器丢行 / governance 去噪过强 / separator 配置错误（separator 被当作 content 丢弃）。

- `duplicate_count` 高：
  - 常见原因：文档重复页眉页脚、OCR boilerplate、多版本混入同 scope。

- 结果“跳来跳去”：
  - 可启用相邻 chunk 拼接/排序（context stitching），并关注是否跨 `header_path` 边界。
