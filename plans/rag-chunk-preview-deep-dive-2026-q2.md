# `/chunk-preview` 切块预览前端调研 — 现状评估 + 自研深化

## Context

**触发场景**:用户从 `/chunk-preview` 出发,要求对**切块预览前端**做全面调研,**约束:不引大包优先自研**。这是 RAG 入库的"第二站":parser 输出原文 → chunking 切块 → embedding 入库。前端是用户调试切块策略的核心 UI。后端已有 70+ chunking 策略,IBM blueprint 已规划"300/50 + 回页合并"对照,Vectara 反直觉(fixed-size 优于 semantic),Anthropic Contextual 提升 35%——**但前端缺这些洞察的落地形态**。

**问题**:`/chunk-preview` 已具规模(`web/components/chunk-preview/` ~13675 行!chunk-list 1631 / context 1246 / top-bar 956 / original-preview 664 / monaco 440 / pdf-preview 318 + workbench scaffold + 多个 source.test),覆盖原文-切块对照、Monaco 编辑器、PDF dock、覆盖率热力图(coverage-heatmap-mini)、语义质量热力图(semantic-quality-heatmap-mini),**但缺**:① 多策略并排对比(Token/Sentence/Recursive/Semantic/Markdown-aware)② chunking_grid 量化打分(对齐 Vectara NAACL 2025)③ Context Cliff @2500 监测 ④ Anthropic Contextual 惰性预览 ⑤ Parent-Child 连坐召回可视化(对齐 PoC-to-MVP)⑥ 切块边界 drag-edit ⑦ chunk 元数据三字段(summary/keywords/questions)预生成预览 ⑧ Min chunk size floor 告警。本调研对标 LlamaIndex / LangChain TextSplitter / Unstructured chunking,**全部自研**。

---

## 1. 现状盘点

### 1.1 文件清单(~13675 行)

| 文件 | 行数 | 角色 |
|---|---|---|
| `chunk-list.tsx` | **1631** | 切块列表(主视图) |
| `context.tsx` | 1246 | 共享 context state |
| `top-bar.tsx` | 956 | 顶部工具栏 |
| `original-preview.tsx` | 664 | 原文预览 |
| `original-preview-monaco.tsx` | 440 | Monaco 编辑器版 |
| `pdf-preview.tsx` | 318 | PDF dock |
| `semantic-quality-heatmap-mini.tsx` | 139 | 语义质量热力图 |
| `coverage-heatmap-mini.tsx` | 76 | 覆盖率热力图 |
| `workbench/index.tsx` | 58 | 工作台壳 |
| `pdf-dock.ts` | 30 | PDF 停靠逻辑 |
| `constants.ts` / `types.ts` | - | 配置 |

### 1.2 已具备能力

- ✅ **原文-切块双栏对照**(Monaco + PDF + 通用文本三态)
- ✅ **覆盖率热力图**(每 chunk 在原文位置)
- ✅ **语义质量热力图**(chunk 间的语义连贯)
- ✅ **PDF dock**(锚定原文位置)
- ✅ **density 可调**(sidebar-client.density.source.test 暗示)
- ✅ **mobile dialog 适配**

### 1.3 8 大缺口

1. ❌ **多策略并排对比**(Token / Recursive / Semantic / Markdown-aware / Late Chunking)
2. ❌ **chunking_grid 量化打分**(对齐 Vectara NAACL 2025 / FloTorch 54% 陷阱)
3. ❌ **Context Cliff @2500 监测**(chunk 长度超过 2500 检索质量断崖)
4. ❌ **Anthropic Contextual 预览**(每 chunk 加上下文摘要)
5. ❌ **Parent-Child 连坐召回可视化**(对齐 PoC-to-MVP)
6. ❌ **chunk 边界拖拽编辑**(用户手动调整切点)
7. ❌ **元数据三字段预生成**(summary / keywords / questions)
8. ❌ **Min chunk size floor 告警**(<100 字符的 chunk 红色标记)

---

## 2. 业界对标(参考 / 排除)

| 工具 | 借鉴点 | 排除原因 |
|---|---|---|
| **LlamaIndex Chunk Visualizer** | 多策略对照 | 偏研究 demo |
| **LangChain TextSplitter UI** | 简单 | 引入 langchain 依赖太重 |
| **Unstructured.io UI** | element-aware | 商业 |
| **Anthropic Contextual** (论文) | +35% recall | 自研 prompt 即可 |
| **Vectara NAACL 2025** | fixed-size 反直觉结论 | benchmark 自建 |
| **Jina Late Chunking** | 论文 | 自研 |
| **RAPTOR** (ICLR'24) | 树形 chunk | 算法自研 |

**结论**:全部自研,只引入算法思路。

---

## 3. P0 落地任务(2-3 周)

### 3.1 多策略并排对比(~600 行)

**新建** `web/components/chunk-preview/components/strategy-comparison-grid.tsx`:
- 4-5 列 grid,同文档跑不同 chunking 策略:
  - `token_300_overlap_50`(IBM 蓝图基准)
  - `sentence_aware`
  - `recursive_markdown`
  - `semantic_bge_m3`(已有 BGE-M3)
  - `late_chunking`(Jina 思路)
- 每列显示:chunk 数 / 平均长度 / 长度分布柱状 / 语义连贯热力
- 点击某列 → 切到 main view 看详细
- **后端**:`POST /api/v1/chunking/compare`(新增,接收 doc_id + 策略列表)

### 3.2 chunking_grid 量化打分(~400 行)

**新建** `web/components/chunk-preview/components/chunking-grid-scores.tsx`:
- 6 维评分(对齐 Vectara NAACL):
  - Top-K 召回 / 上下文完整度 / 长度分布 / 语义连贯 / 边界自然度 / 成本(token 数)
- 雷达图 + 6 个 metric tile
- 后端:`app/rag/evaluation/chunking_quality_score.py`(新)

### 3.3 Context Cliff 监测(~200 行)

**新建** `web/components/chunk-preview/components/context-cliff-warning.tsx`:
- chunk 长度直方图(已有热力图扩展)
- > 2500 字符的 chunk 红色高亮
- 顶部 banner:"⚠️ N 个 chunk 超过 2500 字符,可能触发 Context Cliff"
- 推荐切分策略

### 3.4 Anthropic Contextual 惰性预览(~350 行)

**新建** `web/components/chunk-preview/components/contextual-followup-preview.tsx`:
- 选中某 chunk → 后台调 LLM 生成"上下文摘要前缀"
- 在 chunk 头展示:`[Context] 本段来自 X 文档第 Y 章...`
- 按需触发(不强制全量)
- 后端:已有 `app/rag/chunking/contextual_enrichment.py` 复用

### 3.5 Parent-Child 连坐可视化(~300 行)

**修改** `chunk-list.tsx`(1631 行):
- 选中 chunk → 高亮该文档**所有同源 chunks**(parent-child 关系)
- 边连接线显示同文档 chunk_index 顺序
- 对齐 PoC-to-MVP plan 的"连坐召回"

### 3.6 chunk 边界 drag-edit(~400 行)

**修改** `chunk-list.tsx` + 新建 `web/lib/chunk-boundary-editor.ts`:
- chunk 边界处加可拖拽的"分隔条"
- 拖动 → 实时重切并预览
- 保存 → 写入 dataset metadata `manual_chunk_overrides`
- 后端:`POST /api/v1/chunks/{doc_id}/manual_split`

### 3.7 元数据三字段预生成预览(~250 行)

**新建** `web/components/chunk-preview/components/metadata-preview.tsx`:
- 选中 chunk → 触发 LLM 生成 `summary` + `keywords` + `questions`(对齐 PoC-to-MVP)
- 显示在 chunk 头作为元数据徽标
- 与 `auto-tagging-services` plan LLM tagger 协同

### 3.8 Min chunk size floor 告警(~150 行)

**新建** `web/components/chunk-preview/components/min-size-warning.tsx`:
- < 100 字符 chunk 红色标记
- 列表底部:`⚠️ N 个 chunk 过短,可能影响检索`
- 推荐合并 / 调大 chunk_size

---

## 4. P1 任务(1 月)

### 4.1 chunking 历史时序对比
- 不同时间切块结果对比(对齐 snapshot plan content-addressed)
- 检测 chunking 算法升级回归

### 4.2 chunk-level ACL 闭环可视化
- chunk 上显示文档级 ACL 标签(对齐 deep-research P1)

### 4.3 Token 成本预估
- 切块完成后预估 embedding + LLM contextual 总 tokens

### 4.4 RAPTOR 树形 chunk 可视化
- 树状结构(已有 force-graph 可复用)

---

## 5. 关键文件

**修改**:
- `chunk-list.tsx`(1631,加 parent-child + drag-edit)
- `context.tsx`(1246,扩 state)
- `top-bar.tsx`(956,加策略对比按钮)

**新建**:
- `web/components/chunk-preview/components/strategy-comparison-grid.tsx`(P0)
- `web/components/chunk-preview/components/chunking-grid-scores.tsx`(P0)
- `web/components/chunk-preview/components/context-cliff-warning.tsx`(P0)
- `web/components/chunk-preview/components/contextual-followup-preview.tsx`(P0)
- `web/components/chunk-preview/components/metadata-preview.tsx`(P0)
- `web/components/chunk-preview/components/min-size-warning.tsx`(P0)
- `web/lib/chunk-boundary-editor.ts`(P0)
- `app/rag/evaluation/chunking_quality_score.py`(P0)

**复用**:
- 已有 70+ chunking 策略 / 17700 行
- `app/rag/chunking/contextual_enrichment.py`(已有,无 LLM 版本)
- BGE-M3 算 semantic coherence

---

## 6. 验证

1. 多策略对比:同一 doc 跑 5 策略,chunk 数差异显示
2. quality score:Vectara 样例分数与 paper 同档
3. Context Cliff:>2500 chunk 红色 + banner 提示
4. drag-edit:拖动分隔条 → chunk 实时变化
5. metadata 预览:LLM 在 5s 内出 summary
6. `pnpm verify` + 现有 source.test.ts 全过

---

## 7. 与已有调研协同

- **`rag-parsing-chunking-deep-dive`**:6 维 chunking_quality 对齐 Vectara
- **`rag-ibm-champion-blueprint`**:300/50 是默认对照基准
- **`rag-poc-to-mvp-delivery`**:Parent-Child 连坐 + 三字段元数据共享
- **`rag-context-expansion-rerank`**:Contextual followup 已有 284 行,前端复用
- **`rag-auto-tagging-services`**:metadata 三字段 LLM 是 tagger 的子集
- **`rag-visualization-deep-dive`**:chunking 时序差异图与 P1 时序协同

---

## 8. 关键洞察

1. **13675 行已是业界一流**,但深度浅:**对比+量化+联动**才是差异化
2. **不引大包**:LlamaIndex/LangChain 全套都不要,自研 8 个组件 ~2400 行
3. **chunking 是 RAG 质量上限**:Vectara 反直觉、FloTorch 54% 陷阱说明业界都还在摸索
4. **Context Cliff 监测是真护城河**:让用户在切块时就看到风险
5. **drag-edit 是企业刚需**:解析+chunking 不可能 100% 准,人工修订兜底
6. **metadata 三字段(summary/keywords/questions)**是 PoC-to-MVP 的关键差异化

---

## 9. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- Chunk Preview 已具备策略预览、语义差异对比、auto tune、inspector、语义质量热力、覆盖热力、检索模拟、批量过滤/跳过和 chunk → 文档查看器联动。
- 当前能力已经能支撑“发现切块风险 → 对比策略 → 调整参数 → 回看原文证据”的闭环。
- 对应 source tests 覆盖 compare dialog、auto tune dialog、inspector、semantic quality UI、retrieval search/rerank 和 document-viewer deep link。

明确不做:
- 暂不新增独立 `/chunking/compare` 后端、拖拽边界编辑器、RAPTOR 树形专页或外部 contextual chunking 产品形态。
- 暂不把本文列出的所有 P1 图表做成单独页面;后续只有真实客户切块误差证明必要时再拆 ticket。

Directive: 后续切块能力优先围绕真实检索失败样本补小闭环,不要再按本文档逐项扩展组件。
