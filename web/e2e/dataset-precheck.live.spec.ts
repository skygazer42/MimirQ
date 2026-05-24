import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type PrecheckScanRun = {
  id?: string
  status?: string
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
      description: 'Playwright live dataset precheck proof.',
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
  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

async function uploadBatchPrecheckOnly(
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
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/documents/upload-batch`,
    {
      headers: liveHeaders(),
      multipart: {
        dataset_id: datasetId,
        parser_backend: 'basic',
        chunk_strategy: 'langchain_recursive',
        precheck_only: 'true',
        files: {
          name: filename,
          mimeType: 'text/markdown',
          buffer: Buffer.from(content, 'utf8'),
        },
      },
    }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { precheck_scan_run_id?: string }
  const scanRunId = String(body.precheck_scan_run_id || '')
  expect(scanRunId).toMatch(/\S/)
  return scanRunId
}

async function getPrecheckScanRun(
  request: APIRequestContext,
  datasetId: string,
  scanRunId: string
): Promise<PrecheckScanRun> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}/precheck/scan-runs/${scanRunId}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as PrecheckScanRun
}

async function waitForPrecheckScanStatus(
  request: APIRequestContext,
  datasetId: string,
  scanRunId: string,
  expectedStatus: string
): Promise<void> {
  await expect
    .poll(async () => {
      const current = await getPrecheckScanRun(request, datasetId, scanRunId)
      return String(current.status || '').toLowerCase()
    }, {
      timeout: 180_000,
    })
    .toBe(expectedStatus)
}

test.describe('live dataset precheck page', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('shows a real precheck scan summary and representative samples on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const uniqueSuffix = `${Date.now()}`
    const datasetName = `playwright-precheck-${uniqueSuffix}`
    const filename = `precheck-${uniqueSuffix}.md`
    const content = [
      '# Precheck Batch',
      '',
      `Token PRECHECK-BATCH-${uniqueSuffix} belongs only to this file.`,
    ].join('\n')

    let datasetId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const scanRunId = await uploadBatchPrecheckOnly(request, {
        datasetId,
        filename,
        content,
      })
      await waitForPrecheckScanStatus(request, datasetId, scanRunId, 'completed')

      await page.goto(`/datasets/${encodeURIComponent(datasetId)}/precheck`, {
        waitUntil: 'networkidle',
      })
      await expect(
        page.getByRole('heading', { name: '预检扫描（未入库）' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await expect(page.getByText(datasetName)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('文件总数')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('代表性样本（抽样）')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const samplePanel = page
        .locator('div')
        .filter({ hasText: '代表性样本（抽样）' })
        .filter({ hasText: '问题分桶样本' })
        .first()
      await samplePanel.getByRole('button', { name: '加载' }).first().click()

      await expect(page.getByRole('table', { name: '预检代表性样本' })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText(filename, { exact: true })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('short_text')).toBeVisible({
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
