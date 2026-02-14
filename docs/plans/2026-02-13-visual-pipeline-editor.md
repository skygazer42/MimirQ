# Visual Pipeline Editor (MVP) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a new dataset subpage (`/datasets/[id]/workflow`) that renders a read-only graph of the dataset `DatasetConfigBundle` plus export/import (replace=true) with a node detail panel.

**Architecture:** A pure graph builder (`DatasetConfigBundle -> {nodes, links}`) feeds the existing `GraphViewer` (ForceGraph2D). The workflow page fetches config via `datasetApi.exportConfig`, renders the graph, and supports JSON export/import using `datasetApi.importConfig` with a confirmation dialog.

**Tech Stack:** Next.js App Router (client page), React, TypeScript, Tailwind, `react-force-graph-2d` via `GraphViewer`, Radix Dialog, `vitest`.

---

### Task 1: Build Dataset Config Graph (Pure Function + Tests)

**Files:**
- Create: `web/lib/dataset-config-graph.ts`
- Test: `web/lib/dataset-config-graph.test.ts`

**Step 1: Write the failing test**

Create `web/lib/dataset-config-graph.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildDatasetConfigGraph } from './dataset-config-graph'

describe('buildDatasetConfigGraph', () => {
  it('creates stable base nodes/links for empty bundle', () => {
    const g = buildDatasetConfigGraph({})
    const nodeIds = new Set(g.nodes.map((n) => n.id))

    expect(nodeIds.has('bundle')).toBe(true)
    expect(nodeIds.has('ingestion_defaults')).toBe(true)
    expect(nodeIds.has('pipeline')).toBe(true)
    expect(nodeIds.has('ingestion_policy')).toBe(true)
    expect(nodeIds.has('rag_defaults')).toBe(true)
    expect(nodeIds.has('prompt_defaults')).toBe(true)

    expect(g.links.some((l) => l.source === 'bundle' && l.target === 'pipeline')).toBe(true)
  })

  it('adds pipeline sub-block nodes when pipeline is configured', () => {
    const g = buildDatasetConfigGraph({
      pipeline: {
        governance_enabled: true,
        chunk_size: 600,
        bm25_index_enabled: true,
        table_store_enabled: true,
      },
    })
    const nodeIds = new Set(g.nodes.map((n) => n.id))
    expect(nodeIds.has('pipeline_governance')).toBe(true)
    expect(nodeIds.has('pipeline_chunking')).toBe(true)
    expect(nodeIds.has('pipeline_indexing')).toBe(true)
    expect(nodeIds.has('pipeline_tables')).toBe(true)
  })
})
```

**Step 2: Run test to verify it fails**

Run:

```bash
pnpm -C web test -- lib/dataset-config-graph.test.ts
```

Expected: FAIL (module/function not found).

**Step 3: Write minimal implementation**

Create `web/lib/dataset-config-graph.ts`:

```ts
type AnyObj = Record<string, any>

export type ConfigGraphNode = {
  id: string
  label: string
  color?: string
  group?: number
  meta?: {
    kind: 'bundle' | 'group' | 'subgroup'
    configured?: boolean
    summary?: string[]
    json?: any
  }
}

export type ConfigGraphLink = {
  source: string
  target: string
  label?: string
  meta?: { kind: 'contains' }
}

function isNonEmptyObject(v: unknown): v is AnyObj {
  return !!v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v as AnyObj).length > 0
}

function truthyCount(obj: AnyObj, prefix: string) {
  return Object.entries(obj).filter(([k, v]) => k.startsWith(prefix) && !!v).length
}

export function buildDatasetConfigGraph(config: AnyObj): { nodes: ConfigGraphNode[]; links: ConfigGraphLink[] } {
  const cfg = (config || {}) as AnyObj

  const nodes: ConfigGraphNode[] = [
    { id: 'bundle', label: 'Dataset Config', meta: { kind: 'bundle', configured: true, json: cfg } },
  ]
  const links: ConfigGraphLink[] = []

  const addGroup = (id: string, label: string, configured: boolean, json: any, summary: string[] = []) => {
    nodes.push({
      id,
      label,
      color: configured ? '#3b82f6' : '#cbd5e1',
      meta: { kind: 'group', configured, json, summary },
    })
    links.push({ source: 'bundle', target: id, meta: { kind: 'contains' } })
  }

  const parser = String(cfg.default_parser_backend || '')
  const chunk = String(cfg.default_chunk_strategy || '')
  addGroup(
    'ingestion_defaults',
    'Ingestion Defaults',
    !!(parser.trim() || chunk.trim()),
    { default_parser_backend: cfg.default_parser_backend ?? null, default_chunk_strategy: cfg.default_chunk_strategy ?? null },
    [
      `parser_backend: ${parser.trim() ? parser : '(inherit)'}`,
      `chunk_strategy: ${chunk.trim() ? chunk : '(inherit)'}`,
    ]
  )

  const pipeline = (cfg.pipeline || null) as AnyObj | null
  addGroup('pipeline', 'Pipeline', isNonEmptyObject(pipeline), pipeline, [
    pipeline ? `governance_enabled: ${String(!!pipeline.governance_enabled)}` : 'governance_enabled: (inherit)',
  ])

  const ingestionPolicy = cfg.ingestion_policy || null
  addGroup('ingestion_policy', 'Ingestion Policy', isNonEmptyObject(ingestionPolicy), ingestionPolicy, [
    ingestionPolicy?.rules ? `rules: ${Number(ingestionPolicy.rules.length || 0)}` : 'rules: (none)',
  ])

  const ragDefaults = cfg.rag_defaults || null
  addGroup('rag_defaults', 'RAG Defaults', isNonEmptyObject(ragDefaults), ragDefaults)

  const promptDefaults = {
    default_prompt_template_id: cfg.default_prompt_template_id ?? null,
    default_prompt_template_key: cfg.default_prompt_template_key ?? null,
    default_prompt_ab_experiment_key: cfg.default_prompt_ab_experiment_key ?? null,
  }
  addGroup(
    'prompt_defaults',
    'Prompt Defaults',
    Object.values(promptDefaults).some((v) => v != null && String(v).trim()),
    promptDefaults
  )

  // Optional nodes (backend may include these even if web TS types don't yet)
  const cfgAny = cfg as any
  if (cfgAny.chunk_targets_v2 != null) {
    addGroup('chunk_targets', 'Chunk Targets', isNonEmptyObject(cfgAny.chunk_targets_v2), cfgAny.chunk_targets_v2)
  }
  if (cfgAny.fls_policy != null) {
    addGroup('fls_policy', 'FLS Policy', isNonEmptyObject(cfgAny.fls_policy), cfgAny.fls_policy)
  }

  // Pipeline sub-blocks
  if (isNonEmptyObject(pipeline)) {
    const addSub = (id: string, label: string, configured: boolean, json: any, summary: string[] = []) => {
      nodes.push({ id, label, color: configured ? '#10b981' : '#cbd5e1', meta: { kind: 'subgroup', configured, json, summary } })
      links.push({ source: 'pipeline', target: id, meta: { kind: 'contains' } })
    }

    const govConfigured = truthyCount(pipeline, 'governance_') > 0
    if (govConfigured) addSub('pipeline_governance', 'Governance', true, Object.fromEntries(Object.entries(pipeline).filter(([k]) => k.startsWith('governance_'))))

    const chunkConfigured = ['chunk_size', 'chunk_overlap', 'chunk_merge_small_min_chars', 'chunk_strategy_params'].some((k) => pipeline[k] != null)
    if (chunkConfigured) addSub('pipeline_chunking', 'Chunking', true, {
      chunk_size: pipeline.chunk_size ?? null,
      chunk_overlap: pipeline.chunk_overlap ?? null,
      chunk_merge_small_min_chars: pipeline.chunk_merge_small_min_chars ?? null,
      chunk_strategy_params: pipeline.chunk_strategy_params ?? null,
    })

    const indexingConfigured = [
      'chunk_vector_enabled',
      'bm25_index_enabled',
      'kg_enabled',
      'event_vector_enabled',
      'entity_vector_enabled',
    ].some((k) => pipeline[k] != null)
    if (indexingConfigured) addSub('pipeline_indexing', 'Indexing', true, {
      chunk_vector_enabled: pipeline.chunk_vector_enabled ?? null,
      bm25_index_enabled: pipeline.bm25_index_enabled ?? null,
      kg_enabled: pipeline.kg_enabled ?? null,
      event_vector_enabled: pipeline.event_vector_enabled ?? null,
      entity_vector_enabled: pipeline.entity_vector_enabled ?? null,
    })

    const tablesConfigured = Object.keys(pipeline).some((k) => k.startsWith('table_store_') && pipeline[k] != null)
    if (tablesConfigured) addSub('pipeline_tables', 'Tables / TAG', true, Object.fromEntries(Object.entries(pipeline).filter(([k]) => k.startsWith('table_store_'))))
  }

  return { nodes, links }
}
```

**Step 4: Run test to verify it passes**

Run:

```bash
pnpm -C web test -- lib/dataset-config-graph.test.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add web/lib/dataset-config-graph.ts web/lib/dataset-config-graph.test.ts
git commit -m "feat(web): add dataset config graph builder"
```

---

### Task 2: Add Workflow Graph Page (Read-Only)

**Files:**
- Create: `web/app/datasets/[id]/workflow/page.tsx`

**Step 1: Create the page skeleton**

Add `web/app/datasets/[id]/workflow/page.tsx` and render an `AppFrame` + `PageScaffold`.

**Step 2: Fetch dataset + export config**

Use `datasetApi.get(datasetId)` and `datasetApi.exportConfig(datasetId)` in a `load()` callback.

**Step 3: Render the graph**

Use:

```ts
import { GraphViewer } from '@/components/graph/graph-viewer'
import { buildDatasetConfigGraph } from '@/lib/dataset-config-graph'
```

Render `GraphViewer` with:
- `layoutMode="tree"`
- `showEdgeLabels={false}`
- `onNodeClick={(node) => setSelectedNode(node)}`

**Step 4: Detail panel (right side)**

Render a `Panel` that shows:
- node label
- `node.meta.summary` as a list
- JSON block for `node.meta.json`
- Copy JSON button (`navigator.clipboard.writeText(...)`)

**Step 5: Export**

Implement an Export button:
- call `datasetApi.exportConfig(datasetId)`
- download JSON as `dataset-config-<datasetId8>.json`

**Step 6: Import (replace=true)**

Import UX:
- hidden `<input type="file" accept="application/json">`
- read file as text, parse JSON
- accept both shapes:
  - `{ config: <bundle> }`
  - `<bundle>`
- open a confirmation dialog before sending
- on confirm: `datasetApi.importConfig(datasetId, { config, replace: true })`
- on success: toast + reload

**Step 7: Manual smoke**

Run:

```bash
pnpm -C web dev
```

Open: `/datasets/<id>/workflow`, verify graph renders and import/export works.

**Step 8: Commit**

```bash
git add web/app/datasets/[id]/workflow/page.tsx
git commit -m "feat(web): add dataset workflow graph page"
```

---

### Task 3: Add Navigation Entry (Datasets List)

**Files:**
- Modify: `web/app/datasets/page.tsx`

**Step 1: Add the button**

Add a new outline button in the dataset row actions:

```tsx
<Button
  variant="outline"
  size="sm"
  className="gap-2"
  onClick={() => router.push(`/datasets/${ds.id}/workflow`)}
>
  <Layers className="w-3.5 h-3.5" />
  Workflow
</Button>
```

**Step 2: Verify lint/typecheck**

Run:

```bash
pnpm -C web run lint
pnpm -C web run typecheck
```

**Step 3: Commit**

```bash
git add web/app/datasets/page.tsx
git commit -m "feat(web): add workflow nav entry"
```

---

### Task 4: Quality Gates + Close Issue + Push

**Step 1: Run full web verify**

Run:

```bash
pnpm -C web run verify
```

Expected: PASS.

**Step 2: Close bd issue**

Run:

```bash
bd close MimirQ-qto.5
bd sync
```

**Step 3: Push**

Run:

```bash
git pull --rebase
git push
git status
```

Expected: `git status` shows "up to date with 'origin/main'".

