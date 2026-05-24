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

type SimilarityCollection = {
  id?: string
  label?: string
  kind?: string
  count?: number
  meta?: {
    dataset_id?: string
    dataset_name?: string
  }
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
      description: 'Playwright live similarity workbench dataset.',
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
        kg_enabled: false,
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

async function listSimilarityCollections(
  request: APIRequestContext
): Promise<SimilarityCollection[]> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/ragviz/similarity/collections`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as {
    collections?: SimilarityCollection[]
  }
  return Array.isArray(body.collections) ? body.collections : []
}

async function preflightSimilarityCalculate(
  request: APIRequestContext,
  {
    xCollection,
    yCollection,
  }: {
    xCollection: string
    yCollection: string
  }
): Promise<void> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/ragviz/similarity/calculate`,
    {
      headers: {
        ...liveHeaders(),
        'Content-Type': 'application/json',
      },
      data: {
        x_collection: xCollection,
        y_collection: yCollection,
        x_max_items: 30,
        y_max_items: 30,
      },
    }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as {
    success?: boolean
    result?: { stats?: { total_pairs?: number } }
  }
  expect(body.success).toBe(true)
  expect(Number(body.result?.stats?.total_pairs || 0)).toBeGreaterThan(0)
}

test.describe('live similarity workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('calculates a real similarity heatmap for a disposable dataset on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-similarity-${Date.now()}`
    const filename = `similarity-${Date.now()}.md`
    const markdown = [
      '# Similarity Probe',
      '',
      'Token SIM-ANCHOR belongs only to this similarity workbench document.',
      'Owner: Selene Matrix.',
      '',
    ].join('\n')

    let datasetId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename,
        content: markdown,
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')

      let datasetCollectionId = ''
      let datasetCollectionLabel = ''
      await expect
        .poll(async () => {
          const collections = await listSimilarityCollections(request)
          const found = collections.find(
            (item) =>
              String(item.kind || '') === 'dataset_chunks' &&
              String(item.meta?.dataset_id || '') === datasetId
          )
          datasetCollectionId = String(found?.id || '')
          datasetCollectionLabel = String(found?.label || '')
          return datasetCollectionId
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toMatch(/\S/)

      await preflightSimilarityCalculate(request, {
        xCollection: datasetCollectionId,
        yCollection: datasetCollectionId,
      })

      await page.goto('/knowledge/similarity', { waitUntil: 'networkidle' })
      await expect(page.getByRole('heading', { name: '跨集合相似度热力图' })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const selects = page.locator('select')
      await expect(selects.nth(0)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await selects.nth(0).selectOption(datasetCollectionId)
      await selects.nth(1).selectOption(datasetCollectionId)

      await page.getByRole('button', { name: '计算相似度' }).click()
      await expect(page.getByText(/成功计算\s+1\s+个相似度矩阵/)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('平均相似度')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('最高相似度')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('高相似占比')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(
        page.getByText(`${datasetCollectionLabel}（X 轴）`)
      ).toBeVisible({
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
