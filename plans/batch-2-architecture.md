# 第二批：架构治理

> 对应审查项 #1（api-client 拆分）、#2（TanStack Query）、#5（消除重复）

---

## Task 2.1 — 拆分 api-client.ts（#1）

### 现状

`web/lib/api-client.ts` 有 **4,261 行**，被 **83 个文件** import，包含：
- Axios 实例 (`apiClient`) 和基础设施（SSE helpers, request ID, auth headers）
- **32 个 API 命名空间**（经代码分析确认）：`healthApi`, `documentApi`, `parsingApi`, `authApi`, `pipelineApi`, `governanceApi`, `chunkPresetApi`, `connectorApi`, `ingestionRunApi`, `ragApi`, `retrievalApi`, `evidenceApi`, `datasetApi`, `datasetCategoryApi`, `reportApi`, `chatApi`, `sseApi`, `feedbackApi`, `kgApi`, `metaApi`, `observabilityApi`, `usageApi`, `auditApi`, `rbacApi`, `groupApi`, `scimApi`, `settingsApi`, `ltrApi`, `evaluationApi`, `promptTemplateApi`, `ragConfigTemplateApi`, `ragvizApi`
- **55+ 个内联类型定义**（`FeatureFlags`, `KGConfig`, `LLMConfig`, `RagasRun`, `BackendMeta`, `SystemSettings`, `RAGConfig`, `CacheConfig`, `GovernanceConfig`, `RagConfigTemplate`, `PromptTemplate`, `TenantMember`, `LTRModelInfo` 等）
- 两种调用风格混用：raw `apiClient.get/post` vs `openapiRequest`
- `extractRateLimitDetail` 与 `lib/api-errors.ts` 重复

> ⚠️ **影响范围大**：83 个文件依赖此模块，拆分时必须通过 `index.ts` barrel export 保持向后兼容，然后逐步迁移 import 路径。

### 目标目录结构

```
web/lib/api/
├── client.ts          # Axios 实例、拦截器、SSE helpers、generateRequestId、buildFetchError
├── openapi.ts         # openapiRequest 函数（从原文件移入）
├── auth.ts            # authApi, scimApi
├── chat.ts            # chatApi, sseApi (chat stream)
├── connectors.ts      # connectorApi, ingestionRunApi
├── datasets.ts        # datasetApi, datasetCategoryApi
├── documents.ts       # documentApi, parsingApi
├── evaluation.ts      # evaluationApi, ltrApi
├── evidence.ts        # evidenceApi
├── feedback.ts        # feedbackApi
├── governance.ts      # governanceApi
├── graph.ts           # kgApi
├── health.ts          # healthApi, metaApi
├── observability.ts   # observabilityApi, usageApi, auditApi
├── pipeline.ts        # pipelineApi, chunkPresetApi
├── prompts.ts         # promptTemplateApi, ragConfigTemplateApi
├── rag.ts             # ragApi, retrievalApi, ragvizApi
├── reports.ts         # reportApi
├── rbac.ts            # rbacApi, groupApi
├── settings.ts        # settingsApi
└── index.ts           # re-export all（保持向后兼容）
```

### 步骤

#### A. 提取基础设施层

1. **新建 `web/lib/api/client.ts`** — 移入以下内容：
   - `apiClient` Axios 实例创建 + 拦截器
   - `API_V1_BASE_URL`, `API_LONG_TIMEOUT_MS` 常量
   - `generateRequestId()`, `getAuthHeaders()`, `buildFetchError()`
   - `readSseDataStrings()` SSE 辅助函数
   - `appendChunkPreviewFormFields()`, `buildChunkPreviewQueryParams()`
   - 删除 `extractRateLimitDetail`（改用 `lib/api-errors.ts` 中的版本）

2. **新建 `web/lib/api/openapi.ts`** — 移入 `openapiRequest` 函数

#### B. 按领域拆分 API 命名空间

对每个领域模块（如 `chat.ts`）：

```ts
// web/lib/api/chat.ts
import { apiClient, API_V1_BASE_URL, API_LONG_TIMEOUT_MS, getAuthHeaders, generateRequestId, readSseDataStrings, buildFetchError } from './client'
import type { ChatRequest, Conversation, Message, ... } from '@/types'

export const chatApi = { ... }  // 原封不动移入
export const sseApi = { ... }
```

#### C. 移动内联类型到 `types/`

`api-client.ts` 中有 **55+ 个内联类型定义**，需按领域移入 `types/` 目录。主要分组：

- `FeatureFlags`, `KGConfig`, `LLMConfig`, `EmbeddingConfig`, `MilvusConfig` → `types/settings.ts`
- `RAGConfig`, `CacheConfig`, `UrlIngestConfig`, `GovernanceConfig` → `types/settings.ts`
- `SystemSettings`, `SystemStatus`, `ParserBackendStatus` → `types/settings.ts`
- `RagasRun`, `RagasItem`, `RagasRunDetail` → `types/evaluation.ts`
- `RagConfigTemplate`, `RagConfigTemplateCreate` 等 → `types/rag-config.ts`
- `PromptTemplate`, `PromptTemplateCreate` 等 → `types/prompts.ts`
- `TenantMember`, `TenantMemberListResponse` → `types/rbac.ts`
- `LTRModelInfo` 等 → `types/evaluation.ts`
- `DocumentLifecycleFilter`, `ChunkPreviewRequestParams` → `types/documents.ts`（如不存在则新建）

> **注意**：`types/index.ts`（3,008 行）中已有 87 个从 `backend.ts` re-export 的 OpenAPI 类型 + 299 个手动定义的 interface。移入新类型时需检查是否与 OpenAPI 生成类型重复，如有重复则仅保留 OpenAPI 版本。

#### D. 创建 barrel export

**`web/lib/api/index.ts`**：

```ts
// Re-export all API namespaces for backward compatibility
export { apiClient, API_V1_BASE_URL } from './client'
export { healthApi, metaApi } from './health'
export { documentApi, parsingApi } from './documents'
export { chatApi, sseApi } from './chat'
export { datasetApi, datasetCategoryApi } from './datasets'
// ... etc
```

#### E. 更新 import 路径

搜索所有 `from '@/lib/api-client'` 的 import，逐步更新为具体模块路径。可以先保留 `index.ts` re-export 保持兼容，后续逐步迁移。

#### F. 删除原文件

确认所有 import 都指向新位置后，删除 `web/lib/api-client.ts`。

### 依赖关系

- 此 task 与 Task 2.3 (`extractRateLimitDetail` 去重) 有交叉 — 拆分时直接使用 `api-errors.ts` 中的版本
- 拆分后的模块应继续使用现有调用风格（暂不迁移到 `openapiRequest`，留给后续 PR）

### 验证点

- `pnpm typecheck` — 无新错误
- `pnpm lint` — 无新警告
- `pnpm test` — 现有测试通过
- `pnpm build` — 构建成功
- 手动验证：对话、文档管理、设置页面功能正常

---

## Task 2.2 — 统一 TanStack Query 数据获取（#2）

### 现状

| 现有 useQuery 使用 | 文件 |
|-------------------|------|
| `useQuery` | `hooks/use-backend-health.ts`, `use-backend-meta.ts`, `use-backend-ready.ts` |
| `useQuery` | `app/knowledge/ingestion/page.tsx`, `feedback/page.tsx`, `quarantine/page.tsx` |
| `useQuery` | `components/ingestion/ingestion-detail-dialog.tsx`, `task-center.tsx` |
| `useMutation` | **0 处** |

**需迁移到 useQuery 的 hooks（手动 fetch 模式）**：
- `hooks/use-connector-runs.ts`
- `hooks/use-index-audit.ts`
- `hooks/use-auth.ts`
- `hooks/use-documents.ts`
- `contexts/pipeline-capabilities-context.tsx`（325 行手动 loading/error/refresh）

### 步骤

#### A. 建立 Query Key 工厂

**新建 `web/lib/query-keys.ts`**：

```ts
export const queryKeys = {
  // Documents
  documents: {
    all: ['documents'] as const,
    list: (params?: Record<string, unknown>) => [...queryKeys.documents.all, 'list', params] as const,
    detail: (id: string) => [...queryKeys.documents.all, 'detail', id] as const,
    chunks: (id: string) => [...queryKeys.documents.all, 'chunks', id] as const,
  },
  // Datasets
  datasets: {
    all: ['datasets'] as const,
    list: (params?: Record<string, unknown>) => [...queryKeys.datasets.all, 'list', params] as const,
    detail: (id: string) => [...queryKeys.datasets.all, 'detail', id] as const,
  },
  // Chat
  chat: {
    all: ['chat'] as const,
    conversations: (params?: Record<string, unknown>) => [...queryKeys.chat.all, 'conversations', params] as const,
    messages: (conversationId: string) => [...queryKeys.chat.all, 'messages', conversationId] as const,
  },
  // Pipeline
  pipeline: {
    capabilities: ['pipeline', 'capabilities'] as const,
  },
  // Connectors
  connectors: {
    runs: (datasetId: string) => ['connectors', 'runs', datasetId] as const,
  },
  // Auth
  auth: {
    profile: ['auth', 'profile'] as const,
  },
  // Index Audit
  indexAudit: {
    result: (datasetId: string) => ['indexAudit', datasetId] as const,
  },
  // Health
  health: {
    status: ['health'] as const,
    ready: ['health', 'ready'] as const,
    meta: ['meta'] as const,
  },
  // Evaluations
  evaluations: {
    all: ['evaluations'] as const,
    list: (params?: Record<string, unknown>) => [...queryKeys.evaluations.all, 'list', params] as const,
  },
} as const
```

#### B. 迁移 PipelineCapabilitiesContext（优先级最高）

当前 `contexts/pipeline-capabilities-context.tsx` 手动管理 `loading`, `error`, `capabilities` state + `useEffect` fetch。

**迁移方案**：保持 Context 接口不变，内部替换为 useQuery：

```tsx
export function PipelineCapabilitiesProvider({ children }: ...) {
  const { data: capabilities, isLoading: loading, error, refetch: refresh } = useQuery({
    queryKey: queryKeys.pipeline.capabilities,
    queryFn: () => pipelineApi.getCapabilities(),
    staleTime: 5 * 60 * 1000,
  })

  // ... 其余 computed values 保持不变
}
```

#### C. 迁移其他 Hooks

**`hooks/use-connector-runs.ts`** → 用 useQuery 替换 useEffect+useState：
```ts
export function useConnectorRuns(datasetId: string) {
  return useQuery({
    queryKey: queryKeys.connectors.runs(datasetId),
    queryFn: () => connectorApi.listRuns(datasetId),
    enabled: !!datasetId,
  })
}
```

**`hooks/use-auth.ts`** → 类似模式
**`hooks/use-index-audit.ts`** → 类似模式

#### D. 添加 useMutation 用于写操作

在各页面中，将 `try/catch` 手动处理的写操作替换为 `useMutation`。优先处理：

1. **文档上传/删除** — `hooks/use-documents.ts` 中的 upload/delete 函数
2. **对话创建/删除** — 各聊天页面
3. **设置保存** — settings 页面

**模式**：

```ts
const deleteMutation = useMutation({
  mutationFn: (id: string) => documentApi.delete(id),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
    toast.success('删除成功')
  },
  onError: (err) => toast.error(formatApiError(err)),
})
```

#### E. 清理散落的 query key 字符串

搜索现有代码中硬编码的 query key（如 `['documents']`），替换为 `queryKeys.xxx`。

### 验证点

- 迁移后的 hook 行为不变（loading/error/data 接口兼容）
- 缓存生效：相同数据不重复请求
- `pnpm typecheck && pnpm test && pnpm build`

---

## Task 2.3 — 消除代码重复（#5）

### A. `sanitizeFilename` — 10 个文件各自实现

**涉及文件**：
- `web/components/graph/kg-diagnostics-page.tsx`
- `web/app/datasets/[id]/health/page.tsx`
- `web/components/evaluation/retrieval-ablations-page.tsx`
- `web/components/chunk-preview/components/chunk-preset-panel.tsx`
- `web/app/reports/page.tsx`
- `web/components/chunk-preview/components/chunk-compare-dialog.tsx`
- `web/components/graph/kg-snapshots-page.tsx`
- `web/components/chunk-preview/components/workbench/top-bar.tsx`
- `web/components/chunk-preview/utils/export.ts`
- `web/components/chunk-preview/components/chunk-auto-tune-dialog.tsx`

> ⚠️ **BUG 注意**：`web/components/chunk-preview/utils/export.ts:8` 中的 `sanitizeFilename` 实现**有 bug** — 使用了字符串字面量 `'[^a-zA-Z0-9_\\-.]'` 而非正则表达式 `/[^a-zA-Z0-9_\-.\u4e00-\u9fff]/g`，导致该文件的文件名清理功能实际上不起作用。统一使用共享版本时将自动修复此 bug。

**操作**：
1. 新建 `web/lib/sanitize.ts`：
```ts
export function sanitizeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9_\-.\u4e00-\u9fff]/g, '_').replace(/_{2,}/g, '_')
}
```
2. 删除所有文件中的本地 `sanitizeFilename` 定义
3. 添加 `import { sanitizeFilename } from '@/lib/sanitize'`
4. 特别注意 `export.ts` 中的 bug 版本需要一并替换

### B. Error Boundary 组件 — 6 个 `error.tsx` 几乎相同

**涉及文件**（6 个 error.tsx）：
- `app/error.tsx`, `app/datasets/[id]/error.tsx`, `app/graph/error.tsx`, `app/knowledge/error.tsx`, `app/settings/error.tsx`, `app/evaluations/error.tsx`

**操作**：
1. 新建 `web/components/route-error.tsx`：
```tsx
'use client'
import { useEffect } from 'react'
import Link from 'next/link'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { FullScreenFrame } from '@/components/full-screen-frame'

export function RouteError({
  error, reset, title = '页面加载失败', message = '发生了一个临时错误，请重试或返回首页继续操作。',
}: Readonly<{
  error: Error & { digest?: string }; reset: () => void; title?: string; message?: string
}>) {
  useEffect(() => { console.error(error) }, [error])
  return (
    <FullScreenFrame>
      <Card className="w-full max-w-lg rounded-3xl shadow-strong">
        <CardContent className="p-8 text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-warning/10 text-warning">
            <AlertTriangle className="h-6 w-6" />
          </div>
          <h1 className="text-xl font-semibold text-foreground">{title}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{message}</p>
          <div className="mt-6 flex items-center justify-center gap-3">
            <Button onClick={() => reset()}>重试</Button>
            <Button variant="outline" asChild><Link href="/">返回首页</Link></Button>
          </div>
          {error?.digest && (
            <p className="mt-4 text-xs font-mono text-muted-foreground">错误 ID：{error.digest}</p>
          )}
        </CardContent>
      </Card>
    </FullScreenFrame>
  )
}
```
2. 简化所有 6 个 `error.tsx` 为：
```tsx
'use client'
import { RouteError } from '@/components/route-error'
export default function ErrorPage(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <RouteError {...props} />
}
```

### C. `trimTrailingSlashes` 去重

**涉及文件**：`lib/utils.ts` 和 `lib/env.ts` 各一份，另外 `components/knowledge/import/knowledge-jira-project-dialog.tsx` 和 `.payload.ts` 也引用。

**操作**：
1. 仅保留 `lib/utils.ts` 中的版本
2. `lib/env.ts` 改为 `import { trimTrailingSlashes } from './utils'`
3. 确认 Jira dialog 文件引用路径正确

### D. Base64/Base64URL 编码合并

**操作**：
1. 新建 `web/lib/encoding.ts`，将 `lib/oidc-pkce.ts` 和 `lib/saml-session.ts` 中重复的 base64/base64url 函数移入
2. 两个文件改为 import

### E. `extractRateLimitDetail` 去重

**涉及文件**：`lib/api-errors.ts`（:39-45）和 `lib/api-client.ts`（:132-139）

**操作**：
1. 保留 `lib/api-errors.ts` 中的版本
2. `lib/api-client.ts`（或拆分后的 `lib/api/client.ts`）改为 import
3. 如函数签名略有不同，统一为更完整的版本

### F. Parser backend 名称规范化去重

**涉及文件**（3 处实现）：
- `contexts/parser-backend-context.tsx:36-42` — 主要的规范化逻辑
- `contexts/pipeline-capabilities-context.tsx` — 类似的 parser name 处理
- `components/ui/parser-dropdown.tsx` — 第三份副本，用于下拉组件渲染

> ⚠️ **不一致问题**：`parser-backend-context.tsx` 的规范化逻辑缺少 `olm-ocr` / `olmocr-pdf` 的别名映射，而后端已支持这些 parser。合并时应补充完整的别名表。

**操作**：
1. 新建 `web/lib/parser-compat.ts`：
```ts
export function normalizeParserBackendName(raw: string): string {
  const normalized = raw.toLowerCase().trim().replaceAll('_', '-')
  if (normalized === 'magic-pdf') return 'magicpdf'
  if (normalized === 'etl-4llm') return 'etl4llm'
  if (['bisheng-unstructured', 'bishengunstructured', 'bisheng'].includes(normalized)) return 'etl4llm'
  if (['olm-ocr', 'olmocr-pdf'].includes(normalized)) return 'olmocr'
  return normalized || 'auto'
}
```
2. 替换 3 个文件（`parser-backend-context.tsx`、`pipeline-capabilities-context.tsx`、`parser-dropdown.tsx`）中的内联逻辑

### 验证点

- `pnpm typecheck && pnpm lint && pnpm test && pnpm build`
- 各功能页面正常工作
