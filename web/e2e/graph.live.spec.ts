import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type LiveDocument = {
  id?: string
  status?: string
}

type LiveKgStats = {
  events: number
  entities: number
  links: number
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
      description: 'Playwright live graph dataset.',
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
  }: {
    datasetId: string
    filename: string
    content: string
  }
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/documents/upload`, {
    headers: liveHeaders(),
    multipart: {
      dataset_id: datasetId,
      parser_backend: 'basic',
      chunk_strategy: 'langchain_recursive',
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

function buildRepeatedQuery(key: string, values: string[]): string {
  return values
    .map((value) => String(value || '').trim())
    .filter(Boolean)
    .map((value) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    .join('&')
}

test.describe('live graph workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('loads a real dataset-scoped graph with exact scoped KG counts on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-graph-${Date.now()}`
    const docs = [
      {
        filename: `atlas-${Date.now()}.md`,
        content:
          '# Atlas Acquisition\n\nAtlas Systems acquired Beacon Labs. Mira Chen led the integration workstream.',
      },
      {
        filename: `orion-${Date.now()}.md`,
        content:
          '# Orion Migration\n\nMira Chen coordinated the Orion billing service migration with Beacon Labs engineers.',
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
        })
        documentIds.push(documentId)
      }

      for (const documentId of documentIds) {
        await waitForLiveDocumentStatus(request, documentId, 'completed')
        await extractLiveKg(request, documentId)
      }

      const datasetStats = await fetchLiveKgStats(
        request,
        `dataset_id=${encodeURIComponent(datasetId)}`
      )
      const documentStats = await fetchLiveKgStats(
        request,
        buildRepeatedQuery('document_ids', documentIds)
      )
      expect(datasetStats).toEqual(documentStats)
      const expectedStats = datasetStats
      const expectedStatsLabel = `E:${expectedStats.events} N:${expectedStats.entities} L:${expectedStats.links}`

      await page.goto(`/graph?dataset_id=${encodeURIComponent(datasetId)}`, {
        waitUntil: 'networkidle',
      })
      await expect(
        page.getByRole('heading', { name: '知识图谱' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await expect(page.getByText(expectedStatsLabel)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('语义索引')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByRole('heading', { name: '节点' })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await expect(page.getByRole('button', { name: /聚焦节点：/ }).first()).toBeVisible({
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
