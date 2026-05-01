# 知识图谱可视化全面调研 — 现状评估 + 自研深化路线

## Context

**触发场景**:用户从 `/graph` 页面出发,要求调研 KG 可视化能力,并给出**约束清晰的接入建议**——**只采纳自研、不引入冗余大包**(Cytoscape 全套、yWorks 商业、Sigma.js+Graphology 全栈、G6/AntV、Neo4j Bloom 等大型外部生态)。这与 MimirQ 的**轻依赖、自研为主**风格一致。

**问题**:`/graph` 模块**已实现 9084 行代码**(graph-canvas 934 / graph-viewer 954 / force-graph-3d 604 / kg-diagnostics 1174 / kg-snapshots 1229 / kg-network-analysis 218 / 多个 hooks 与小组件),覆盖 2D/3D 力导向、聚类 worker、网络分析、节点/边详情、路径/连接/解释模式、上下文菜单、键盘漫游、小地图、图例、scope picker、快照对比、provenance tooltip 等,**已超越多数商业产品基础能力**。但对标业界 GraphRAG 可视化 SOTA(GraphRAG Visualizer / Plan-on-Graph / ToG agentic search / Linkurious / Memgraph Lab),仍有可深化空间——而且必须**全部自研**。本调研盘清现状、对标业界、给出**纯自研深化路线图**。

---

## 1. 现状盘点(已确认,9084 行)

### 1.1 文件清单与规模

| 文件 | 行数 | 角色 |
|---|---|---|
| `web/components/graph/kg-snapshots-page.tsx` | 1229 | KG 快照对比页 |
| `web/components/graph/kg-diagnostics-page.tsx` | 1174 | KG 诊断页 |
| `web/components/graph/graph-viewer.tsx` | 954 | 2D viewer 主体 |
| `web/app/graph/_components/graph-canvas.tsx` | 934 | 画布编排 + WebWorker |
| `web/app/graph/_components/graph-node-detail-panel.tsx` | 774 | 节点详情 + 邻居 + 来源 |
| `web/components/graph/force-graph-3d.tsx` | 604 | 3D 沉浸视图 |
| `web/app/graph/_components/graph-action-dialogs.tsx` | 370 | 编辑/删除等对话框 |
| `web/app/graph/_components/graph-page-header.tsx` | 329 | 标题/工具栏 |
| `web/app/graph/_components/graph-page-shell.tsx` | 316 | 整体壳 |
| `web/app/graph/_components/graph-link-detail-panel.tsx` | 275 | 边详情 |
| `web/app/graph/_components/graph-context-menu.tsx` | 272 | 右键菜单 |
| `web/app/graph/_components/graph-filters-popover.tsx` | 261 | 类型/谓词/置信度过滤 |
| `web/app/graph/_components/graph-scope-picker-dialog.tsx` | 234 | 范围选择 |
| `web/app/graph/_components/graph-floating-controls.tsx` | 221 | 浮动控件 |
| `web/app/graph/_components/kg-network-analysis-panel.tsx` | 218 | 网络分析(degree 等) |
| `web/components/graph/graph-minimap.tsx` | 202 | 小地图 |
| `web/components/graph/graph-loading-indicator.tsx` | 165 | 加载指示 |
| `web/components/graph/graph-legend.tsx` | 152 | 图例 |
| `web/app/graph/_components/graph-page-body.tsx` | 128 | 主体布局 |
| `web/app/graph/_components/graph-status-banners.tsx` | 105 | 状态横幅 |
| `web/app/graph/_components/graph-explainability-panel.tsx` | 65 | 可解释性面板 |
| `web/app/graph/_components/graph-search-overlay.tsx` | 46 | 搜索覆盖层 |
| 多个 use-graph-* hooks(状态/数据/筛选/解析/操作/交互) | - | 关注点分离架构 |
| `web/workers/graph-clustering.worker.ts` | - | Web Worker 聚类 |
| `web/lib/graph-parser.ts` / `graph-edge-display.ts` / `graph-provenance.ts` / `graph-clustering.ts` | - | 自研工具集 |

**合计**:9084 行 + 多个 hooks/utils/worker

### 1.2 已具备能力清单

| 类别 | 能力 | 实现位置 |
|---|---|---|
| **渲染** | 2D Canvas 力导向 | `graph-viewer.tsx`(react-force-graph-2d) |
| | 3D WebGL 力导向 | `force-graph-3d.tsx`(react-force-graph-3d / Three.js) |
| | 小地图导航 | `graph-minimap.tsx` |
| **数据源** | GraphML 文件上传 | `graph-parser.ts` |
| | 后端 KG API | `app/rag/kg/search/*` |
| | trace replay(回放) | `setTraceReplay` |
| **交互** | 节点/边详情面板 | `graph-node-detail-panel.tsx` / `graph-link-detail-panel.tsx` |
| | 右键上下文菜单 | `graph-context-menu.tsx` |
| | 键盘漫游(a11y) | `graph-keyboard-roving.ts` |
| | 路径模式(2 节点最短路径) | `interaction-modes` |
| | 连接模式(添加边) | `interaction-modes` |
| | **解释模式**(RAG 反向溯图) | `graph-explainability-panel.tsx` |
| **筛选** | 文本搜索 | `graph-search-overlay.tsx` |
| | 实体类型 / 谓词 / 置信度桶 | `graph-filters-popover.tsx` |
| **分析** | 节点中心度 / degree | `kg-network-analysis-panel.tsx` |
| | 子图聚类(Web Worker) | `graph-clustering.worker.ts` + comlink |
| **运维** | 快照对比(diff) | `kg-snapshots-page.tsx` |
| | 诊断页(质量/覆盖/孤立) | `kg-diagnostics-page.tsx` |
| | provenance tooltip | `graph-provenance.ts` |
| **范围** | scope picker(dataset/document/全局) | `graph-scope-picker-dialog.tsx` |
| **样式** | 边宽随置信度;颜色按类型;dark/light 主题 | `graph-canvas.tsx` |
| **导出** | 截图、节点子图导出 | `use-graph-page-actions.ts` |

### 1.3 已有依赖(零新增空间应优先利用)

- `react-force-graph-2d/3d` 1.29 ✅
- `three` (隐式,3d 内含)
- `comlink` (Web Worker 通信)
- `d3-force` (隐式在 force-graph 内)
- `next-themes`
- 自研 worker / parser / clustering / provenance

---

## 2. 业界 KG 可视化全景与"自研避雷"

### A. 大型图库(**全部排除**,违反"不引入大包"约束)

| 库 | 大小 | 排除原因 |
|---|---|---|
| **Cytoscape.js** + 插件 | 4-6 MB | 生态大但过重,与已有 force-graph 重叠 |
| **Sigma.js + Graphology** | 1-2 MB | 需要 Graphology 全套数据结构,迁移成本高 |
| **G6 (AntV)** | 1 MB+ | 中文社区强但与已有体系不兼容 |
| **vis-network** | 700 KB | 2024 已停止维护 |
| **yFiles for HTML** | 商业 $10k+ | 不考虑 |
| **Linkurious** / **Neo4j Bloom** | SaaS / 商业 | 不考虑 |
| **GoJS** / **mxGraph** | 商业/弃用 | 不考虑 |

### B. 小型可选库(**也建议自研**,只参考思路)

| 库 | 大小 | 评估 |
|---|---|---|
| **d3-force-layout** 单独包 | ~50KB | 已隐式在 force-graph 中 |
| **d3-hierarchy** | 30 KB | 树形布局可考虑直接抄源码片段 |
| **dagre** (DAG 布局) | 100 KB | 自实现 Sugiyama 即可 |
| **elkjs** (复杂布局) | 1 MB+ | 太重,排除 |
| **graphology-layout-forceatlas2** | 50 KB | 自实现 ForceAtlas2 算法 |
| **louvain-js** | 15 KB | **可参考算法,自实现 Louvain** |
| **leiden** 算法 | - | 论文级,自实现 |

**结论**:**全部自研**,业界库只参考算法与 API 设计。

### C. GraphRAG 可视化标杆(参考思路,不直接用)

| 工具 | 思路 | 借鉴点 |
|---|---|---|
| **Microsoft GraphRAG Visualizer** | Streamlit + 社区 + 实体子图 + LLM 摘要联动 | **社区→子图→LLM 摘要**三联动模式 |
| **LlamaIndex Property Graph Index** | 节点 metadata 驱动渲染 | metadata-aware 渲染 |
| **Plan-on-Graph (WWW'25)** | 路径搜索过程可视化 | **agentic search 步骤动画** |
| **Tree-of-Graph (ICLR'24)** | beam search 树状展开 | beam 节点展开效果 |
| **NodeGuard / GraphScope** | 大规模图实时查询 | server-side aggregation |
| **Cosmograph** | WebGL 1M 节点演示 | **GPU 算力极限** |
| **DeepGraphLab** | 图嵌入投影 | **嵌入空间 → 图视图**联动 |

### D. 业界关键算法(自实现 ROI 高的)

| 算法 | 用途 | 自实现成本 |
|---|---|---|
| **Louvain / Leiden 社区检测** | 自动聚类、社区折叠 | 200-400 行 TS |
| **ForceAtlas2** | 大图布局(优于 d3-force) | 300 行 TS |
| **Sugiyama(分层 DAG)** | 层次结构图 | 400 行 TS |
| **Dijkstra / A* 最短路径** | 路径模式 | 100 行 TS,已部分有 |
| **PageRank / HITS** | 重要性 | 50 行 TS |
| **Betweenness centrality** | 桥节点识别 | 200 行 TS |
| **Hierarchical Edge Bundling** | 边捆绑减乱 | 300 行 TS |
| **Quad-tree spatial index** | 大图 hover 命中 | 200 行 TS |
| **Semantic zoom** (LOD) | 远缩略/近详细 | 200 行 TS |
| **Focus + Context (鱼眼)** | 选区放大 | 150 行 TS |
| **Time-varying graph diff** | 快照动画过渡 | 已部分有 |

---

## 3. Gap 分析(MimirQ vs 业界 SOTA,纯自研视角)

| 维度 | 业界 SOTA | MimirQ 现状 | Gap | 优先级 |
|---|---|---|---|---|
| 大图渲染(>5k 节点) | Cosmograph WebGL | force-graph 渲染 ~2k 后掉帧 | **缺 LOD + 视口剔除** | **P0** |
| Agentic search 可视化 | Plan-on-Graph 路径动画 | 仅静态展示 | **缺 LLM 引导漫游回放** | **P0** |
| 社区折叠/展开 | GraphRAG Visualizer | 已有 worker 聚类但未折叠 | **缺折叠交互** | **P0** |
| 边捆绑 | Hierarchical Edge Bundling | 无 | 大量边时视觉混乱 | P1 |
| 语义缩放(LOD) | Cosmograph / yFiles | 无 | 缺远近不同细节 | P1 |
| 时序快照动画 | yFiles temporal | 已有快照但仅 diff 不动画 | 缺过渡动画 | P1 |
| 子图查询 mini-DSL | Cypher / GraphQL | 仅文本搜索 + 类型过滤 | 缺组合查询 | P1 |
| 鱼眼/Focus+Context | yFiles | 无 | 大图浏览不便 | P2 |
| 嵌入空间 → 图联动 | DeepGraphLab | 无(viz plan 有 UMAP 但未联动) | **协同点** | P2 |
| 图谱版本 GitOps | Memgraph | 已有 snapshot 但无 commit history | 缺版本树 | P2 |
| KG 编辑工作流 | Neo4j Bloom | 已有 connect mode 但无审批 | 缺审批 + diff stage | P2 |
| 多图对比叠加 | yFiles compare | 已有 diff 但无叠加视图 | 缺三方/N 方对比 | P3 |
| GPU 加速布局(WebGPU) | Cosmograph | 无 | 自实现成本极高 | P3 |
| 协作标注 | yFiles realtime | 无 | 多人在线 | P3 |
| 路径解释生成 | LLM-guided narrative | 已有 explain panel 但模板化 | LLM 生成路径解释 | P2 |

---

## 4. 推荐方案:四层自研深化架构

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4 — 战略层(P3,长尾自研深探)                            │
│   - WebGPU GPU 布局(自实现 ForceAtlas2 GPU 版)                 │
│   - 图谱协作标注(WebSocket + CRDT)                            │
│   - 多图叠加对比                                                │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3 — 高级交互(P2,1-2 月自研)                            │
│   - 鱼眼 / Focus+Context                                        │
│   - 嵌入空间 ↔ 图视图联动(对接 viz plan UMAP)                │
│   - LLM 路径解释生成器                                          │
│   - KG 编辑审批工作流(stage / diff / commit)                  │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2 — 性能与组合(P1,1 月自研)                            │
│   - 边捆绑(自实现 HEB 算法)                                  │
│   - 语义缩放(LOD,3-4 档细节)                                │
│   - 时序快照动画(d3-transition 风格)                         │
│   - 子图 mini-DSL(自研 100 行 parser)                          │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 — 核心补齐(P0,2-3 周自研)                            │
│   - 大图 LOD + 视口剔除(Quad-tree 空间索引)                  │
│   - **Agentic search 路径回放动画**(对齐 KG plan ToG/PoG)    │
│   - 社区折叠/展开(基于已有 clustering worker)                │
│   - Louvain 算法自实现(替代 worker 内简易聚类)               │
└──────────────────────────────────────────────────────────────────┘
```

**核心设计原则**:
1. **零新依赖**:Layer 1-3 不新增 npm 包,**全部自研在 `web/lib/graph-*` 与 `web/workers/`**
2. **复用已有基建**:react-force-graph 渲染层不替换,自研增强叠加在 canvas 之上
3. **算法自研代替库**:Louvain / ForceAtlas2 / Sugiyama / Dijkstra / HEB 都自实现 200-400 行
4. **Worker 优先**:重计算(Louvain / 路径 / centrality)走 Web Worker(comlink 已用)
5. **OTel 协同**:agentic search 回放复用可视化 plan 的 trace span,避免重复采集

---

## 5. P0 落地任务(2-3 周纯自研)

### 5.1 大图 LOD + 视口剔除(~500 行)

**新建** `web/lib/graph-quadtree.ts`:
- 自实现四叉树空间索引(参考 d3-quadtree 思路,~150 行)
- API:`insert(node) / query(rect) / nearest(point)`
- 视口外节点不参与渲染、不参与命中

**修改** `web/components/graph/graph-viewer.tsx`:
- 接入 quad-tree:每帧 query 视口内节点
- LOD 三档:
  - 远(zoom <0.3):仅渲染社区聚合点
  - 中(0.3-1.5):节点 + 主要边
  - 近(>1.5):全部细节 + 标签
- benchmark:5k 节点 60fps,1w 节点 30fps(目标)

### 5.2 Agentic Search 路径回放动画(~600 行)

**新建** `web/components/graph/agentic-replay-overlay.tsx`:
- 输入:agentic search trace JSON(对齐 KG plan 的 `agentic_beam_search.py`)
- 步骤:`step → expand from N nodes → score → prune → next step`
- 用 SVG 覆盖层(不动 force-graph 内部)在已有节点上画动画
  - 当前 frontier 节点闪烁脉冲
  - 被剪枝节点淡出
  - 选中路径粗线 + 箭头流动
- 时间轴控件:播放/暂停/逐步/速度
- **后端**:`app/rag/kg/search/agentic_beam_search.py`(KG plan 已规划)输出 trace,新增 `/api/v1/graph/agentic-replay` 拉取
- 用 `requestAnimationFrame` 自实现时间轴,不引入 GSAP/anime.js

### 5.3 社区折叠/展开(~400 行)

**修改** `web/workers/graph-clustering.worker.ts` + 新建 `web/lib/graph-louvain.ts`:
- 自实现 Louvain 算法(2008 论文,~250 行 TS,无外部依赖)
  - phase 1:节点逐个移动到使模块度增益最大的社区
  - phase 2:社区聚合为新节点,递归
- 输出每节点 `community_id`

**新建** `web/components/graph/community-collapse-controls.tsx`:
- 工具栏按钮"折叠所有社区"→ 每社区聚合为大节点(size=社区大小)
- 双击社区节点 → 展开
- 折叠节点之间用聚合边(weight=原边数总和)
- 与已有 graph-legend 协同

### 5.4 Louvain 单测(~150 行)

**新建** `web/lib/graph-louvain.test.ts`:
- 经典图(空手道俱乐部)模块度应 >0.4
- 二分图应正确分两组
- 全连通图应不分割
- 性能:1w 节点 <2 秒

---

## 6. P1 落地任务(1 月,纯自研)

### 6.1 边捆绑 (Hierarchical Edge Bundling)

**新建** `web/lib/graph-edge-bundling.ts`(~300 行):
- 实现 Holten 2006 HEB 算法(基于树/层次结构)
- 边走贝塞尔曲线,控制点向社区中心收拢
- bundling strength 参数 0-1
- 与社区折叠结合时效果最佳

**修改** `graph-viewer.tsx`:增加 `bundleEdges` 开关

### 6.2 语义缩放(LOD)细化

**新建** `web/lib/graph-lod-strategy.ts`(~200 行):
- 标签:zoom <0.5 不显示;0.5-1 仅 top-degree;>1 全部
- 边:zoom <0.3 仅高置信度(>0.8);其余渐进
- 节点形状:zoom <0.5 圆点;>0.5 形状区分类型

### 6.3 时序快照动画

**修改** `kg-snapshots-page.tsx`:
- 已有 base/target diff,扩展为时间轴
- 节点入场:fade-in + 从父节点位置出生
- 节点出场:fade-out + 收缩到 0
- 边:width 渐变
- 时间轴:HH:MM 标记,可拖拽

### 6.4 子图查询 mini-DSL

**新建** `web/lib/graph-query-dsl.ts`(~250 行):
- 简化语法:`type:Person AND degree>5 AND connected_to(type:Company)`
- 自研 tokenizer + parser(无 PEG.js / nearley 依赖,递归下降)
- 编译为节点过滤 predicate
- 集成到 search-overlay

### 6.5 网络分析扩展

**修改** `kg-network-analysis-panel.tsx`(~200 行新增):
- 自实现 PageRank(50 行,迭代 30 轮)
- 自实现 Betweenness centrality(BFS 复杂度 O(V·E),~200 行)
- top-K 列表 + 高亮节点

---

## 7. P2/P3 任务(季度计划)

### P2

- **鱼眼 / Focus+Context**:`graph-fisheye-lens.ts`(~200 行,Carpendale 1995 算法)
- **嵌入空间 ↔ 图联动**:与 viz plan 的 UMAP 散点配合,选区在散点 = 高亮在图
- **LLM 路径解释生成器**:已有 explain panel 模板化,改为调 LLM 生成自然语言"为什么这条路径"
- **KG 编辑审批工作流**:connect mode → stage → diff → commit(GitOps 风格)

### P3

- **WebGPU 布局**:`web/workers/graph-layout-webgpu.worker.ts`,自实现 ForceAtlas2 GPU 版(WGSL 着色器)
- **协作标注**:WebSocket + CRDT(自研轻量 CRDT,不引入 Yjs)
- **多图叠加对比**:N 个图重叠绘制,差异色编码
- **图谱 GitOps**:每次编辑产生 commit,可 revert / branch / merge

---

## 8. 关键文件清单

**修改**(增强,不重写):
- `web/components/graph/graph-viewer.tsx`(接 quad-tree + LOD + bundling 开关)
- `web/components/graph/graph-canvas.tsx`(同上)
- `web/components/graph/kg-snapshots-page.tsx`(时序动画)
- `web/components/graph/kg-diagnostics-page.tsx`(PageRank/Betweenness 集成)
- `web/app/graph/_components/kg-network-analysis-panel.tsx`(扩展指标)
- `web/app/graph/_components/graph-explainability-panel.tsx`(agentic 回放入口)
- `web/workers/graph-clustering.worker.ts`(集成 Louvain)
- `web/lib/graph-clustering.ts`(替换简易聚类)

**新建**(纯自研,无新依赖):
- `web/lib/graph-quadtree.ts`(P0)
- `web/lib/graph-louvain.ts`(P0)
- `web/lib/graph-edge-bundling.ts`(P1)
- `web/lib/graph-lod-strategy.ts`(P1)
- `web/lib/graph-query-dsl.ts`(P1)
- `web/lib/graph-pagerank.ts`(P1)
- `web/lib/graph-betweenness.ts`(P1)
- `web/lib/graph-fisheye-lens.ts`(P2)
- `web/components/graph/agentic-replay-overlay.tsx`(P0)
- `web/components/graph/community-collapse-controls.tsx`(P0)
- `web/components/graph/graph-time-slider.tsx`(P1)
- `web/workers/graph-pagerank.worker.ts`(P1)
- `web/workers/graph-louvain.worker.ts`(P0,大图走 worker)
- `web/workers/graph-layout-webgpu.worker.ts`(P3)
- 单测:`*.test.ts` 配套

**复用**(零修改):
- `react-force-graph-2d/3d`、`three`、`comlink`(已有)
- `web/lib/graph-parser.ts` / `graph-edge-display.ts` / `graph-provenance.ts`
- `web/app/graph/use-graph-*.ts` hooks 架构

**后端配合**:
- `app/rag/kg/search/agentic_beam_search.py`(KG plan P0 已规划,输出 trace)
- `app/api/v1/graph.py` 或新增 `app/api/v1/graph_replay.py`

---

## 9. 验证方法

1. **Quad-tree 单测**:`web/lib/graph-quadtree.test.ts` — insert/query/nearest 正确性 + 1w 节点 <50ms
2. **Louvain 单测**:空手道俱乐部图模块度 >0.4
3. **大图烟测**:`pnpm dev` → /graph 上传 5k 节点 GraphML → 60fps;1w 节点 → 30fps
4. **Agentic 回放联调**:KG plan 的 `agentic_beam_search.py` 输出 trace → 前端动画展示 frontier/pruned/selected → 时间轴交互正常
5. **社区折叠**:Louvain → 自动检测出社区(色标在图例)→ 双击折叠/展开
6. **时序动画**(P1):snapshot1 → snapshot2 切换,节点渐变过渡
7. **DSL 查询**(P1):输入 `type:Person AND degree>5` → 高亮符合节点
8. **完整验证**:`pnpm verify` + `pnpm test web/lib/graph-*.test.ts`

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 自实现 Louvain 慢 | 走 Web Worker;<5k 节点同步,>5k 异步;benchmark 1w<2s |
| Quad-tree 与 force-graph 内部状态冲突 | 不修改 force-graph,只在外层 overlay 上做命中 |
| LOD 切换闪烁 | 渐变阈值带 hysteresis(进入 0.5,退出 0.4) |
| 边捆绑视觉过度 | strength 默认 0,用户主动开启 |
| Agentic 回放后端 trace 格式不稳定 | 与 KG plan 协作定义 schema,前端守卫 + 降级到静态展示 |
| 算法自实现 bug | 单测覆盖经典图(空手道、Les Misérables、二分图);属性测试(模块度单调性) |
| WebGPU 兼容性 | P3 才做,Safari 滞后,先做 WebGL fallback |
| 性能退化 | 每个 PR 跑 benchmark CI;指定阈值(60fps@2k / 30fps@1w) |

---

## 11. 与已有调研的关系

- 与 `plans/rag-kg-deep-research-2026-q2.md` 强协同:其 P0 `agentic_beam_search.py` + `path_verbalizer.py` + `plan_on_graph.py` 是本计划 P0.5.2 回放动画的**数据源**
- 与 `plans/rag-visualization-deep-dive-2026-q2.md` 协同:**修正了那份计划"P2 引入 Sigma.js"的建议**,改为纯自研补能力(按用户约束);其 OTel span 是 agentic 回放的 trace 通道
- 与 `plans/rag-ablation-deep-dive-2026-q2.md`:Per-case 钻取可定位"哪条 query 走了哪条 KG 路径",回放动画提供视觉证据
- 与 `plans/rag-poc-attribution-framework-2026-q2.md` 的差评归因:KG 路径是"答错"案例的关键解释维度
- 与 `plans/rag-auto-tagging-services-2026-q2.md` 的实体标签:LLM 标签可作为节点的额外属性(filter / 颜色编码维度)

---

## 12. 关键洞察

1. **9084 行已是业界一线水平**,继续投入应聚焦"业界开源做不到 / 不便集成"的能力——agentic 回放、KG 与 RAG 答案的解释联动
2. **不引入大包是对的**:react-force-graph + 自研增强的组合,比直接换 Sigma.js 维护成本低;每个新算法 200-400 行 TS 即可
3. **Louvain / Quad-tree / PageRank 都不到 300 行**:自实现性价比远高于引库;论文级算法的核心逻辑非常紧凑
4. **真正的 KG-RAG 差异化在"动画化 agentic 推理过程"**:这是商业产品都没做透的领域,直接对标 Plan-on-Graph 论文(WWW'25)
5. **Web Worker 是大图必需基建**:已有 `comlink`,所有重算法走 worker 不阻塞 UI
6. **不要为了"好看"做功能**:鱼眼、WebGPU 等都很炫,但**先把"看得懂、定位 bad case"做到位**(对齐 viz plan 同样洞察)
7. **力导向 + 自研增强 ≠ 玩具**:Cosmograph 的 1M 节点也是基于 d3-force 思路 + WebGL 改造,本质不需要切库,只需要更好的工程

---

## 13. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地内容:
- `/graph` 现有 2D/3D、聚类 worker、RAG trace 回放、网络分析、快照、诊断能力保留不重写。
- 新增自研 `graph-viewport-lod` 空间索引与 LOD 策略,无新增依赖。
- 2D 图谱接入 `nodeVisibility` / `linkVisibility` / `onZoomEnd` / `onEngineStop`,大图缩放和停稳后自动按视口剔除节点与连线。
- 大图显示轻量 LOD 状态提示,缩放到 detail 后恢复节点标签细节。

明确不做:
- Louvain 重写、边捆绑、WebGPU、协同标注、GitOps、多图叠加等属于重工程或低频能力,当前不进入产品闭环。
- Agentic replay 不另造后端;现有 RAG trace 导入和 explain 动画已覆盖必要可解释路径。
