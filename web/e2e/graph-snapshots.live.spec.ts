import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type LiveDocument = {
  id?: string
  status?: string
  active_pipeline_hash?: string | null
  metadata?: Record<string, unknown> | null
}

type LiveKgStats = {
  events: number
  entities: number
  links: number
}

type LiveSnapshotDiff = {
  node_diff?: {
    added_count?: number | null
    removed_count?: number | null
    changed_count?: number | null
  } | null
  edge_diff?: {
    added_count?: number | null
    removed_count?: number | null
    changed_count?: number | null
  } | null
}

function apiBaseUrl(): string {
  return String(
    process.env.PLAYWRIGHT_LIVE_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      'http://127.0.0.1:8000'
  ).replace(/\/+$/, '')
}

function liveHeaders(): Record<string, string> {
  return {
    'X-Tenant-ID':
      process.env.PLAYWRIGHT_LIVE_TENANT_ID ||
      process.env.NEXT_PUBLIC_TENANT_ID ||
      DEFAULT_TENANT_ID,
    'X-Account-ID':
      process.env.PLAYWRIGHT_LIVE_USER_ID ||
      process.env.NEXT_PUBLIC_USER_ID ||
      DEFAULT_USER_ID,
    'X-User-ID':
      process.env.PLAYWRIGHT_LIVE_USER_ID ||
      process.env.NEXT_PUBLIC_USER_ID ||
      DEFAULT_USER_ID,
  }
}

async function installLiveAuth(page: Page) {
  const headers = liveHeaders()
  await page.addInitScript(
    ({ tenantId, userId }) => {
      window.localStorage.setItem('mimirq_tenant_id', tenantId)
      window.localStorage.setItem('mimirq_user_id', userId)
    },
    {
      tenantId: headers['X-Tenant-ID'],
      userId: headers['X-User-ID'],
    }
  )
}

async function createLiveDataset(
  request: APIRequestContext,
  name: string
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/datasets/`, {
    headers: liveHeaders(),
    data: {
      name,
      description: 'Playwright live graph snapshots dataset.',
      permission: 'all_team_members',
      default_parser_backend: 'auto',
      default_chunk_strategy: 'langchain_recursive',
      pipeline: {
        governance_enabled: true,
        persist_parsed_content: true,
        persist_parsed_content_max_chars: 200000,
        chunk_size: 1000,
        chunk_overlap: 200,
        chunk_vector_enabled: true,
        bm25_index_enabled: true,
        kg_enabled: true,
        event_vector_enabled: false,
        entity_vector_enabled: false,
      },
    },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { id?: string; dataset_id?: string }
  const datasetId = String(body.id || body.dataset_id || '')
  expect(datasetId).toMatch(/\S/)
  return datasetId
}

async function deleteLiveDataset(
  request: APIRequestContext,
  datasetId: string
): Promise<void> {
  const purgeResponse = await request.post(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}/purge?dry_run=false&max_delete=1000`,
    {
      headers: liveHeaders(),
      data: {},
    }
  )
  expect(purgeResponse.ok()).toBe(true)

  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

async function uploadCompletedDocument(
  request: APIRequestContext,
  {
    datasetId,
    filename,
    content,
    chunkStrategy,
  }: {
    datasetId: string
    filename: string
    content: string
    chunkStrategy: string
  }
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/documents/upload`, {
    headers: liveHeaders(),
    multipart: {
      dataset_id: datasetId,
      parser_backend: 'basic',
      chunk_strategy: chunkStrategy,
      file: {
        name: filename,
        mimeType: 'text/markdown',
        buffer: Buffer.from(content, 'utf8'),
      },
    },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { id?: string; document_id?: string }
  const documentId = String(body.id || body.document_id || '')
  expect(documentId).toMatch(/\S/)
  return documentId
}

async function fetchLiveDocument(
  request: APIRequestContext,
  documentId: string
): Promise<LiveDocument> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/documents/${documentId}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as LiveDocument
}

async function waitForLiveDocumentStatus(
  request: APIRequestContext,
  documentId: string,
  expectedStatus: string
): Promise<void> {
  await expect
    .poll(async () => {
      const current = await fetchLiveDocument(request, documentId)
      return String(current.status || '').toLowerCase()
    }, {
      timeout: 180_000,
    })
    .toBe(expectedStatus)
}

function getActivePipelineHash(document: LiveDocument): string {
  const metadata =
    document.metadata && typeof document.metadata === 'object'
      ? (document.metadata as Record<string, unknown>)
      : {}
  return String(
    document.active_pipeline_hash ||
      metadata['active_pipeline_hash'] ||
      metadata['pipeline_hash'] ||
      ''
  ).trim()
}

async function extractLiveKg(
  request: APIRequestContext,
  documentId: string
): Promise<void> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/kg/documents/${documentId}/extract?replace_existing=true&extract_relations=false&extract_skills=false&extraction_backend=heuristic`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
}

async function fetchLiveKgStats(
  request: APIRequestContext,
  query: string
): Promise<LiveKgStats> {
  const separator = query.startsWith('?') ? '' : '?'
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/kg/stats${separator}${query}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as {
    events?: number
    entities?: number
    links?: number
  }
  return {
    events: Number(body.events || 0),
    entities: Number(body.entities || 0),
    links: Number(body.links || 0),
  }
}

async function waitForScopedKgStats(
  request: APIRequestContext,
  {
    documentId,
    pipelineHash,
  }: {
    documentId: string
    pipelineHash: string
  }
): Promise<LiveKgStats> {
  let last: LiveKgStats = { events: 0, entities: 0, links: 0 }
  await expect
    .poll(async () => {
      last = await fetchLiveKgStats(
        request,
        `document_ids=${encodeURIComponent(documentId)}&pipeline_hash=${encodeURIComponent(pipelineHash)}`
      )
      return last.events > 0 || last.entities > 0
    }, {
      timeout: 180_000,
    })
    .toBe(true)
  return last
}

async function compareLiveSnapshots(
  request: APIRequestContext,
  {
    datasetId,
    pipelineHashA,
    pipelineHashB,
  }: {
    datasetId: string
    pipelineHashA: string
    pipelineHashB: string
  }
): Promise<LiveSnapshotDiff> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/kg/snapshots/compare?pipeline_hash_a=${encodeURIComponent(pipelineHashA)}&pipeline_hash_b=${encodeURIComponent(pipelineHashB)}&dataset_id=${encodeURIComponent(datasetId)}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as LiveSnapshotDiff
}

function diffMagnitude(diff: LiveSnapshotDiff): number {
  const counts = [
    diff.node_diff?.added_count,
    diff.node_diff?.removed_count,
    diff.node_diff?.changed_count,
    diff.edge_diff?.added_count,
    diff.edge_diff?.removed_count,
    diff.edge_diff?.changed_count,
  ]
  return counts.reduce((sum, value) => sum + Math.max(0, Number(value || 0)), 0)
}

test.describe('live graph snapshots workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('compares two real dataset-scoped snapshot hashes on the deployed snapshots page', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-graph-snapshots-${Date.now()}`
    const docs = [
      {
        filename: `snapshot-a-${Date.now()}.md`,
        chunkStrategy: 'langchain_recursive',
        content:
          '# Atlas Acquisition\n\nAtlas Systems acquired Beacon Labs. Mira Chen led the integration workstream and kept Project Atlas stable.',
      },
      {
        filename: `snapshot-b-${Date.now()}.md`,
        chunkStrategy: 'semantic_sentence',
        content:
          '# Orion Migration\n\nMira Chen coordinated the Orion billing service migration, and Beacon Labs engineers reviewed the cutover checklist.',
      },
    ]

    let datasetId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentIds: string[] = []
      for (const doc of docs) {
        const documentId = await uploadCompletedDocument(request, {
          datasetId,
          filename: doc.filename,
          content: doc.content,
          chunkStrategy: doc.chunkStrategy,
        })
        documentIds.push(documentId)
      }

      const pipelineHashes: string[] = []
      for (const documentId of documentIds) {
        await waitForLiveDocumentStatus(request, documentId, 'completed')
        const detail = await fetchLiveDocument(request, documentId)
        const pipelineHash = getActivePipelineHash(detail)
        expect(pipelineHash).toMatch(/\S/)
        pipelineHashes.push(pipelineHash)
        await extractLiveKg(request, documentId)
      }

      expect(new Set(pipelineHashes).size).toBe(2)
      await waitForScopedKgStats(request, {
        documentId: documentIds[0],
        pipelineHash: pipelineHashes[0],
      })
      await waitForScopedKgStats(request, {
        documentId: documentIds[1],
        pipelineHash: pipelineHashes[1],
      })

      const diff = await compareLiveSnapshots(request, {
        datasetId,
        pipelineHashA: pipelineHashes[0],
        pipelineHashB: pipelineHashes[1],
      })
      expect(diffMagnitude(diff)).toBeGreaterThan(0)

      await page.goto(`/graph/snapshots?dataset_id=${encodeURIComponent(datasetId)}`, {
        waitUntil: 'networkidle',
      })
      await expect(
        page.getByRole('heading', { name: '图谱快照' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await page.getByRole('button', { name: '手动填写' }).click()
      await page
        .getByPlaceholder('手动填写快照 A 哈希')
        .fill(pipelineHashes[0])
      await page
        .getByPlaceholder('手动填写快照 B 哈希')
        .fill(pipelineHashes[1])

      await page.getByRole('button', { name: '后端对比' }).click()
      await expect(page.getByText('后端对比完成')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('还没有对比结果')).toHaveCount(0)
      await expect(page.getByText('节点变化')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('属性变化')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('新增关系')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('删除关系')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      expect(pageErrors).toEqual([])
    } finally {
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })
})
