import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type LiveDocument = {
  id?: string
  status?: string
  metadata?: Record<string, unknown>
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
      description: 'Playwright live quarantine verification dataset.',
      permission: 'all_team_members',
      default_parser_backend: 'auto',
      default_chunk_strategy: 'langchain_recursive',
      pipeline: {
        governance_enabled: true,
        persist_parsed_content: true,
        persist_parsed_content_max_chars: 200000,
        chunk_size: 1200,
        chunk_overlap: 120,
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

async function uploadQuarantinedDocument(
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
  const pipeline = {
    governance_enabled: true,
    chunk_vector_enabled: false,
    bm25_index_enabled: false,
    governance_drop_outline_only: true,
    governance_drop_outline_min_content_chars: 50,
    governance_drop_outline_max_heading_ratio: 0.8,
    governance_drop_low_density: true,
    governance_drop_low_density_threshold: 0.3,
    governance_quarantine_on_drop: true,
  }

  const response = await request.post(`${apiBaseUrl()}/api/v1/documents/upload`, {
    headers: liveHeaders(),
    multipart: {
      dataset_id: datasetId,
      parser_backend: 'basic',
      chunk_strategy: 'langchain_recursive',
      pipeline: JSON.stringify(pipeline),
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

async function fetchLiveDocumentStatusCode(
  request: APIRequestContext,
  documentId: string
): Promise<number> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/documents/${documentId}`,
    { headers: liveHeaders() }
  )
  return response.status()
}

async function waitForLiveDocumentStatus(
  request: APIRequestContext,
  documentId: string,
  expectedStatus: string
): Promise<LiveDocument> {
  let current: LiveDocument | null = null

  await expect
    .poll(async () => {
      current = await fetchLiveDocument(request, documentId)
      return String(current.status || '').toLowerCase()
    }, {
      timeout: 180_000,
    })
    .toBe(expectedStatus)

  if (!current) {
    throw new Error(`Document ${documentId} was not available after polling`)
  }

  return current
}

test.describe('live quarantine surfaces', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('reviews a real quarantined document through the quarantine center UI', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-quarantine-${Date.now()}`
    const filename = `outline-only-${Date.now()}.md`
    const content = '# Executive Summary\n\n## Agenda\n\n## Risks\n\n## Next Steps\n'

    let datasetId = ''
    let documentId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      documentId = await uploadQuarantinedDocument(request, {
        datasetId,
        filename,
        content,
      })

      await waitForLiveDocumentStatus(request, documentId, 'quarantined')

      await page.goto(
        `/knowledge/quarantine?datasetId=${encodeURIComponent(datasetId)}`,
        { waitUntil: 'networkidle' }
      )
      await expect(
        page.getByRole('heading', { name: '隔离审核中心' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      const fileButton = page.getByRole('button', { name: new RegExp(filename) })
      await expect(fileButton).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await fileButton.click()

      const dialog = page.getByRole('dialog')
      await expect(
        dialog.getByRole('heading', { name: filename })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(dialog.getByText('待审核')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const reviewButton = dialog.getByRole('button', { name: '标记为已解决' })
      await reviewButton.click()

      await expect
        .poll(async () => {
          const current = await fetchLiveDocument(request, documentId)
          const metadata = (current.metadata || {}) as {
            user?: { quarantine_reviewed?: boolean }
          }
          return Boolean(metadata.user?.quarantine_reviewed)
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(true)

      await expect(dialog.getByText('已解决', { exact: true }).first()).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(reviewButton).toBeDisabled()
      expect(pageErrors).toEqual([])
    } finally {
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })

  test('deletes a real quarantined document through the quarantine center UI', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-quarantine-delete-${Date.now()}`
    const filename = `outline-delete-${Date.now()}.md`
    const content = '# Executive Summary\n\n## Agenda\n\n## Risks\n\n## Next Steps\n'

    let datasetId = ''
    let documentId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      documentId = await uploadQuarantinedDocument(request, {
        datasetId,
        filename,
        content,
      })

      await waitForLiveDocumentStatus(request, documentId, 'quarantined')

      await page.goto(
        `/knowledge/quarantine?datasetId=${encodeURIComponent(datasetId)}`,
        { waitUntil: 'networkidle' }
      )
      const fileButton = page.getByRole('button', { name: new RegExp(filename) })
      await expect(fileButton).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await fileButton.click()

      const dialog = page.getByRole('dialog')
      await expect(
        dialog.getByRole('heading', { name: filename })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      const footer = dialog.locator('div.border-t').last()
      await footer.locator('button').last().click()

      const confirm = page.getByRole('alertdialog')
      await expect(
        confirm.getByText('确定物理删除？')
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await confirm.getByRole('button', { name: '物理删除' }).click()

      await expect
        .poll(async () => fetchLiveDocumentStatusCode(request, documentId), {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(404)

      await expect(fileButton).toHaveCount(0)
      documentId = ''
      expect(pageErrors).toEqual([])
    } finally {
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })
})
