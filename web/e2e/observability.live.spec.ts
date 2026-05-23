import { expect, test, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

function liveHeaders() {
  return {
    tenantId:
      process.env.PLAYWRIGHT_LIVE_TENANT_ID ||
      process.env.NEXT_PUBLIC_TENANT_ID ||
      DEFAULT_TENANT_ID,
    userId:
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
    headers
  )
}

async function assertResultPanel(
  page: Page,
  {
    title,
    expectedTexts,
  }: {
    title: string
    expectedTexts: string[]
  }
) {
  await expect(page.getByText(title, { exact: true })).toBeVisible({
    timeout: LIVE_EXPECT_TIMEOUT_MS,
  })
  await page.getByText('查看原始响应', { exact: true }).click()
  const rawPanel = page.locator('details pre').last()
  for (const text of expectedTexts) {
    await expect(rawPanel).toContainText(text, {
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
  }
}

test.describe('live observability workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('runs real observability ops actions on the deployed page host', async ({
    page,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    await page.goto('/observability', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: '监控面板' })
    ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
    await expect(page.getByText('观测运维操作')).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    await page.getByRole('button', { name: '依赖健康' }).click()
    await assertResultPanel(page, {
      title: '依赖诊断快照',
      expectedTexts: [
        'mimirq.observability.deps.v1',
        '"postgres"',
        '"redis"',
      ],
    })

    await page.getByRole('button', { name: '任务队列' }).click()
    await assertResultPanel(page, {
      title: '任务队列快照',
      expectedTexts: [
        'mimirq.task_queue_observability.v1',
        '"queue_depth"',
        '"workers_active"',
      ],
    })

    await page.getByRole('button', { name: 'SLO' }).click()
    await assertResultPanel(page, {
      title: 'SLO 快照',
      expectedTexts: [
        'mimirq.slo_snapshot.v1',
        '"window_minutes": 60',
        '"window_minutes": 1440',
      ],
    })

    await page.getByText('高级参数（可选）').click()
    await page.getByRole('button', { name: 'Trace 上报' }).click()
    await assertResultPanel(page, {
      title: '前端 Trace 上报',
      expectedTexts: ['"reported": true', 'manual_observability_probe'],
    })

    expect(pageErrors).toEqual([])
  })
})
