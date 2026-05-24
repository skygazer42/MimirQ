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

type DatasetTableAsset = {
  table_id?: string
  row_count?: number
  col_count?: number
  document_filename?: string | null
  columns?: Array<{ name?: string; dtype?: string | null }>
  sample_rows?: Array<Record<string, unknown>>
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
      description: 'Playwright live dataset tables proof.',
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
        kg_enabled: false,
        event_vector_enabled: false,
        entity_vector_enabled: false,
        table_store_enabled: true,
        table_store_auto_route: false,
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
        mimeType: 'text/csv',
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

async function listTables(
  request: APIRequestContext,
  datasetId: string
): Promise<DatasetTableAsset[]> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}/tables?skip=0&limit=200`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { items?: DatasetTableAsset[] }
  return Array.isArray(body.items) ? body.items : []
}

async function getTable(
  request: APIRequestContext,
  datasetId: string,
  tableId: string
): Promise<DatasetTableAsset> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}?include_columns=true&include_sample_rows=true`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as DatasetTableAsset
}

test.describe('live dataset tables page', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('renders a real table asset and its columns/sample rows on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const uniqueSuffix = `${Date.now()}`
    const datasetName = `playwright-dataset-tables-${uniqueSuffix}`
    const filename = `tables-${uniqueSuffix}.csv`
    const csv = [
      'region,amount,status',
      'APAC,1200,review',
      'EMEA,800,done',
    ].join('\n')

    let datasetId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename,
        content: csv,
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')

      let tableId = ''
      await expect
        .poll(async () => {
          const items = await listTables(request, datasetId)
          tableId = String(items[0]?.table_id || '')
          return tableId
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toMatch(/\S/)

      const tableDetail = await getTable(request, datasetId, tableId)
      expect(Number(tableDetail.row_count || 0)).toBe(2)
      expect(Number(tableDetail.col_count || 0)).toBe(3)

      await page.goto(`/datasets/${encodeURIComponent(datasetId)}/tables`, {
        waitUntil: 'networkidle',
      })
      await expect(
        page.getByRole('heading', { name: '表格 / TAG' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await expect(page.getByText(datasetName)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('表格列表')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const tableButton = page.getByRole('button', { name: new RegExp(tableId) }).first()
      await expect(tableButton).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await tableButton.click()

      await expect(page.getByText('表格信息')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('rows: 2')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('cols: 3')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('Columns')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      const columnsPanel = page
        .locator('div')
        .filter({ hasText: 'Columns' })
        .first()
      await expect(columnsPanel.getByText('region', { exact: true })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(columnsPanel.getByText('amount', { exact: true })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(columnsPanel.getByText('status', { exact: true })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('Sample Rows')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      const sampleRowsPanel = page
        .locator('div')
        .filter({ hasText: 'Sample Rows' })
        .first()
      await expect(sampleRowsPanel.getByText('APAC')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(sampleRowsPanel.getByText('review')).toBeVisible({
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
