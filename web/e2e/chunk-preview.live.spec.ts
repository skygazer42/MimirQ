import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type LiveDocument = {
  id?: string
  status?: string
  filename?: string
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
      description: 'Playwright live chunk preview dataset.',
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

async function listDatasetDocuments(
  request: APIRequestContext,
  datasetId: string
): Promise<LiveDocument[]> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/documents/?limit=50&dataset_id=${encodeURIComponent(datasetId)}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { items?: LiveDocument[] }
  return body.items || []
}

test.describe('live chunk preview workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('loads a real dataset document and auto-previews chunk statistics in the chunk preview workbench', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-chunk-preview-${Date.now()}`
    const filename = `chunk-preview-${Date.now()}.md`
    const markdown = [
      '# Chunk Preview Workbench',
      '',
      'This document is long enough to exercise chunk preview with real backend data.',
      '',
      'Paragraph one explains parser service health and coverage metrics.',
      '',
      'Paragraph two explains overlap waste and retrieval grounding.',
      '',
      'Paragraph three repeats enough structure to keep the preview non-trivial.',
      '',
    ]
      .join('\n')
      .repeat(8)

    let datasetId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename,
        content: markdown,
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')

      await page.goto(
        `/chunk-preview?dataset_id=${encodeURIComponent(datasetId)}`,
        { waitUntil: 'networkidle' }
      )
      await expect(
        page.getByRole('heading', { name: '切片预览' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      const fileButton = page.getByRole('button', {
        name: `选择文件：${filename}`,
      })
      await expect(fileButton).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await expect(page.getByText(/个切块/)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('预览统计')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('切片数')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('覆盖率')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('重叠浪费')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      expect(pageErrors).toEqual([])
    } finally {
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })

  test('submits a live chunk preview into the dataset through the deployed workbench', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-chunk-ingest-${Date.now()}`
    const filename = `chunk-ingest-${Date.now()}.md`
    const markdown = [
      '# Chunk Preview Submit',
      '',
      'This document exists to validate the confirm-ingest path from the chunk preview workbench.',
      '',
      'Paragraph one gives enough content for multiple chunk calculations when repeated.',
      '',
      'Paragraph two keeps the backend preview non-trivial and citation-friendly.',
      '',
    ]
      .join('\n')
      .repeat(10)

    let datasetId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename,
        content: markdown,
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')

      const beforeDocs = await listDatasetDocuments(request, datasetId)
      expect(beforeDocs.length).toBe(1)

      await page.goto(
        `/chunk-preview?dataset_id=${encodeURIComponent(datasetId)}`,
        { waitUntil: 'networkidle' }
      )
      await expect(
        page.getByRole('heading', { name: '切片预览' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await expect(page.getByText(/个切块/)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const submitButton = page.getByRole('button', { name: '确认入库' })
      await expect(submitButton).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await submitButton.click()

      await expect(
        page.getByRole('button', { name: '已完成' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await expect
        .poll(async () => (await listDatasetDocuments(request, datasetId)).length, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBeGreaterThanOrEqual(2)

      expect(pageErrors).toEqual([])
    } finally {
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })
})
