# 第三批：代码质量

> 对应审查项 #1 余项（大组件拆分）、#9（hooks 拆分）、#8（类型安全）、#6（loading/error 补充）

---

## Task 3.1 — 拆分大型组件（#1 余项）

### 需拆分的组件

| 组件 | 行数 | 建议拆分 |
|------|------|---------|
| `components/parsing/parsing-page.tsx` | 2,889 | 见下方 |
| `app/graph/page.tsx` | 2,872 | 见下方 |
| `app/settings/page.tsx` | 2,356 | 见下方 |
| `components/evidence/evidence-suite-workbench.tsx` | 2,579 | 见下方 |
| `components/document-viewer-panel.tsx` | 1,527 | 见下方 |

#### A. `parsing-page.tsx` → 拆分为子组件

```
components/parsing/
├── parsing-page.tsx           # 主容器 + 状态协调（目标 <300 行）
├── upload-zone.tsx            # 文件拖拽/选择上传区域
├── file-queue-table.tsx       # 解析队列表格
├── parse-progress-panel.tsx   # 解析进度面板
├── quality-gate-dialog.tsx    # 质量门控对话框
├── file-preview-drawer.tsx    # 文件预览抽屉
└── parsing-toolbar.tsx        # 工具栏（批量操作、筛选）
```

#### B. `graph/page.tsx` → 拆分为子组件

```
app/graph/
├── page.tsx                   # 主容器 + 路由状态（目标 <300 行）
├── _components/
│   ├── graph-canvas.tsx       # ForceGraph 渲染
│   ├── graph-search.tsx       # 搜索面板
│   ├── graph-filters.tsx      # 实体类型/谓词过滤
│   ├── entity-detail-panel.tsx # 实体详情侧边栏
│   ├── rag-trace-panel.tsx    # RAG trace 可视化
│   ├── path-analysis.tsx      # 路径分析
│   └── layout-switcher.tsx    # 2D/3D/表格布局切换
```

#### C. `settings/page.tsx` → 拆分为 Section 组件

```
app/settings/
├── page.tsx                   # 主容器 + Tab 路由（目标 <200 行）
├── _sections/
│   ├── model-section.tsx      # LLM/Embedding 配置
│   ├── feature-flags-section.tsx # 特性开关
│   ├── parser-section.tsx     # 解析器配置
│   ├── chunk-section.tsx      # 分块策略配置
│   ├── rag-section.tsx        # RAG 配置
│   ├── observability-section.tsx # 可观测配置
│   ├── safety-section.tsx     # 安全配置
│   ├── cache-section.tsx      # 缓存配置
│   └── governance-section.tsx # 数据治理配置
```

#### D. `evidence-suite-workbench.tsx` → 拆分

```
components/evidence/
├── evidence-suite-workbench.tsx  # 主容器（目标 <400 行）
├── suite-list-panel.tsx          # Suite 列表 + CRUD
├── item-list-panel.tsx           # Item 列表 + 筛选
├── item-detail-panel.tsx         # 单个 Item 详情
├── retrieve-panel.tsx            # 检索测试面板
├── import-export-dialog.tsx      # 导入导出
└── scoring-panel.tsx             # 评分面板
```

#### E. `document-viewer-panel.tsx` → 拆分

```
components/document-viewer/
├── document-viewer-panel.tsx    # 主容器（目标 <300 行）
├── chunk-renderer.tsx           # Chunk 内容渲染
├── highlight-layer.tsx          # 高亮层
└── floating-menu.tsx            # 浮动操作菜单
```

### 拆分原则

1. **状态提升**：主容器管理共享状态，通过 props 传递给子组件
2. **回调模式**：子组件通过回调通知父组件，不直接修改父状态
3. **保持接口兼容**：主组件的 export 接口不变
4. **逐步拆分**：每次提取一个子组件，确认功能正常后继续

### 验证点

- 每个子组件拆分后：`pnpm typecheck` 通过
- 全部完成后：`pnpm build` 成功
- 手动验证各页面功能不变

---

## Task 3.2 — 拆分大型 Hooks（#9）

### A. `use-chat.ts` (513 行)

**当前结构**：
- SSE 流式处理逻辑
- Fallback 非流式处理
- 会话管理（创建/加载/切换）
- 超时管理
- `sendMessage` 回调 ~300 行深层嵌套 try/catch

**拆分方案**：

```
hooks/
├── use-chat.ts              # 主 hook（目标 <200 行），协调以下子 hooks
├── use-chat-stream.ts       # SSE 流式逻辑：解析 SSE 事件、处理 token/citation/error
├── use-chat-session.ts      # 会话管理：创建/加载/切换/删除
└── use-chat-formatter.ts    # 消息格式化：markdown 处理、citation 渲染辅助
```

**`use-chat-stream.ts`** 提取内容：
- SSE 事件解析逻辑
- token 拼接
- citation 处理
- error 事件处理
- 超时管理（AbortController）

**`use-chat-session.ts`** 提取内容：
- `createConversation` / `loadConversation` / `switchConversation`
- 会话列表管理
- 会话持久化

### B. `use-documents.ts` (492 行)

**当前结构**：混合了加载、上传（单个+批量+URL）、轮询、取消、删除。

**拆分方案**：

```
hooks/
├── use-documents.ts          # 主 hook，组合子 hooks（目标 <100 行）
├── use-document-list.ts      # 列表加载 + 分页 + 筛选（迁移到 useQuery）
├── use-document-upload.ts    # 上传逻辑（单个 + 批量 + URL）→ useMutation
├── use-document-polling.ts   # 处理中状态轮询
└── use-document-actions.ts   # 删除、取消等操作 → useMutation
```

### 验证点

- 拆分后的主 hook 保持相同的返回值接口
- `pnpm typecheck && pnpm test`
- 手动验证：对话功能、文档上传/删除功能正常

---

## Task 3.3 — 类型安全提升（#8）

### 现状统计

- 98 处 `: any`
- 65 处 `as any`
- 166 处 `Record<string, any>`

### 优先级修复

#### A. 移动 api-client.ts 内联类型（与 Task 2.1 协同）

已在 Task 2.1 中规划，此处不重复。

#### B. 修复 `types/index.ts` 中的 `Record<string, any>`

**策略**：对于有明确 schema 的类型，替换为具体类型；对于真正的 dynamic data（如 `metadata`, `extra`），保留 `Record<string, unknown>`（比 `any` 更安全）。

**批量替换**：
```bash
# 将所有 Record<string, any> 改为 Record<string, unknown>
# 这是安全的第一步，强制调用方做类型检查
```

**手动精修**：对有明确 schema 的字段定义具体类型（需逐个检查 OpenAPI spec）。

#### C. 修复 `retrieve-preview-panel.tsx` 的 12 处 `as any`

逐一检查每个 `as any`，根据实际数据类型添加正确的类型注解或类型守卫。

#### D. 修复重复类型定义

`types/index.ts:1944-1956` 存在与 `types/backend.ts` 的重复 re-export：

```ts
// 这些在 index.ts 中既有手动定义又有从 backend.ts re-export
export type UserProfile = import('./backend').UserProfile  // :1946
// 但前面 :15 也可能有手动定义
```

**操作**：删除手动定义，仅保留从 `backend.ts`（OpenAPI 生成）的 re-export。

### 验证点

- `pnpm typecheck` — 不应增加新错误，目标减少 any 数量
- `pnpm lint` — 通过

---

## Task 3.4 — 补充 loading.tsx / error.tsx（#6）

### 现状

**有 loading.tsx + error.tsx 的路由**（6 个）：
- `app/` (root)
- `app/datasets/[id]/`
- `app/graph/`
- `app/knowledge/`
- `app/settings/`
- `app/evaluations/`

**有 page.tsx 但缺少 loading.tsx / error.tsx 的路由**（~40 个）：

```
app/chunk-preview/
app/data-governance/
app/data-governance/profiles/
app/data-governance/common-lines/
app/logos-preview/
app/knowledge/nebula/
app/knowledge/similarity/
app/knowledge/evidence/
app/knowledge/ingestion/
app/knowledge/quarantine/
app/knowledge/feedback/
app/knowledge/[id]/health/
app/datasets/
app/datasets/[id]/evidence/
app/datasets/[id]/ingestion/
app/datasets/[id]/db-catalog/
app/datasets/[id]/tables/
app/datasets/[id]/precheck/
app/datasets/[id]/health/
app/datasets/[id]/workflow/
app/datasets/[id]/profile/
app/datasets/[id]/kg/
app/parsing/
app/graph/snapshots/
app/graph/diagnostics/
app/evaluations/ablations/
app/evaluation/
app/access-review/
app/auth/
app/auth/oidc/callback/
app/auth/saml/callback/
app/history/
app/settings/groups/
app/settings/groups/[id]/
app/settings/rbac/
app/observability/
app/reports/
app/audit/
app/usage/
app/diagnostics/
app/prompts/
app/page.tsx (root page)
```

### 步骤

#### A. 创建通用 loading 组件

`web/components/route-loading.tsx`：

```tsx
import { Loader2 } from 'lucide-react'

export function RouteLoading() {
  return (
    <div className="flex h-full items-center justify-center" aria-live="polite">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      <span className="sr-only">加载中...</span>
    </div>
  )
}
```

#### B. 批量创建 loading.tsx

对每个缺失的路由，创建 `loading.tsx`：

```tsx
import { RouteLoading } from '@/components/route-loading'
export default function Loading() { return <RouteLoading /> }
```

> 部分路由可以跳过：`auth/oidc/callback/` 和 `auth/saml/callback/` 是回调页面，loading 无意义。`logos-preview/` 是预览页面。

#### C. 批量创建 error.tsx

复用 Task 2.3 中创建的 `<RouteError>` 组件：

```tsx
'use client'
import { RouteError } from '@/components/route-error'
export default function ErrorPage(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <RouteError {...props} />
}
```

### 优先级

优先补充用户常用路由：
1. `app/parsing/` — 文档解析
2. `app/datasets/` — 数据集列表
3. `app/history/` — 对话历史
4. `app/reports/` — 报告
5. `app/observability/` — 可观测
6. 其余路由

### 验证点

- `pnpm build` — 所有路由构建成功
- 手动测试：访问不存在的数据集 ID，确认 error boundary 捕获错误
