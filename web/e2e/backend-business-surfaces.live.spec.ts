import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 240_000

type DatasetItem = {
  id?: string
  name?: string
}

type ConversationItem = {
  id?: string
}

function apiBaseUrl(): string {
  return String(process.env.PLAYWRIGHT_LIVE_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')
}

function liveHeaders(): Record<string, string> {
  return {
    'X-Tenant-ID': process.env.PLAYWRIGHT_LIVE_TENANT_ID || process.env.NEXT_PUBLIC_TENANT_ID || DEFAULT_TENANT_ID,
    'X-User-ID': process.env.PLAYWRIGHT_LIVE_USER_ID || process.env.NEXT_PUBLIC_USER_ID || DEFAULT_USER_ID,
  }
}

async function installLiveAuth(page: Page) {
  const headers = liveHeaders()
  await page.addInitScript(({ tenantId, userId }) => {
    window.localStorage.setItem('mimirq_tenant_id', tenantId)
    window.localStorage.setItem('mimirq_user_id', userId)
  }, {
    tenantId: headers['X-Tenant-ID'],
    userId: headers['X-User-ID'],
  })
}

async function revealRawResponse(page: Page): Promise<void> {
  const rawResponse = page.getByText('查看原始响应').last()
  await expect(rawResponse).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
  await rawResponse.click()
}

async function firstDatasetId(request: APIRequestContext): Promise<string> {
  const response = await request.get(`${apiBaseUrl()}/api/v1/datasets/?limit=1`, { headers: liveHeaders() })
  if (!response.ok()) return ''
  const payload = (await response.json()) as { items?: DatasetItem[] }
  return String(payload.items?.[0]?.id || '')
}

async function firstConversationId(request: APIRequestContext): Promise<string> {
  const response = await request.get(`${apiBaseUrl()}/api/v1/chat/conversations?limit=1`, { headers: liveHeaders() })
  if (!response.ok()) return ''
  const payload = (await response.json()) as { items?: ConversationItem[] }
  return String(payload.items?.[0]?.id || '')
}

test.describe('live backend business surfaces', () => {
  test.skip(!LIVE_BACKEND_ENABLED, 'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend')

  test('loads business pages that host newly aligned backend interfaces', async ({ page, request }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    await page.goto('/settings', { waitUntil: 'networkidle' })
    await expect(page.getByText('行业规则与查询改写')).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
    await expect(page.getByText('RTBF 级联删除闭环')).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
    await page.getByRole('button', { name: '改写预览' }).click()
    await revealRawResponse(page)
    await expect(page.getByText('mimirq.industry_rules_preview.v1')).toBeVisible({ timeout: 30_000 })

    await page.goto('/graph', { waitUntil: 'networkidle' })
    await expect(page.getByRole('button', { name: /网络分析/ })).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

    const datasetId = await firstDatasetId(request)
    if (datasetId) {
      await page.goto(`/datasets/${datasetId}/profile`, { waitUntil: 'networkidle' })
      await expect(page.getByText('Dataset Analysis / 入库后分析闭环')).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await page.getByRole('button', { name: '摘要' }).click()
      await revealRawResponse(page)
      await expect(page.getByText('mimirq.dataset_analysis.summary.v1')).toBeVisible({ timeout: 30_000 })
    }

    const conversationId = await firstConversationId(request)
    if (conversationId) {
      await page.goto(`/history?id=${conversationId}`, { waitUntil: 'networkidle' })
      await expect(page.getByText('历史记录')).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      const lineageAction = page.getByRole('button', { name: '答案血缘' }).first()
      if (await lineageAction.isVisible().catch(() => false)) {
        await lineageAction.click()
        await expect(page.getByRole('heading', { name: 'Answer Lineage' })).toBeVisible()
      }
    }

    expect(pageErrors).toEqual([])
  })
})
