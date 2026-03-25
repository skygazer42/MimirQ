# 第一批：安全 + 性能优化

> 对应审查项 #3、#4、#7

---

## Task 1.1 — 修复图片 Auth Token 泄露（#3）

### 现状

`maybeAttachImageAuthToken()` 存在**两份相同的副本**，均将 JWT 拼接到图片 URL 的 query parameter：

1. `web/components/markdown/markdown-renderer.tsx:56-88`
2. `web/components/chat/message-item.tsx:36-68`（完全相同的逻辑）

```ts
// :84-86 (markdown-renderer.tsx), :64-66 (message-item.tsx)
if (!parsed.searchParams.has('token') && !parsed.searchParams.has('access_token')) {
  if (token) parsed.searchParams.set('token', token)
}
```

两个文件都从 `@/lib/auth-storage` 导入 `getAccessToken` 和 `getTenantId`。
Token 会泄露到浏览器历史、服务器日志、Referer 头。

### 修改方案

**策略：用 `fetch()` + `Authorization` header 获取图片 → 转为 blob URL 渲染。**

#### 步骤

1. **新建 `web/lib/image-auth-proxy.ts`**

```ts
import { getAccessToken, getTenantId } from '@/lib/auth-headers'
import { API_BASE_URL } from '@/lib/env'

let BACKEND_ORIGIN = ''
try { BACKEND_ORIGIN = new URL(API_BASE_URL).origin } catch {}

const blobCache = new Map<string, string>()

function needsAuth(url: string): boolean {
  try {
    const parsed = new URL(url, API_BASE_URL)
    if (BACKEND_ORIGIN && parsed.origin !== BACKEND_ORIGIN) return false
    const path = parsed.pathname || ''
    return path.includes('/api/v1/documents/image/') || path.includes('/api/v1/documents/image-url/')
  } catch { return false }
}

export async function fetchAuthImage(src: string): Promise<string> {
  if (!needsAuth(src)) return src
  if (blobCache.has(src)) return blobCache.get(src)!

  const token = getAccessToken()
  const tenantId = getTenantId()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (tenantId) headers['X-Tenant-ID'] = tenantId

  const resp = await fetch(src, { headers })
  if (!resp.ok) return src

  const blob = await resp.blob()
  const blobUrl = URL.createObjectURL(blob)
  blobCache.set(src, blobUrl)
  return blobUrl
}

export function revokeAuthImages() {
  for (const url of blobCache.values()) URL.revokeObjectURL(url)
  blobCache.clear()
}
```

2. **新建 `web/components/markdown/auth-image.tsx`**

```tsx
'use client'
import { useState, useEffect } from 'react'
import { fetchAuthImage } from '@/lib/image-auth-proxy'

export function AuthImage(props: React.ImgHTMLAttributes<HTMLImageElement>) {
  const { src, ...rest } = props
  const [resolvedSrc, setResolvedSrc] = useState(src)

  useEffect(() => {
    if (!src) return
    let cancelled = false
    fetchAuthImage(src).then(url => { if (!cancelled) setResolvedSrc(url) })
    return () => { cancelled = true }
  }, [src])

  return <img {...rest} src={resolvedSrc} />
}
```

3. **修改 `web/components/markdown/markdown-renderer.tsx`**
   - 删除 `maybeAttachImageAuthToken()` 函数（:56-88）
   - 在 rehype/remark 的 img 渲染组件中使用 `<AuthImage>` 替代原生 `<img>`
   - 搜索文件中所有调用 `maybeAttachImageAuthToken` 的地方，替换为直接传递原始 URL

4. **验证点**
   - 打开包含图片的文档对话，确认图片正常显示
   - 检查 Network 面板：图片请求应使用 `Authorization` header，URL 中不应包含 `token=`
   - `pnpm typecheck && pnpm lint`

---

## Task 1.2 — 移动全局 CSS 和 Provider（#4）

### 现状

`web/app/layout.tsx` 存在两个问题：

1. **第 3 行** `import '@xyflow/react/dist/style.css'` 全局引入，但仅 `web/components/workflow/workflow-editor.tsx` 和 `web/app/datasets/[id]/workflow/page.tsx` 使用 xyflow
2. **第 48-56 行** 4 层 Pipeline Provider 嵌套，但仅被以下路由使用：
   - `PipelineCapabilitiesProvider` → `ParserBackendProvider`, `ChunkStrategyProvider` 依赖它
   - `ParserBackendProvider` → parsing 页面、chunk-preview、settings
   - `ChunkStrategyProvider` → chunk-preview、settings
   - `PipelineOptionsProvider` → chunk-preview

### 步骤

#### A. 移动 xyflow CSS

1. **从 `web/app/layout.tsx` 删除第 3 行** `import '@xyflow/react/dist/style.css'`
2. **在 `web/components/workflow/workflow-editor.tsx` 顶部添加**：
   ```ts
   import '@xyflow/react/dist/style.css'
   ```

#### B. 移动 Pipeline Providers

1. **新建路由组 layout** `web/app/(pipeline)/layout.tsx`：

```tsx
import { PipelineCapabilitiesProvider } from "@/contexts/pipeline-capabilities-context"
import { ParserBackendProvider } from "@/contexts/parser-backend-context"
import { ChunkStrategyProvider } from "@/contexts/chunk-strategy-context"
import { PipelineOptionsProvider } from "@/contexts/pipeline-options-context"

export default function PipelineLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <PipelineCapabilitiesProvider>
      <ParserBackendProvider>
        <ChunkStrategyProvider>
          <PipelineOptionsProvider>
            {children}
          </PipelineOptionsProvider>
        </ChunkStrategyProvider>
      </ParserBackendProvider>
    </PipelineCapabilitiesProvider>
  )
}
```

2. **将需要 Pipeline 的路由移入 `(pipeline)` 路由组**：
   - `parsing/` → `(pipeline)/parsing/`
   - `chunk-preview/` → `(pipeline)/chunk-preview/`
   - `settings/` → `(pipeline)/settings/`
   - `datasets/` → `(pipeline)/datasets/`（workflow 页面和 settings 需要）

   > **注意**：需检查所有使用 `usePipelineCapabilities()`, `useParserBackendPreference()`, `useChunkStrategyPreference()`, `usePipelineOptions()` 的组件，确保它们都在路由组内。

3. **精简 `web/app/layout.tsx`**：
   - 删除 4 个 Provider import
   - `<AuthGuard>{children}</AuthGuard>` 直接作为 `<QueryProvider>` 的子元素

```tsx
// 精简后的 layout.tsx
<ThemeProvider ...>
  <QueryProvider>
    <SonnerToaster />
    <CommandMenu />
    <RouteScrollReset />
    {enableFluidCursor ? <FluidCursor /> : null}
    <TaskCenter />
    <AuthGuard>{children}</AuthGuard>
  </QueryProvider>
</ThemeProvider>
```

4. **验证前置检查**：搜索所有消费这些 context 的文件，确认都在路由组内：

```bash
grep -rn "usePipelineCapabilities\|useParserBackendPreference\|useChunkStrategyPreference\|usePipelineOptions" web/ --include="*.tsx" --include="*.ts"
```

5. **验证点**
   - 非 Pipeline 路由（首页 `/`、`/graph`、`/history`）不应加载 Pipeline 相关 JS
   - Pipeline 路由（`/parsing`、`/settings`、`/chunk-preview`）功能正常
   - `pnpm build` 成功

---

## Task 1.3 — 大型库按需加载（#7）

### 现状

| 库 | 文件数 | 文件列表 | 状态 |
|----|--------|----------|------|
| `recharts` (~200KB) | 8 | `datasets/[id]/profile/page.tsx`, `datasets/[id]/health/page.tsx`, `datasets/[id]/precheck/page.tsx`, `knowledge/ingestion/page.tsx`, `reports/page.tsx`, `observability/page.tsx`, `evaluation/holographic-radar.tsx`, `chunk-preview/workbench/sidebar.tsx` | 直接 import |
| `plotly.js-dist-min` (~1MB) | 2 | `ragviz/similarity-workbench.tsx`, `diagnostics/page.tsx` | ✅ 已用 dynamic import |
| `react-syntax-highlighter` (~200KB+) | 1 | `components/ui/cinematic-typewriter.tsx` | 需检查是否已 dynamic |
| `@codesandbox/sandpack-react` (~500KB) | 0 | 仅 `package.json` 依赖，无实际 import | 可删除依赖 |

### 步骤

#### A. recharts 按需加载（8 个文件）

对每个使用 recharts 的组件，将其图表部分提取为独立组件，用 `next/dynamic` 包装：

**模式示例**（以 `observability/page.tsx` 为例）：

1. 在同目录新建 `_charts.tsx`（或 `components/` 子目录），将所有 recharts import 和图表 JSX 移入
2. 在页面文件中：

```tsx
import dynamic from 'next/dynamic'

const ObservabilityCharts = dynamic(
  () => import('./_charts').then(m => m.ObservabilityCharts),
  { ssr: false, loading: () => <div className="h-64 animate-pulse bg-muted rounded-lg" /> }
)
```

**需处理的 8 个文件**：

| 文件 | 建议新文件 |
|------|-----------|
| `app/datasets/[id]/profile/page.tsx` | `app/datasets/[id]/profile/_charts.tsx` |
| `app/datasets/[id]/health/page.tsx` | `app/datasets/[id]/health/_charts.tsx` |
| `app/datasets/[id]/precheck/page.tsx` | `app/datasets/[id]/precheck/_charts.tsx` |
| `app/knowledge/ingestion/page.tsx` | `app/knowledge/ingestion/_charts.tsx` |
| `app/reports/page.tsx` | `app/reports/_charts.tsx` |
| `app/observability/page.tsx` | `app/observability/_charts.tsx` |
| `components/evaluation/holographic-radar.tsx` | 原地用 dynamic export |
| `components/chunk-preview/components/workbench/sidebar.tsx` | 同目录 `_charts.tsx` |

#### B. react-syntax-highlighter 检查

检查 `components/ui/cinematic-typewriter.tsx` 是否已用 dynamic import。如未使用：

```tsx
const SyntaxHighlighter = dynamic(
  () => import('react-syntax-highlighter').then(m => m.default),
  { ssr: false }
)
```

#### C. 清理未使用的 sandpack 依赖

经代码搜索确认：**零个源文件** import `@codesandbox/sandpack-react`，仅存在于 `package.json` 依赖列表中。可安全删除：

```bash
cd web && pnpm remove @codesandbox/sandpack-react
```

### 验证点

- `pnpm build` — 确认构建成功
- 检查首页 bundle 大小：recharts 不应出现在初始 JS bundle 中
- 各图表页面功能正常（图表延迟加载后正确显示）
