import { expect, test } from '@playwright/test'
import { openUsage, usageEvidence, usageFixture, waitUsage } from './usage-overview.helpers'

test('A renders the resource overview and dataset table with independent quotas', async ({ page }) => {
  const { state } = await usageFixture(page)
  await openUsage(page)
  await waitUsage(page)
  const table = page.getByRole('region', { name: '数据集用量归因', exact: true })
  await expect(table.locator('tbody tr')).toHaveCount(8)
  await expect(page.locator('dl[aria-label="累计用量"] dd').nth(1)).toHaveText('1,752,300')
  const rail = page.getByRole('complementary', { name: '租户配额与限流', exact: true })
  await expect(rail).toBeVisible()
  expect((await rail.boundingBox())!.width).toBe(348)
  const header = page.locator('[data-usage-overview] > header')
  expect((await header.boundingBox())!.height).toBe(52)
  await expect(header.getByRole('group', { name: '用量统计窗口' })).toBeVisible()
  await expect(header.getByRole('button', { name: '查看原始配额' })).toHaveCount(0)
  await expect(rail.getByRole('button', { name: '查看原始配额' })).toBeVisible()
  await expect(rail.getByRole('button', { name: '复制配额' })).toBeVisible()
  await expect(page.getByRole('region', { name: '租户配额概览' }).getByRole('progressbar')).toHaveCount(4)
  await expect(page.getByRole('region', { name: '请求限流', exact: true }).getByRole('progressbar')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '查看工程文档库知识库', exact: true })).toHaveAttribute(
    'href',
    '/knowledge?dataset=ds-engineering&lifecycle=all&status=all',
  )
  const hidden = table.getByRole('row').filter({ hasText: '不可见数据集' })
  await expect(hidden.getByRole('link')).toHaveCount(0)
  await expect(table.getByRole('row').filter({ hasText: '未绑定数据集' }).getByRole('link')).toHaveCount(0)
  await page.screenshot({ path: `${usageEvidence}/desktop-a.png` })
  await page.getByRole('tab', { name: '链路资源', exact: true }).click()
  await expect(page.getByRole('region', { name: '数据集链路资源' }).locator('tbody tr')).toHaveCount(8)
  await expect(page.locator('dl[aria-label="链路资源汇总"]')).toContainText('1,266,100')
  await expect(page.locator('dl[aria-label="链路资源汇总"]')).toContainText('40.6 s')
  const overflowingHeaders = await page
    .getByRole('region', { name: '数据集链路资源' })
    .locator('thead th')
    .evaluateAll((headers) =>
      headers
        .filter((header) => {
          const range = document.createRange()
          range.selectNodeContents(header)
          const style = getComputedStyle(header)
          return (
            range.getBoundingClientRect().width >
            header.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
          )
        })
        .map((header) => header.textContent),
    )
  expect(overflowingHeaders).toEqual([])
  await expect(page.getByRole('tabpanel', { name: '链路资源', exact: true })).toHaveCSS('opacity', '1')
  await page.screenshot({ path: `${usageEvidence}/resources.png` })
  await page.getByRole('tab', { name: '配额状态', exact: true }).click()
  await expect(page.getByRole('region', { name: '完整配额状态' })).toContainText('所有数据集共享')
  await expect(page.getByRole('region', { name: '聊天 token明细', exact: true })).toContainText('7,440')
  await expect(page.getByRole('tabpanel', { name: '配额状态', exact: true })).toHaveCSS('opacity', '1')
  await page.screenshot({ path: `${usageEvidence}/quotas.png` })
  expect(state.requests.every((r) => r.method === 'GET')).toBe(true)
  expect(state.errors).toEqual([])
})

test('empty usage and disabled quotas remain distinct from missing data', async ({ page }) => {
  const { state } = await usageFixture(page)
  state.empty = true
  state.chat.enabled = false
  for (const item of Object.values(state.tenant)) item.enabled = false
  await openUsage(page)
  await waitUsage(page)
  await expect(page.getByRole('heading', { name: '暂无用量记录', exact: true })).toBeVisible()
  await expect(page.locator('dl[aria-label="累计用量"] dd').first()).toHaveText('0条')
  await expect(page.locator('dl[aria-label="累计用量"] dd').last()).toHaveText('—')
  const band = page.getByRole('region', { name: '租户配额概览', exact: true })
  await expect(band.locator('details')).toHaveCount(0)
  await expect(band.getByText('未启用', { exact: true })).toHaveCount(5)
  await expect(band.getByRole('progressbar')).toHaveCount(0)
  await expect(page.locator('table')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '开始对话', exact: true })).toHaveAttribute('href', '/')
  await expect(page.getByRole('link', { name: '查看知识库', exact: true })).toHaveAttribute('href', '/knowledge')
  await expect(page.getByRole('complementary', { name: '用量监控维度' }).locator('li')).toHaveCount(3)
  await page.screenshot({ path: `${usageEvidence}/empty.png` })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(band.locator('details')).not.toHaveAttribute('open')
  await band.locator('summary').click()
  await expect(band.getByText('未启用', { exact: true })).toHaveCount(5)
})

test('partial failures preserve available resources and retry the affected source', async ({ page }) => {
  const { state } = await usageFixture(page)
  state.fail = new Set(['cost', 'chat', 'labels'])
  await openUsage(page)
  await expect(page.getByRole('button', { name: '重试链路资源', exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('dl[aria-label="累计用量"] dd').nth(1)).toHaveText('1,752,300')
  await expect(page.locator('dl[aria-label="累计用量"] dd').nth(2)).toHaveText('—')
  await expect(page.getByRole('region', { name: '聊天 token', exact: true })).toContainText('未取得')
  await expect(page.getByRole('region', { name: '文档数量', exact: true })).toContainText('2,432')
  const table = page.getByRole('region', { name: '数据集用量归因', exact: true })
  await expect(table).not.toContainText('不可见数据集')
  await expect(table.getByRole('link')).toHaveCount(0)
  await page.screenshot({ path: `${usageEvidence}/partial-failure.png` })
  await page.setViewportSize({ width: 1440, height: 600 })
  await page.mouse.move(0, 0)
  const noticeOrb = page.getByRole('button', { name: '展开 3 条异常提示', exact: true })
  await expect(noticeOrb).toBeVisible({ timeout: 10_000 })
  await page
    .locator('dl[aria-label="累计用量"]')
    .locator('..')
    .evaluate((element) => {
      element.scrollTop = element.scrollHeight
    })
  await expect(noticeOrb).toBeInViewport({ ratio: 1 })
  await noticeOrb.click()
  state.fail.clear()
  await page.getByRole('button', { name: '重试链路资源', exact: true }).click()
  await expect(page.locator('dl[aria-label="累计用量"] dd').nth(2)).toHaveText('84,600')
  await page.getByRole('button', { name: '刷新用量', exact: true }).click()
  await waitUsage(page)
  await expect(page.locator('[aria-label="数据读取状态"] [role="alert"]')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '查看工程文档库知识库', exact: true })).toBeVisible()
  expect(state.errors).toEqual([])
})

test('window changes never relabel old usage and late responses stay out of the current scope', async ({ page }) => {
  const { state, summaryFor } = await usageFixture(page)
  await openUsage(page)
  await waitUsage(page)
  let release = () => {}
  state.hold14 = new Promise<void>((resolve) => {
    release = resolve
  })
  try {
    await page.getByRole('button', { name: '近 14 天', exact: true }).click()
    await expect(page.locator('dl[aria-label="累计用量"] dd').nth(1)).toHaveText('—')
    await expect(page.getByRole('region', { name: '数据集用量归因', exact: true })).toHaveAttribute('aria-busy', 'true')
    await expect(page.getByRole('table', { name: '正在读取用量。', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '近 30 天', exact: true }).click()
    await expect(page.locator('dl[aria-label="累计用量"] dd').nth(1)).toHaveText(
      summaryFor(30).total_assistant_tokens.toLocaleString('zh-CN'),
    )
    await expect(page.getByRole('region', { name: '聊天 token', exact: true })).toContainText('近 24 小时')
  } finally {
    release()
    state.hold14 = null
  }
  await waitUsage(page)
  await expect(page.getByRole('button', { name: '近 30 天', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('dl[aria-label="累计用量"] dd').nth(1)).toHaveText(
    summaryFor(30).total_assistant_tokens.toLocaleString('zh-CN'),
  )
  expect(state.errors).toEqual([])
})

test('all attribution rows are reachable and changing views resets pagination', async ({ page }) => {
  const { state } = await usageFixture(page)
  for (let i = 0; i < 7; i++)
    state.rows.push({
      ...state.rows[0],
      id: `extra-${i}`,
      name: `扩展资料 ${i + 1}`,
      assistant_tokens: 100 - i,
      llm_total_tokens: 100 - i,
    })
  await openUsage(page)
  await waitUsage(page)
  await expect(page.getByRole('region', { name: '数据集用量归因' }).locator('tbody tr')).toHaveCount(10)
  await page.getByRole('button', { name: '用量下一页', exact: true }).click()
  await expect(page.getByRole('region', { name: '数据集用量归因' }).locator('tbody tr')).toHaveCount(5)
  await expect(page.getByRole('button', { name: '用量上一页', exact: true })).toBeEnabled()
  await page.getByRole('tab', { name: '链路资源', exact: true }).click()
  await expect(page.getByRole('button', { name: '用量上一页', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '近 14 天', exact: true }).click()
  await waitUsage(page)
  await expect(page.getByRole('button', { name: '用量上一页', exact: true })).toBeDisabled()
})

test('raw quota copy and dialog have observable results and restore keyboard focus', async ({ page }) => {
  await usageFixture(page)
  await openUsage(page)
  await waitUsage(page)
  const opener = page.getByRole('button', { name: '查看原始配额', exact: true })
  await opener.click()
  const dialog = page.getByRole('dialog', { name: '原始配额', exact: true })
  await expect(dialog.locator('pre')).toContainText('"rps": 10')
  await dialog.getByRole('button', { name: '复制配额', exact: true }).click()
  expect(await page.evaluate(() => (window as Window & { usageCopied?: string }).usageCopied)).toContain(
    '"chat_token_quota"',
  )
  await expect(page.getByText('配额已复制', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${usageEvidence}/raw-dialog.png` })
  await page.keyboard.press('Escape')
  await expect(opener).toBeFocused()
  await expect(page.getByText('配额已复制', { exact: true })).not.toBeVisible({ timeout: 8_000 })
})

test('phone and laptop keep the table inside its scroll region and follow dark appearance', async ({ page }) => {
  const { state } = await usageFixture(page, { dark: true })
  state.rows[0].name = '工程文档与服务回滚规范'.repeat(8)
  await openUsage(page)
  await waitUsage(page)
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitUsage(page)
    const windowOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    expect(windowOverflow).toBe(false)
    await expect(page.getByRole('heading', { name: '用量／配额', exact: true })).toBeVisible()
    if (width === 390) {
      await expect(
        page.getByRole('region', { name: '数据集用量归因', exact: true }).locator('tbody th').first(),
      ).toBeInViewport({ ratio: 1 })
      const quotas = page.getByRole('group', { name: '配额概览，可横向滚动', exact: true })
      await quotas.focus()
      await quotas.press('ArrowRight')
      await expect.poll(() => quotas.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
      await page.getByRole('tab', { name: '链路资源', exact: true }).click()
      const resources = page.locator('dl[aria-label="链路资源汇总"]')
      const resourceBox = await resources.boundingBox()
      const totalBox = await page.locator('dl[aria-label="累计用量"]').boundingBox()
      expect(totalBox!.y + totalBox!.height).toBeLessThanOrEqual(resourceBox!.y)
      for (const value of await resources.locator('dd').all()) {
        await value.scrollIntoViewIfNeeded()
        await expect(value).toBeInViewport({ ratio: 1 })
      }
      await page.getByRole('tab', { name: '用量归因', exact: true }).click()
    }
    const scroll = page.getByRole('region', { name: '数据集用量表，可横向滚动', exact: true })
    await scroll.scrollIntoViewIfNeeded()
    const first = scroll.locator('tbody th').first()
    const initial = await first.boundingBox()
    await scroll.evaluate((element) => {
      element.scrollLeft = element.scrollWidth
    })
    const after = await first.boundingBox()
    expect(Math.abs((initial?.x ?? 0) - (after?.x ?? 0))).toBeLessThan(2)
    await page.screenshot({ path: `${usageEvidence}/${width === 390 ? 'phone-dark' : 'laptop-dark'}.png` })
  }
  await page.getByRole('tab', { name: '配额状态', exact: true }).click()
  await expect(page.getByRole('region', { name: '请求限流明细', exact: true })).toContainText('聊天 / 检索')
  const body = await page
    .locator('[data-usage-overview]')
    .evaluate((element) => getComputedStyle(element).backgroundColor)
  expect(body).not.toBe('rgb(255, 255, 255)')
  expect(state.errors).toEqual([])
})

test('authenticated users without usage permission never mount the usage requests', async ({ page }) => {
  const { state } = await usageFixture(page, { authenticated: true, allowed: false })
  await page.goto('/usage', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeVisible({ timeout: 60_000 })
  expect(state.requests.filter((r) => r.path.includes('/usage/'))).toHaveLength(0)
  await expect(page.getByRole('button', { name: '查看原始配额', exact: true })).toHaveCount(0)
})

test('reports a missing resource window when only assistant usage is still pending', async ({ page }) => {
  const { state } = await usageFixture(page)
  state.fail.add('cost')
  let releaseSummary!: () => void
  const pendingSummary = new Promise<void>((resolve) => {
    releaseSummary = resolve
  })
  await page.route(
    (url) => url.pathname.endsWith('/chat/tokens/summary'),
    async (route) => {
      await pendingSummary
      await route.fallback()
    },
  )

  try {
    await page.goto('/usage?view=resources', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: '重试链路资源', exact: true })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('region', { name: '链路资源状态', exact: true })).toContainText('未取得完整用量数据')
    await expect(page.getByText('统计窗口未取得', { exact: true })).toBeVisible()
    await expect(page.getByText('正在读取统计窗口…', { exact: true })).toHaveCount(0)
  } finally {
    releaseSummary()
  }
  await waitUsage(page)
})
