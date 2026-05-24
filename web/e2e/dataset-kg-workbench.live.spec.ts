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

type KGStatsResponse = {
  events?: number
  entities?: number
  links?: number
}

type KGGraphNode = {
  id?: string
  label?: string
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
      description: 'Playwright live dataset KG workbench proof.',
      permission: 'all_team_members',
      default_parser_backend: 'basic',
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

async function extractKg(
  request: APIRequestContext,
  documentId: string
): Promise<void> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/kg/documents/${documentId}/extract?async=false`,
    {
      headers: liveHeaders(),
    }
  )
  expect(response.ok()).toBe(true)
}

async function getKgStats(
  request: APIRequestContext,
  documentIds: string[]
): Promise<KGStatsResponse> {
  const url = new URL(`${apiBaseUrl()}/api/v1/kg/stats`)
  documentIds.forEach((id) => url.searchParams.append('document_ids', id))
  const response = await request.get(url.toString(), {
    headers: liveHeaders(),
  })
  expect(response.ok()).toBe(true)
  return (await response.json()) as KGStatsResponse
}

async function searchKgNodes(
  request: APIRequestContext,
  {
    query,
    documentIds,
  }: {
    query: string
    documentIds: string[]
  }
): Promise<KGGraphNode[]> {
  const url = new URL(`${apiBaseUrl()}/api/v1/kg/graph/search`)
  url.searchParams.set('q', query)
  url.searchParams.set('kind', 'entity')
  url.searchParams.set('limit', '20')
  documentIds.forEach((id) => url.searchParams.append('document_ids', id))
  const response = await request.get(url.toString(), {
    headers: liveHeaders(),
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as KGGraphNode[]
  return Array.isArray(body) ? body : []
}

test.describe('live dataset KG workbench page', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('renders a real dataset-scoped KG preview and quick search on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const uniqueSuffix = `${Date.now()}`
    const datasetName = `playwright-dataset-kg-${uniqueSuffix}`
    const queryName = 'Mira Chen'
    const uniqueToken = `KG-PROBE-${uniqueSuffix}`
    const fileA = `dataset-kg-a-${uniqueSuffix}.md`
    const fileB = `dataset-kg-b-${uniqueSuffix}.md`
    const docA = [
      '# KG Probe A',
      '',
      `Project Atlas acquired Blue Harbor.`,
      `${queryName} leads the Atlas integration program.`,
      `Token ${uniqueToken} belongs only to this KG probe dataset.`,
    ].join('\n')
    const docB = [
      '# KG Probe B',
      '',
      `${queryName} also oversees the Orion billing service.`,
      'Blue Harbor supplies billing data to Orion.',
    ].join('\n')

    let datasetId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentIds = await Promise.all([
        uploadCompletedDocument(request, {
          datasetId,
          filename: fileA,
          content: docA,
        }),
        uploadCompletedDocument(request, {
          datasetId,
          filename: fileB,
          content: docB,
        }),
      ])
      await Promise.all(
        documentIds.map((documentId) =>
          waitForLiveDocumentStatus(request, documentId, 'completed')
        )
      )
      await Promise.all(documentIds.map((documentId) => extractKg(request, documentId)))

      await expect
        .poll(async () => {
          const stats = await getKgStats(request, documentIds)
          return Number(stats.entities || 0)
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBeGreaterThan(0)

      const preflightSearch = await searchKgNodes(request, {
        query: queryName,
        documentIds,
      })
      expect(preflightSearch.some((node) => String(node.label || '').includes(queryName))).toBe(true)

      await page.goto(`/datasets/${encodeURIComponent(datasetId)}/kg`, {
        waitUntil: 'networkidle',
      })
      await expect(
        page.getByRole('heading', { name: `KG Workbench · ${datasetName}` })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await expect(page.getByText('1. Scope docs')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '全选已加载' }).click()
      await expect(page.getByText('当前范围：').locator('..')).toContainText('2', {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '加载预览' }).click()
      await expect(page.getByText('entities=')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('events=')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('links=')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const searchPanel = page.locator('div').filter({ hasText: '4. Quick KG search' }).first()
      const searchInput = searchPanel.getByPlaceholder('Search entity/event…')
      await searchInput.fill(queryName)
      await searchInput.press('Enter')
      const searchResultButton = searchPanel.getByRole('button', {
        name: /Mira Chen/,
      }).first()
      await expect(searchResultButton).toBeVisible({
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
