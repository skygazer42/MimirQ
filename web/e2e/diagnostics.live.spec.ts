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

type LivePromptPreviewResponse = {
  query_for_retrieval?: string
  prompt_text?: string
  citations?: Array<Record<string, unknown>>
  metrics?: Record<string, unknown>
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
      description: 'Playwright live diagnostics dataset.',
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

async function fetchPromptPreview(
  request: APIRequestContext,
  {
    datasetId,
    query,
  }: {
    datasetId: string
    query: string
  }
): Promise<LivePromptPreviewResponse> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/rag/prompt-preview`, {
    headers: liveHeaders(),
    data: {
      query,
      dataset_id: datasetId,
      structured_output: false,
    },
  })
  expect(response.ok()).toBe(true)
  return (await response.json()) as LivePromptPreviewResponse
}

async function fetchEmbeddingDrift(
  request: APIRequestContext,
  {
    datasetId,
  }: {
    datasetId: string
  }
): Promise<Record<string, unknown>> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/observability/embedding-drift/snapshot?dataset_id=${encodeURIComponent(datasetId)}&sample_n=50&drift_threshold=0.05`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as Record<string, unknown>
}

test.describe('live diagnostics center', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('runs real prompt-preview and embedding-drift probes from the deployed diagnostics page', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-diagnostics-${Date.now()}`
    const filename = `diagnostics-${Date.now()}.md`
    const uniqueToken = `DIAGNOSTICS-ANCHOR-${Date.now()}`
    const query = `Which token belongs only to this diagnostics document: ${uniqueToken}?`
    const markdown = [
      '# Diagnostics Center',
      '',
      `Token ${uniqueToken} belongs only to this diagnostics document.`,
      '',
      'The diagnostics preview should retrieve this anchor and expose it in prompt preview output.',
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

      const preview = await fetchPromptPreview(request, { datasetId, query })
      expect(Array.isArray(preview.citations)).toBe(true)
      expect((preview.citations || []).length).toBeGreaterThan(0)
      expect(String(preview.prompt_text || '')).toContain(uniqueToken)

      const driftSnapshot = await fetchEmbeddingDrift(request, { datasetId })
      expect(Object.keys(driftSnapshot).length).toBeGreaterThan(0)

      await page.goto('/diagnostics', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '诊断中心' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await page.locator('#diagnostics-dataset').click()
      await page.getByRole('option', { name: new RegExp(datasetName) }).click()

      const queryBox = page.locator('textarea').first()
      await queryBox.fill(query)

      await page.getByRole('button', { name: '运行 RAG 预览' }).click()
      await expect(page.getByText('RAG 预览完成')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const rawSummary = page.getByText('查看原始响应').first()
      await rawSummary.click()
      const rawPre = page.locator('details pre').last()
      await expect(rawPre).toContainText(datasetId, {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(rawPre).toContainText('"rag_preview": {', {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(rawPre).toContainText(uniqueToken, {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '漂移检查' }).click()
      await expect(page.getByText('漂移检查完成')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(rawPre).toContainText('"embedding_drift": {', {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(rawPre).not.toContainText('"embedding_drift": null')
      await expect(rawPre).toContainText('"drift_rate"', {
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
