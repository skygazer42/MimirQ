import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type UsageSummary = {
  total_assistant_tokens?: number
  total_assistant_messages?: number
}

type UsageCostSummary = {
  total_llm_total_tokens?: number
}

type TenantQuotaSummary = {
  documents?: { used?: number }
  qps?: { enabled?: boolean; rps?: number }
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

function formatNumber(value: number | string | null | undefined): string {
  if (value == null || value === '') return '0'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n.toLocaleString()
}

async function fetchUsageSummary(
  request: APIRequestContext,
  windowDays = 7
): Promise<UsageSummary> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/usage/chat/tokens/summary?window_days=${windowDays}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as UsageSummary
}

async function fetchUsageCostSummary(
  request: APIRequestContext,
  windowDays = 7
): Promise<UsageCostSummary> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/usage/chat/cost/summary?window_days=${windowDays}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as UsageCostSummary
}

async function fetchTenantQuotaSummary(
  request: APIRequestContext
): Promise<TenantQuotaSummary> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/usage/tenant/quotas`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as TenantQuotaSummary
}

test.describe('live usage page', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('loads live usage totals and tenant quota raw JSON on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const summary = await fetchUsageSummary(request, 7)
    const cost = await fetchUsageCostSummary(request, 7)
    const quota = await fetchTenantQuotaSummary(request)

    await page.goto('/usage', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: '用量/配额' })
    ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
    await expect(
      page.getByRole('heading', { name: '租户级配额状态' })
    ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
    const quotaHeading = page.getByRole('heading', { name: '租户级配额状态' })
    await quotaHeading.scrollIntoViewIfNeeded()

    await expect(
      page.getByText(formatNumber(summary.total_assistant_tokens)).first()
    ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
    await expect(
      page.getByText(formatNumber(cost.total_llm_total_tokens)).first()
    ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
    await expect(
      page.getByText(formatNumber(summary.total_assistant_messages)).first()
    ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

    const rawToggle = page.getByText('查看原始响应').first()
    await expect(rawToggle).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await rawToggle.click()
    const detailsToggle = page.getByLabel('复制租户配额 JSON')
    await expect(detailsToggle).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    const rawPanel = page.locator('pre').last()
    await expect(rawPanel).toContainText('"documents"', {
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(rawPanel).toContainText('"storage"', {
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(rawPanel).toContainText('"embedding_chars"', {
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(rawPanel).toContainText('"qps"', {
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    const quotaNumber =
      quota.documents?.used != null
        ? formatNumber(quota.documents.used)
        : quota.qps?.enabled && Number.isFinite(Number(quota.qps.rps))
          ? formatNumber(quota.qps.rps)
          : '0'
    await expect(page.getByText(quotaNumber).first()).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    expect(pageErrors).toEqual([])
  })
})
