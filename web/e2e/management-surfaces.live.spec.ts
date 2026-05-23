import { expect, test, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 240_000

async function installLiveAuth(page: Page) {
  const tenantId =
    process.env.PLAYWRIGHT_LIVE_TENANT_ID ||
    process.env.NEXT_PUBLIC_TENANT_ID ||
    DEFAULT_TENANT_ID
  const userId =
    process.env.PLAYWRIGHT_LIVE_USER_ID ||
    process.env.NEXT_PUBLIC_USER_ID ||
    DEFAULT_USER_ID

  await page.addInitScript(({ tenantId, userId }) => {
    window.localStorage.setItem('mimirq_tenant_id', tenantId)
    window.localStorage.setItem('mimirq_user_id', userId)
  }, { tenantId, userId })
}

test.describe('live management surfaces', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('loads management pages that depend on real backend-admin surfaces', async ({
    page,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    await page.goto('/prompts', { waitUntil: 'networkidle' })
    await expect(page.getByText('提示词模板')).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(page.getByText('模板管理')).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    await page.goto('/reports', { waitUntil: 'networkidle' })
    await expect(page.getByText('数据报告与审计概览')).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(page.getByText('报告状态')).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    await page.goto('/evaluations', { waitUntil: 'networkidle' })
    await expect(page.getByText('评测中心')).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(page.getByRole('button', { name: '对话评测' })).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(
      page.getByRole('button', { name: 'Golden 评测集' })
    ).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    await page.goto('/usage', { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { name: '用量/配额' })).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(page.getByRole('heading', { name: '租户级配额状态' })).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    await page.goto('/audit', { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    await expect(page.getByText('按后端审计日志展示时间、操作者、事件名称、资源/租户与操作明细。')).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    await page.goto('/access-review', { waitUntil: 'networkidle' })
    await expect(page).toHaveURL(/\/audit/)
    await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    expect(pageErrors).toEqual([])
  })
})
