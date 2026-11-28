import { test, expect } from '@playwright/test'
import { ablationsFixture } from './remaining-ablations.helpers'
import { openRemaining, remainingShot } from './remaining-pages.helpers'

for (const variant of [
  { name: 'desktop', width: 1600, height: 1000, theme: 'light' as const },
  { name: 'narrow-dark', width: 1120, height: 850, theme: 'dark' as const },
  { name: 'phone', width: 390, height: 844, theme: 'light' as const },
]) {
  test(`ablations ${variant.name} keeps failed parameters and reads back a submitted run`, async ({ page }) => {
    test.setTimeout(300000)
    const state = await ablationsFixture(page, variant.theme)
    await page.setViewportSize(variant)
    await openRemaining(page, '/evaluations/ablations', '检索调参对比')
    await expect(page.getByRole('combobox', { name: '实验数据集', exact: true })).toHaveValue(
      '4bf314df-47e7-4594-b611-666666666666',
    )
    await expect(page.getByRole('table', { name: '实验运行', exact: true }).getByRole('row')).toHaveCount(3)
    await remainingShot(page, `after-retrieval-ablations-${variant.name}`)
    await page.getByRole('button', { name: '新建实验', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '实验参数', exact: true })
    const cases = dialog.getByRole('spinbutton', { name: '评测样本上限', exact: true })
    await cases.fill('25')
    await remainingShot(page, `after-retrieval-ablations-config-${variant.name}`)
    await expect(dialog.getByRole('button', { name: '运行消融实验', exact: true })).toBeEnabled()
    await dialog.getByRole('button', { name: '运行消融实验', exact: true }).click()
    await expect(dialog.getByRole('alert').filter({ hasText: '实验提交暂不可用' })).toBeVisible()
    await expect(cases).toHaveValue('25')
    expect(state.writes[0].max_cases).toBe(25)
    state.failSave = false
    await dialog.getByRole('button', { name: '运行消融实验', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('table', { name: '实验运行', exact: true }).getByRole('row')).toHaveCount(4)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  })
}

test('older leaderboard runs remain visible and can be compared outside the recent run window', async ({ page }) => {
  const state = await ablationsFixture(page)
  state.includeOlder = true
  await openRemaining(page, '/evaluations/ablations', '检索调参对比')
  await expect(page.getByRole('combobox', { name: '实验数据集', exact: true })).toHaveValue(
    '4bf314df-47e7-4594-b611-666666666666',
  )
  await page.getByRole('button', { name: '按指标排行', exact: true }).click()
  const table = page.getByRole('table', { name: '实验运行', exact: true })
  await expect(table.getByRole('row')).toHaveCount(4)
  await table.getByRole('button', { name: '设为候选 archived-best-run', exact: true }).click()
  await expect.poll(() => state.detailReads).toEqual(['archived-best-run'])
  await table.getByRole('button', { name: '设为基线 baseline-run', exact: true }).click()
  await page.getByRole('button', { name: '生成对比', exact: true }).click()
  await expect.poll(() => state.diffs.at(-1)).toEqual({ target: 'archived-best-run', base: 'baseline-run' })
})

test('a later comparison selector cancels an older ranking detail selection', async ({ page }) => {
  const state = await ablationsFixture(page)
  state.includeOlder = true
  let release!: () => void
  state.detailGate = new Promise<void>((resolve) => {
    release = resolve
  })
  await openRemaining(page, '/evaluations/ablations', '检索调参对比')
  await expect(page.getByRole('combobox', { name: '实验数据集', exact: true })).toHaveValue(
    '4bf314df-47e7-4594-b611-666666666666',
  )
  await page.getByRole('button', { name: '按指标排行', exact: true }).click()
  await page.getByRole('button', { name: '设为候选 archived-best-run', exact: true }).click()
  await expect.poll(() => state.detailReads.length).toBe(1)
  const selector = page.getByRole('combobox', { name: '选择候选运行', exact: true })
  await selector.click()
  await page
    .getByRole('option')
    .filter({ hasText: /baseline/ })
    .click()
  await expect(selector).toContainText('baseline')
  const response = page.waitForResponse((value) => new URL(value.url()).pathname.endsWith('/runs/archived-best-run'))
  release()
  await (await response).finished()
  await page.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
  )
  await expect(selector).toContainText('baseline')
  await page.getByRole('button', { name: '设为基线 candidate-run', exact: true }).click()
  await page.getByRole('button', { name: '生成对比', exact: true }).click()
  await expect.poll(() => state.diffs.at(-1)).toEqual({ target: 'baseline-run', base: 'candidate-run' })
})

test('short parameter form keeps its title and actions fixed while scrolling', async ({ page }) => {
  await ablationsFixture(page)
  await page.setViewportSize({ width: 390, height: 620 })
  await openRemaining(page, '/evaluations/ablations', '检索调参对比')
  await page.getByRole('button', { name: '新建实验', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '实验参数', exact: true })
  const title = dialog.getByRole('heading', { name: '实验参数', exact: true })
  const submit = dialog.getByRole('button', { name: '运行消融实验', exact: true })
  const cases = dialog.getByRole('spinbutton', { name: '评测样本上限', exact: true })
  const mode = dialog.getByRole('switch', { name: '仅检索模式', exact: true })
  await expect(dialog.getByText('仅检索', { exact: true })).toBeVisible()
  await expect(mode).toBeChecked()
  await mode.click()
  await expect(dialog.getByText('检索与生成', { exact: true })).toBeVisible()
  await mode.click()
  await cases.fill('25')
  await submit.click()
  const failure = dialog.getByRole('alert').filter({ hasText: '实验提交暂不可用' })
  await expect(failure).toBeVisible()
  await expect(cases).toHaveValue('25')
  await expect(title).toBeInViewport({ ratio: 1 })
  await failure.scrollIntoViewIfNeeded()
  await expect(failure).toBeInViewport({ ratio: 1 })
  await expect(title).toBeInViewport({ ratio: 1 })
  await expect(submit).toBeInViewport({ ratio: 1 })
  await expect(dialog.getByRole('button', { name: '取消', exact: true })).toBeInViewport({ ratio: 1 })
  const failureBottom = await failure.evaluate((element) => element.getBoundingClientRect().bottom)
  const footerTop = await submit.locator('..').evaluate((element) => element.getBoundingClientRect().top)
  expect(failureBottom).toBeLessThanOrEqual(footerTop + 1)
})

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 620 },
]) {
  test(`comparison evidence and feedback stay clear at ${viewport.width}`, async ({ page }) => {
    await ablationsFixture(page)
    await page.setViewportSize(viewport)
    await openRemaining(page, '/evaluations/ablations', '检索调参对比')
    await page.getByRole('button', { name: '设为基线 baseline-run', exact: true }).click()
    await page.getByRole('button', { name: '设为候选 candidate-run', exact: true }).click()
    await page.getByRole('button', { name: '生成对比', exact: true }).click()
    const conclusion = page.getByRole('definition').filter({ hasText: '0.6000' })
    await expect(conclusion).toBeVisible()
    const metrics = page.getByRole('table', { name: '基线与候选运行的实际指标值及差值', exact: true })
    const metricRow = await metrics.getByRole('row').nth(1).boundingBox()
    expect(metricRow!.y).toBeGreaterThanOrEqual(0)
    expect(metricRow!.y + metricRow!.height).toBeLessThanOrEqual(viewport.height)
    const toast = page.locator('[data-sonner-toast][data-front="true"]')
    await expect(toast).toBeVisible()
    expect(await toast.evaluate((element) => element.getBoundingClientRect().bottom)).toBeLessThanOrEqual(72)
    if (viewport.width < 640) {
      const navigation = await page
        .locator('button[aria-controls="mimirq-sidebar"][aria-expanded="false"]')
        .boundingBox()
      const notification = await toast.boundingBox()
      expect(navigation!.y).toBeGreaterThanOrEqual(notification!.y + notification!.height)
    }
    await remainingShot(page, `comparison-evidence-${viewport.width}`)
    await page.getByRole('button', { name: '新建实验', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '实验参数', exact: true })
    const title = dialog.getByRole('heading', { name: '实验参数', exact: true })
    const toastRect = await toast.boundingBox()
    const titleRect = await title.evaluate((element) => {
      const range = document.createRange()
      range.selectNodeContents(element)
      return range.getBoundingClientRect().toJSON()
    })
    expect(titleRect.top >= toastRect!.y + toastRect!.height || titleRect.right <= toastRect!.x).toBe(true)
    await dialog.getByRole('button', { name: '运行消融实验', exact: true }).click()
    await expect(dialog.getByRole('alert').filter({ hasText: '实验提交暂不可用' })).toBeVisible()
    await toast.locator('[data-content]').hover()
    await dialog.getByText('仅检索', { exact: true }).scrollIntoViewIfNeeded()
    await expect(dialog.getByText('仅检索', { exact: true })).toBeInViewport({ ratio: 1 })
    await remainingShot(page, `parameter-feedback-${viewport.width}`)
    await toast.locator('[data-close-button]').click()
    await expect(dialog).toBeVisible()
  })
}

test('mobile task center clears the chat composer and keeps keyboard focus', async ({ page }) => {
  await ablationsFixture(page)
  await page.route('**/api/v1/documents**', async (route) => {
    const url = new URL(route.request().url())
    if (!/^\/api\/v1\/documents\/?$/.test(url.pathname)) return route.fallback()
    const processing = url.searchParams.get('status') === 'processing'
    await route.fulfill({
      json: {
        total: processing ? 1 : 0,
        items: processing
          ? [{ id: 'dock-task', filename: '处理中.pdf', status: 'processing', processing_progress: 30 }]
          : [],
      },
    })
  })
  await page.route('**/api/v1/chat/conversations/dock-conversation/messages**', (route) =>
    route.fulfill({
      json: {
        conversation_id: 'dock-conversation',
        returned: 1,
        has_more: false,
        messages: [
          { id: 'dock-message', role: 'assistant', content: '停靠测试对话', created_at: '2026-11-24T00:00:00Z' },
        ],
      },
    }),
  )
  await page.setViewportSize({ width: 390, height: 620 })
  await page.goto('/?conversation=dock-conversation', { waitUntil: 'domcontentloaded' })
  const input = page.getByRole('textbox', { name: '消息输入框', exact: true })
  const trigger = page.getByRole('button', { name: '任务中心', exact: true })
  await expect(input).toBeVisible({ timeout: 60000 })
  await expect(trigger).toBeVisible()
  await expect(page.getByText('停靠测试对话', { exact: true })).toBeVisible()
  await input.fill('检查多行输入后的任务入口位置。\n'.repeat(6))
  await expect
    .poll(async () => {
      const composer = await input.locator('..').boundingBox()
      const button = await trigger.boundingBox()
      return button!.y + button!.height <= composer!.y - 8
    })
    .toBe(true)
  await remainingShot(page, 'chat-task-dock-phone')
  await trigger.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('region', { name: '任务中心', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
})
