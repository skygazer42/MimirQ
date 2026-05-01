# KG 快照(Snapshot)调研 — 现状评估 + 自研版本化与 Diff 深化

## Context

**触发场景**:用户从 `/graph/snapshots` 出发,要求对 KG 快照做全面调研,**约束:不引大包,优先自研**。当前 KG snapshot 实现已具雏形(后端 `app/rag/kg/snapshot.py` 91 行 + 前端 `kg-snapshots-page.tsx` 1229 行),但**只做 count 级聚合 diff**(docs/events/entities/links/relations + entity_types delta),缺**节点/边精确 diff、拓扑/社区变化、语义 diff、版本化、GitOps、影响分析、可视化 overlay、审批工作流**等业界主流能力。本调研对标业界(TerminusDB / Dgraph 时序 / GraphRAG indexer 文件版本化 / Versioned RDF 学术),给出**纯自研深化路线**。

**目标**:把"快照"从"两份聚合数 diff"升级为**完整的版本化系统**——支持精确节点/边 diff、回滚、影响分析、可视化叠加、客户可读报告,所有能力**全部自研**(无新增 npm/pip 大包)。

---

## 1. 现状盘点(已确认)

### 1.1 后端实现(极轻)

`app/rag/kg/snapshot.py`(91 行,纯函数 diff 逻辑):
- `KG_SNAPSHOT_SCHEMA_V1 = "mimirq.kg_snapshot.v1"`
- `diff_kg_snapshots(a, b)` 输出:
  - `delta`:{docs, events, entities, links, relations} 各自 b - a
  - `entity_types_delta`:[{type, delta}] 按绝对值排序
- **不含**节点/边的具体 added/removed 列表
- **无** persistence(不存历史快照,每次现取)

`app/rag/kg/api/routes.py:1328-1482`:
- `export_kg_snapshot(pipeline_hash, ...)` 从 DB 实时构建快照(scoped + ACL-aware)
- `diff_kg_snapshots_api` POST 接收两个快照 JSON 返回 diff
- `compare_kg_snapshots` 一站式:取两个 hash → export → diff
- **限制**:export 只产聚合 count + entity_types,**不输出节点/边明细**

`app/rag/kg/search/snapshot_router.py`:snapshot 范围下的检索路由

`app/services/ops_config_snapshot_service.py` / `slo_snapshot_service.py`:**与 KG 无关**的运维快照(配置/SLO)

### 1.2 前端实现(1229 行,极重)

`web/components/graph/kg-snapshots-page.tsx`:
- 依赖:**`diff` (jsdiff) `diffLines`** + `recharts`(柱状图) + `lucide-react`
- 4 tab:`studio`(对比工作区) / `audit`(审计严重度)
- 视图切换:`diff` / `a` / `b`
- 5 个 DIFF_KEYS:docs / events / entities / links / relations
- 输入两个 pipeline_hash + 可选 document_ids 过滤
- 展示:
  - 5 维 delta 柱状图(recharts)
  - entity_types_delta 表格
  - JSON 文本 unified diff(jsdiff 行级,**不是图级**)
  - 单边 JSON 视图(a / b)
  - 复制 / 下载 / 文件名 sanitize
  - 审计标签(healthy / notice / warning)

### 1.3 已有依赖(不新增)

- `diff` (jsdiff)** - 行级文本 diff 已用,可复用做"序列化后文本 diff"
- `recharts` 已用
- `react-force-graph-2d/3d`(`/graph` 页面)— **未与 snapshots 联动**
- `comlink` / Worker 基建(可借用)

### 1.4 8 大缺口

1. ❌ **节点/边精确 diff**(added/removed/changed 列表,带 id)
2. ❌ **属性级 diff**(节点改名 / 边权重变化 / 类型变化)
3. ❌ **拓扑变化**(社区分裂/合并 / 连通分量变化 / 中心度漂移)
4. ❌ **语义 diff**(LLM 总结"主要变化是什么")
5. ❌ **可视化 overlay**(在 `/graph` 画布上叠加红/绿表示 added/removed)
6. ❌ **历史持久化**(无 DB 表存历史 snapshot,每次实时算)
7. ❌ **GitOps 模型**(branch / commit / revert / cherry-pick)
8. ❌ **影响分析**(某文档删除/重导致哪些节点/边消失,反向追责)

---

## 2. 业界 KG 版本化与 Diff 全景

### A. 商业产品(全部排除,违反约束)

| 产品 | 模型 | 排除原因 |
|---|---|---|
| **Neo4j Aura DB Versioning** | 数据库快照 | 商业 + 锁数据库 |
| **Memgraph Lab** | Cypher diff | 商业 |
| **Dgraph** | 内置 versioning | 整个换数据库 |
| **TigerGraph** | 商业 | 不考虑 |
| **GraphDB Workbench** (Ontotext) | RDF 商业 | 不考虑 |
| **AllegroGraph** | 商业 | 不考虑 |

### B. 开源/学术(参考思路,不引入)

| 项目/论文 | 思路 | 借鉴点 |
|---|---|---|
| **TerminusDB** | **基于 Git 的图数据库**(commit/branch/merge) | **GitOps 模型最完整**,Delta 编码 |
| **Dolt** | "Git for Data"(SQL+Git) | 行级 diff + branch |
| **LakeFS** | 数据湖版本化 | 大文件 versioning |
| **Versioned RDF** (学术) | RDF + commit_id 4 元组 | 时间旅行查询 |
| **LDtab** | 表格化的 RDF 历史 | 简单存储 |
| **Microsoft GraphRAG indexer** | parquet 文件 + 哈希 | **文件级版本化最简方案** |
| **Datasette + git-history** | git 跟踪 SQLite | 元数据级 |
| **Graph Diff** (Müller et al. 2018) | 形式化图 diff 定义 | 算法理论 |
| **GED** (Graph Edit Distance) | 编辑距离最小化 | 节点对齐难题 |
| **Memgraph + TimescaleDB** | 时序图 | 思路 |
| **CRDT for Graphs** | Conflict-free 协作 | KG 协作编辑 |

### C. 业界关键算法(自实现 ROI 高)

| 算法 | 用途 | 自实现成本 |
|---|---|---|
| **节点对齐**(by id) | added/removed 列表 | 50 行 Python |
| **属性 diff**(JSON merge patch RFC 7396) | 节点/边属性变化 | 100 行 |
| **JSON Patch RFC 6902**(op/path/value) | 标准化 patch 格式 | 200 行(也可手写) |
| **Hash-based 内容寻址**(blake3/sha256) | snapshot ID + 去重 | 30 行 |
| **Merkle tree** | 大 KG 增量同步 | 200 行 |
| **Bloom filter on edges** | 快速判定边存在 | 100 行 |
| **拓扑 diff**(连通分量 / 社区) | 走 Louvain 比较 | 100 行(已有 KG-viz plan Louvain) |
| **GED 近似**(贪心匹配) | 节点重命名识别 | 200 行 |
| **Unified diff** | 文本 patch | jsdiff 已用 |
| **三方 merge**(common ancestor) | branch merge | 300 行 |

---

## 3. Gap 分析(MimirQ vs 业界 SOTA)

| 维度 | 业界 SOTA | MimirQ 现状 | Gap | 优先级 |
|---|---|---|---|---|
| 节点 added/removed 精确列表 | TerminusDB / Dolt | ❌ 仅 count | **完全缺** | **P0** |
| 边 added/removed 精确列表 | 同上 | ❌ | **完全缺** | **P0** |
| 属性级 diff(节点改名等) | JSON Patch | ❌ | 完全缺 | **P0** |
| 拓扑变化(社区/连通分量) | 学术 | ❌ | 与 KG-viz Louvain 协同 | P1 |
| 语义 diff(LLM 总结) | GraphRAG Visualizer | ❌ | 缺 | P1 |
| 历史持久化(DB 表) | TerminusDB | ❌ 实时算 | **缺持久化** | **P0** |
| GitOps(branch/commit/revert) | TerminusDB / Dolt | ❌ | 缺 | P2 |
| 可视化 overlay | yFiles temporal | ❌ snapshot 与 /graph 不联动 | **强联动机会** | **P0** |
| 影响分析(反向溯源) | Memgraph Lab | ❌ | 缺 | P1 |
| 三方 diff(>2 snapshot) | TerminusDB | ❌ | 缺 | P2 |
| 时间轴回放(播放历史) | Memgraph + Time | ❌ | 缺 | P2 |
| 客户可读报告(PDF/HTML) | 商业 | ❌ 仅 JSON 下载 | 缺 | P1 |
| 增量同步(Merkle tree) | TerminusDB | ❌ | 大 KG 全量重算 | P3 |
| 审批工作流(stage / approve) | GitOps | ❌ | 缺 | P2 |
| GED 重命名识别 | 学术 | ❌ | 节点重命名误判为"删+增" | P2 |

---

## 4. 推荐方案:四层自研架构

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4 — 战略(P3,长尾)                                       │
│   - Merkle tree 增量同步                                        │
│   - GED 近似(节点重命名识别)                                  │
│   - 时间序列回放动画                                            │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3 — GitOps 化(P2,2 月)                                  │
│   - branch / commit / revert                                    │
│   - 三方 merge(common ancestor)                                │
│   - 审批工作流(stage / approve / publish)                     │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2 — 智能化(P1,1 月)                                     │
│   - 拓扑 diff(社区分裂/合并、连通分量、centrality drift)       │
│   - 语义 diff(LLM 自然语言总结主要变化)                        │
│   - 影响分析(选中节点/边 → 反向追溯到导致变化的文档/chunk)   │
│   - 客户可读 HTML/PDF 报告                                     │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 — 精确 diff + 持久化(P0,2-3 周)                       │
│   - **节点/边精确 added/removed/changed 列表**                  │
│   - **属性级 diff**(JSON Patch RFC 6902 风格)                  │
│   - **历史持久化**(DB 表 + Blob 存储)                          │
│   - **可视化 overlay**(/graph 画布上红/绿叠加)                 │
└──────────────────────────────────────────────────────────────────┘
```

**核心设计原则**:
1. **零新依赖**:全部自研在 `app/rag/kg/snapshot/` 与 `web/lib/graph-snapshot-*`
2. **content-addressed**:每个 snapshot 用 blake3 hash 标识,内容相同自动去重
3. **持久化分级**:聚合统计 + entity_types 入 PG;**节点/边明细入 Blob/MinIO**(>10MB 时);小 KG 直接 PG JSONB
4. **复用 KG-viz plan 算法**:Louvain(社区) / Quad-tree(命中) / PageRank 都已规划自研,本计划复用
5. **/graph 强联动**:不另建画布,在已有 9084 行 graph 模块上叠加 overlay 层
6. **客户优先**:diff 报告必须能脱敏导出 HTML(对齐 Pre-POC scanner 离线报告原则)

---

## 5. P0 落地任务(2-3 周纯自研)

### 5.1 精确节点/边 diff(~400 行)

**修改** `app/rag/kg/snapshot.py`(91 → ~500 行):
- `export_kg_snapshot_v2` 输出新增字段:
  - `nodes`: list of `{id, type, name, props_hash}`(props_hash = blake3 of sorted JSON)
  - `edges`: list of `{src, dst, kind, predicate, props_hash}`
  - `node_props_blob_url`(可选,大 KG 走 MinIO)
- `diff_kg_snapshots_v2(a, b)` 输出:
  - 已有 `delta` + `entity_types_delta`
  - **新增** `nodes_added: [...]` / `nodes_removed: [...]` / `nodes_changed: [{id, before_props_hash, after_props_hash}]`
  - **新增** `edges_added` / `edges_removed` / `edges_changed`
  - 控制大小:>10000 时只返 head/tail + summary,完整列表走单独 endpoint 分页
- Schema bump 到 `mimirq.kg_snapshot.v2`,保留 v1 兼容

**新建** `app/rag/kg/snapshot/diff_v2.py`(独立纯函数文件,~200 行):
- `_align_nodes(a, b)` 按 id 对齐:O(n) hash join
- `_diff_props(a_props, b_props)` 输出 JSON Patch ops 列表(自实现 RFC 6902 子集,无 `jsonpatch` 包)
  - 支持 `add` / `remove` / `replace`
  - 不支持 `move` / `copy` / `test`(不必要)

### 5.2 属性级 diff(JSON Patch 自实现)(~250 行)

**新建** `app/rag/kg/snapshot/json_patch.py`:
- `compute_patch(before, after) -> list[Op]`:深度遍历两个 dict/list 生成最小 op 集合
- `apply_patch(doc, ops) -> dict`:应用 patch
- 单测覆盖 RFC 6902 全部经典样例

### 5.3 历史持久化(~400 行)

**Alembic 迁移**:`migrations/versions/xxxx_add_kg_snapshots.py`
```sql
CREATE TABLE kg_snapshots (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  pipeline_hash VARCHAR(64) NOT NULL,
  snapshot_hash CHAR(64) NOT NULL,  -- blake3 of canonical JSON
  schema VARCHAR(32) NOT NULL DEFAULT 'mimirq.kg_snapshot.v2',
  summary JSONB NOT NULL,           -- counts + entity_types
  nodes_blob_path TEXT,             -- MinIO key (大 KG)
  edges_blob_path TEXT,
  parent_snapshot_id UUID REFERENCES kg_snapshots(id),  -- GitOps 树
  branch_name VARCHAR(64) DEFAULT 'main',
  message TEXT,                     -- commit message
  author_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(tenant_id, snapshot_hash)
);
CREATE INDEX idx_kg_snapshots_pipeline ON kg_snapshots(tenant_id, pipeline_hash, created_at DESC);
CREATE INDEX idx_kg_snapshots_branch ON kg_snapshots(tenant_id, branch_name, created_at DESC);
```

**新建** `app/services/kg_snapshot_store.py`:
- `save_snapshot(snapshot, ...)` → 入 PG + 大字段进 MinIO
- `get_snapshot(id)` → 反向组装
- `list_snapshots(tenant, pipeline_hash, limit)` → 分页
- `compute_canonical_hash(snapshot)` → 排序键 + blake3
- 内容相同自动去重(hash 命中直接返回旧 id)

### 5.4 后端 API 扩展

**修改** `app/rag/kg/api/routes.py:1328-1482`:
- `POST /kg/snapshots/save`(新):保存当前 KG 为快照,返回 id
- `GET /kg/snapshots`(新):列表
- `GET /kg/snapshots/{id}`(新):详情
- `GET /kg/snapshots/{id}/nodes?cursor=...`(新):节点分页
- `POST /kg/snapshots/{a}/diff/{b}`(新):返回 v2 diff(含 nodes_added/removed)
- `GET /kg/snapshots/{id}/diff/{other_id}/nodes_added?cursor=...`(分页 added 节点)

### 5.5 前端可视化 overlay(~400 行)

**新建** `web/components/graph/snapshot-diff-overlay.tsx`:
- 输入:diff_v2 + 当前 graph data(已有 `/graph` 画布)
- 用 SVG 覆盖层(不动 force-graph),根据 diff:
  - 绿色光环:nodes_added
  - 红色叉:nodes_removed(用 ghost 节点占位)
  - 黄色脉冲:nodes_changed
  - 边同色编码
- 时间轴(类似 KG-viz plan 5.2 agentic-replay):snapshot A → B 渐变过渡

**修改** `web/components/graph/kg-snapshots-page.tsx`(1229 → 减重至 ~800):
- 拆分:1229 行太重,提取 `kg-snapshots-list.tsx` / `kg-snapshots-diff-table.tsx` / `kg-snapshots-stats-chart.tsx`
- 新增"在画布上查看 diff"按钮 → 跳转 `/graph?snapshot_a=...&snapshot_b=...` 触发 overlay
- 节点 added/removed 列表(虚拟列表,react-window 已有?若无则简单分页)

### 5.6 单测

- `tests/test_kg_snapshot_diff_v2.py`:精确 added/removed;props 变化;边对齐;edge cases(空快照/同快照)
- `tests/test_kg_json_patch.py`:RFC 6902 全部经典样例
- `tests/test_kg_snapshot_store.py`:save/get/dedup;PG + MinIO 集成
- `web/lib/graph-snapshot-overlay.test.ts`:overlay 数据结构生成

---

## 6. P1 落地任务(1 月)

### 6.1 拓扑变化(~400 行)

**新建** `app/rag/kg/snapshot/topology_diff.py`:
- 复用 KG-viz plan 的 `web/lib/graph-louvain.ts`(算法相同,Python 版 ~250 行)
  - 也可以走 worker 在前端算
- 输出:
  - `community_changes`:{community_id, action: split/merge/grow/shrink, before_size, after_size}
  - `connected_components_delta`:数量变化
  - `centrality_drift`:top-100 节点的 PageRank 变化排名

### 6.2 语义 diff(~300 行)

**新建** `app/rag/kg/snapshot/semantic_diff.py`:
- 输入:diff_v2 的 nodes_added/removed/changed top-50
- LLM 调用(复用 `llm_judge.py` 框架,对齐 evaluation plan)生成自然语言总结:
  - "主要变化:新增 12 个'医药通路'节点,删除 3 个'过期药品'实体,..."
  - 三档简洁度:一句话 / 三段 / 完整报告
- Pydantic SO 强类型;带 Self-Consistency

### 6.3 影响分析(~350 行)

**新建** `app/rag/kg/snapshot/impact_analysis.py`:
- 输入:节点 id(或边 id)
- 反向溯源:
  - 该节点来自哪些 chunks(provenance 已有)
  - 删除/修改后影响哪些下游节点(BFS k-hop)
  - 影响哪些已有 query 的检索结果(对接 ablation plan 的 per-case)
- 前端 `web/components/graph/impact-analysis-panel.tsx`(~200 行)展示树状图

### 6.4 客户可读 HTML 报告(~500 行)

**新建** `app/services/kg_snapshot_report.py`:
- 输入:diff_v2
- 输出:单文件 HTML(对齐 Pre-POC scanner 三原则)
  - 头部:摘要(N 个新增 / M 个删除 / K 个修改)
  - 雷达图(嵌入 echarts SVG)
  - top 10 added/removed 节点表格
  - 语义总结(P1.6.2 输出)
  - 脱敏选项(节点 name 走 Presidio)
- 复用前端 echarts 服务端渲染(echarts-snapshot 或自实现 SSR)

### 6.5 三方 / N 方 diff(~300 行)

**修改** `app/rag/kg/snapshot/diff_v2.py`:
- `diff_kg_snapshots_n(snapshots: list[dict])`:
  - 共有节点(intersection)
  - 任一独有节点
  - 矩阵 N×N 两两 diff
- 前端 `kg-snapshots-page.tsx` 新 tab"多方对比",echarts 维恩图(自研 3-4 集合的 SVG)

---

## 7. P2/P3(季度计划)

### P2 GitOps 化

- **branch / commit / revert**:复用 `parent_snapshot_id` 字段构建 commit 树
- **三方 merge**:找 common ancestor → 各自 patch → conflict 检测
- **审批工作流**:`stage` 状态 → `approve` → `publish`;集成已有 RBAC

### P3

- **Merkle tree 增量同步**:大 KG snapshot 复用未变化部分(blob 寻址)
- **GED 近似(节点重命名识别)**:贪心匹配 + 属性 cos sim,识别"删 A 增 A'"实为重命名
- **时间序列回放动画**:每日自动 snapshot + 时间轴 → 跨周/月观察 KG 演化
- **CRDT 协作编辑**:多人同时改 KG,自动合并(高复杂度,只在确实需要时做)

---

## 8. 关键文件清单

**修改**(增强,不重写):
- `app/rag/kg/snapshot.py`(91 → ~500 行,加 v2 diff)
- `app/rag/kg/api/routes.py:1328-1482`(新 endpoints)
- `web/components/graph/kg-snapshots-page.tsx`(1229 → ~800,拆分 + overlay 入口)
- `web/lib/api/graph.ts`(新方法)

**新建**(纯自研,无新依赖):
- `app/rag/kg/snapshot/__init__.py`
- `app/rag/kg/snapshot/diff_v2.py`(P0)
- `app/rag/kg/snapshot/json_patch.py`(P0,RFC 6902 自实现)
- `app/rag/kg/snapshot/topology_diff.py`(P1)
- `app/rag/kg/snapshot/semantic_diff.py`(P1)
- `app/rag/kg/snapshot/impact_analysis.py`(P1)
- `app/services/kg_snapshot_store.py`(P0)
- `app/services/kg_snapshot_report.py`(P1,HTML 报告)
- `migrations/versions/xxxx_add_kg_snapshots.py`(P0)
- `web/components/graph/snapshot-diff-overlay.tsx`(P0)
- `web/components/graph/kg-snapshots-list.tsx`(P0,从 1229 行拆出)
- `web/components/graph/kg-snapshots-diff-table.tsx`(P0,从 1229 行拆出)
- `web/components/graph/kg-snapshots-stats-chart.tsx`(P0,从 1229 行拆出)
- `web/components/graph/impact-analysis-panel.tsx`(P1)
- `web/lib/graph-snapshot-overlay.ts`(P0,overlay 数据结构)
- 单测:`test_kg_snapshot_diff_v2.py` / `test_kg_json_patch.py` / `test_kg_snapshot_store.py` / `test_kg_topology_diff.py` / `test_kg_impact_analysis.py`

**复用**(零修改 + 协同):
- `app/rag/kg/api/routes.py` 已有 `export_kg_snapshot`(扩展输出 v2)
- `app/services/regression_run_diff.py`(diff 模式可借鉴)
- `web/components/graph/graph-canvas.tsx` 等 9084 行 KG 模块(overlay 层叠加)
- 已有依赖:`diff` (jsdiff) / `recharts`(JSON 文本 diff 已用,不动)
- KG-viz plan 的 Louvain / Quad-tree / Worker 基建
- evaluation plan 的 `llm_judge.py`(语义 diff 复用)

**后端配合**:
- `app/services/document_permission_service.py`(diff 时 ACL 守卫)
- `app/services/security_redaction.py`(对客户报告脱敏)

---

## 9. 验证方法

1. **JSON Patch 单测**:`pytest tests/test_kg_json_patch.py -v` — RFC 6902 经典样例全过
2. **Diff v2 单测**:同 KG diff 应空;增 1 节点应 nodes_added=[1];改 props 应 nodes_changed
3. **持久化烟测**:save 同一 KG 两次 → 第二次 hash 命中返回相同 id(去重)
4. **API 烟测**:
   ```bash
   curl -X POST /api/v1/kg/snapshots/save -d '{"pipeline_hash":"abc"}' → {id}
   curl -X POST /api/v1/kg/snapshots/{a}/diff/{b}
   ```
5. **前端联调**:`/graph/snapshots` 选两个 hash → 显示 added/removed 列表 → 点"在画布查看"→ `/graph` 红绿 overlay
6. **大 KG 性能**:10w 节点 diff < 5 秒(blake3 hash join);blob 路径走 MinIO 不阻塞 PG
7. **影响分析**(P1):选某节点 → 显示影响 5 个文档 + 12 个下游节点
8. **HTML 报告**(P1):导出 → 打开浏览器 → 单文件含图表 + 表格 + 语义总结
9. **完整验证**:`pnpm verify` + `pytest tests/test_kg_*.py -v` 全绿

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 节点/边明细膨胀 PG | >10MB 走 MinIO blob;PG 只存 hash + summary;分页 endpoint 拉明细 |
| Hash 冲突 | blake3 256-bit 冲突概率极低;tenant_id + snapshot_hash 联合唯一 |
| 大 KG diff 慢 | hash join O(n);分批流式;>10w 节点提示用户走异步任务 |
| ACL 透传缺失 | diff 时严格走 `document_permission_service`;旧/新 snapshot 都要校验 |
| 节点重命名误判 | P0 不识别(仅 added+removed);P3 GED 近似 |
| Overlay 与 force-graph 冲突 | 用纯 SVG 覆盖层,不动 force-graph 内部 |
| 历史 v1 兼容 | schema 字段兼容,旧 snapshot 显示"无明细" |
| 客户报告 PII 泄露 | 默认走 Presidio 脱敏(对齐 safety + Pre-POC plan);手动开关 |
| Storage 成本 | retention 策略(保留最近 30 天 + 关键 milestone);blob 走对象存储 |
| 拆分 1229 行回归风险 | 严格保留所有 source.test.ts 用例;拆完跑 `pnpm test web/components/graph` |

---

## 11. 与已有调研的关系

- 与 `plans/rag-kg-visualization-self-built-2026-q2.md`:本计划的 5.5 overlay 复用其 P0 Quad-tree 命中;P1 拓扑 diff 复用其 P0 Louvain 算法;**双方 KG 模块全栈共建**
- 与 `plans/rag-kg-deep-research-2026-q2.md`:KG provenance + ontology 是 snapshot 的语义层;influence analysis 用其 BFS k-hop
- 与 `plans/rag-evaluation-deep-dive-2026-q2.md`:语义 diff 复用 `llm_judge.py` 框架(P0)
- 与 `plans/rag-ablation-deep-dive-2026-q2.md`:影响分析"哪些 query 被影响"对接 ablation per-case 钻取
- 与 `plans/rag-pre-poc-scanner-2026-q2.md`:HTML 单文件报告原则一致(脱敏 + 客观 + 待确认)
- 与 `plans/rag-safety-compliance-deep-dive-2026-q2.md`:Presidio 脱敏在客户报告导出时强制
- 与 `plans/rag-poc-attribution-framework-2026-q2.md`:5 字段埋点的"final_context_filenames"可与影响分析互查
- 与 `plans/rag-poc-to-mvp-delivery-2026-q2.md`:GitOps 思路(P2)与"运营闭环 + 反馈基础设施"协同

---

## 12. 关键洞察

1. **现状是"假快照"**——只存聚合数,真实 KG 内容没存,没法回滚也没法精确比较;升级为"真快照"是 P0 必做
2. **Content-addressed (blake3)** 是去重和增量同步的基石;每个 snapshot 一个唯一 hash 是最小代价获得最大收益
3. **不引大包是对的**:TerminusDB 整套换数据库,Dolt 强绑 SQL,自研 JSON Patch + blob storage 完全够用
4. **/graph 是 9084 行的金矿**:本计划不另建画布,在已有基建上叠 overlay 层,500 行就能完成可视化
5. **客户拿走的报告才有价值**:HTML 单文件 + 脱敏对齐 Pre-POC plan 思路,这是产品差异化
6. **GitOps 不必激进**:P0 只做 commit 树(parent_snapshot_id)就够支撑后续 branch/merge,不要一上来全盘 GitOps
7. **拆 1229 行是顺带的好事**:大组件难维护、难复用,P0 拆 4 个子组件后续每个 plan 都受益
8. **影响分析(P1)是真护城河**:让客户在改 KG 之前就能看到"会影响什么",这是企业最值钱的能力

---

## 13. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地:
- 后端闭环:`/api/v1/kg/snapshots/export?include_details=true` 可导出 bounded event/entity nodes 与 event_entity/relation edges,每条记录带稳定 `props_hash`.
- Diff 闭环:`diff_kg_snapshots` 在 v2 快照上返回 `node_diff` / `edge_diff` 与 added/removed/changed 样本列表,保留 v1 聚合 diff 兼容.
- 前端闭环:`/graph/snapshots` 默认请求明细,Diff 视图显式展示精确节点/边变化摘要与样本,不再只能看 JSON 行级差异.
- 测试闭环:新增精确 node/edge drift 单测与前端 source test,覆盖 API 使用与产品化展示入口.

暂缓:
- KG snapshot DB 持久化、MinIO blob、commit tree、branch/merge/revert.
- `/graph` 画布 overlay 与时间轴回放.
- 拓扑 diff、语义 diff、影响分析与客户 HTML/PDF 报告.
- 大 KG 异步分页 diff 与 Merkle 增量同步.

Directive: 当前产品先解决“能看清两版 KG 具体变了什么”;不要在没有真实使用压力前引入 GitOps 或重型持久化系统.
