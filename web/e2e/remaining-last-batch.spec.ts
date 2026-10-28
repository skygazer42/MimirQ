import { test, expect } from '@playwright/test'
import { lastBatchFixture, auditDocumentId } from './remaining-last-batch.helpers'
import { openRemaining, remainingShot } from './remaining-pages.helpers'

for (const variant of [{ name: 'desktop', width: 1600, height: 1000, theme: 'light' as const }, { name: 'narrow-dark', width: 1120, height: 850, theme: 'dark' as const }, { name: 'phone', width: 390, height: 844, theme: 'light' as const }]) {
  test(`last batch ${variant.name} reports, readers and callback recovery`, async ({ page }) => {
    test.setTimeout(600000)
    await lastBatchFixture(page, variant.theme)
    await page.setViewportSize(variant)
    if (variant.name === 'phone') await page.emulateMedia({ reducedMotion: 'reduce' })
    await openRemaining(page, `/knowledge/${auditDocumentId}/health`, '文档健康审计')
    await expect(page.getByText('解析链路', { exact: true })).toBeVisible()
    await remainingShot(page, `after-document-health-${variant.name}`)
    await openRemaining(page, '/observability', '可观测性')
    await expect(page.getByText('30', { exact: true }).first()).toBeVisible()
    await remainingShot(page, `after-observability-${variant.name}`)
    await page.getByRole('tab', { name: '查询分析', exact: true }).click()
    await expect(page.getByRole('cell', { name: 'query-slow-001', exact: true })).toBeVisible()
    await remainingShot(page, `after-observability-queries-${variant.name}`)
    const statistics = page.getByRole('button', { name: '查看统计 query-slow-001', exact: true })
    await statistics.click()
    await expect(page.getByRole('dialog')).toContainText('query-slow-001')
    if (variant.name === 'phone') {
      const motion = await page.getByRole('dialog').evaluate(element => ({ name: getComputedStyle(element).animationName, durations: getComputedStyle(element).animationDuration.split(',').map(value => Number.parseFloat(value)) }))
      expect(motion.name === 'none' || motion.durations.every(duration => duration <= 0.01)).toBe(true)
    }
    await page.getByRole('dialog').getByRole('button', { name: '完成', exact: true }).click()
    await expect(statistics).toBeFocused()
    await openRemaining(page, '/knowledge/evidence', '证据调试')
    await page.getByRole('textbox', { name: '检索问题', exact: true }).fill('设备的维护周期是多久？')
    await page.getByRole('button', { name: '运行检索', exact: true }).click()
    await expect(page.getByRole('heading', { name: '已找到证据', exact: true })).toBeVisible()
    await expect(page.getByText('维护周期为六个月，完成例行检查后记录维护日期。', { exact: true })).toBeVisible()
    await remainingShot(page, `after-evidence-debugger-${variant.name}`)
    await openRemaining(page, '/knowledge/nebula', '语义星云')
    await expect(page.getByText('1 文档 · 4 切片', { exact: true })).toBeVisible()
    await expect(page.locator('canvas')).toBeVisible({ timeout: 60000 })
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    await remainingShot(page, `after-semantic-nebula-${variant.name}`)
    await page.getByRole('button', { name: '图例与定位', exact: true }).click()
    await page.getByRole('combobox', { name: '定位切片', exact: true }).selectOption(`${auditDocumentId}:chunk-1`)
    await expect(page.getByRole('dialog', { name: '切片详情', exact: true })).toContainText('设备维护第 2 节')
    await remainingShot(page, `after-semantic-nebula-detail-${variant.name}`)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.evaluate(() => document.documentElement.style.setProperty('--background', '220 20% 20%'))
    await expect(page.getByRole('region', { name: '三维切片画布', exact: true })).toHaveAttribute('data-canvas-background', 'hsl(220, 20%, 20%)')
    for (const protocol of ['oidc', 'saml']) {
      await page.goto(`/auth/${protocol}/callback${protocol === 'saml' ? '?error=saml_session_missing' : ''}`, { waitUntil: 'domcontentloaded' })
      await expect(page.getByRole('heading', { name: '单点登录未完成', exact: true })).toBeVisible({ timeout: 60000 })
      await expect(page.getByRole('button', { name: '返回登录', exact: true })).toBeVisible()
      await remainingShot(page, `after-${protocol}-callback-${variant.name}`)
    }
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  })
}

test('last-batch read failure and stale evidence cannot appear as another successful query', async ({ page }) => {
  const state = await lastBatchFixture(page)
  state.failHealth = true
  await openRemaining(page, `/knowledge/${auditDocumentId}/health`, '文档健康审计')
  await expect(page.getByRole('alert').filter({ hasText: '健康审计暂不可用' })).toBeVisible()
  state.failHealth = false
  await page.getByRole('alert').getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(page.getByText('解析链路', { exact: true })).toBeVisible()
  state.failEvidence = true
  await openRemaining(page, '/knowledge/evidence', '证据调试')
  const query = page.getByRole('textbox', { name: '检索问题', exact: true })
  await query.fill('设备的维护周期是多久？')
  await page.getByRole('button', { name: '运行检索', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '证据检索暂不可用' })).toBeVisible()
  await expect(query).toHaveValue('设备的维护周期是多久？')
  state.failEvidence = false
  let release!: () => void
  state.gate = new Promise<void>(resolve => { release = resolve })
  await page.getByRole('button', { name: '运行检索', exact: true }).click()
  await expect.poll(() => state.evidenceRequests.length).toBe(2)
  state.gate = null; state.evidenceMode = 'abstain'
  await query.fill('另一问题：有维护证据吗？')
  await page.getByRole('button', { name: '运行检索', exact: true }).click()
  await expect(page.getByRole('heading', { name: '证据不足，已拒答', exact: true })).toBeVisible()
  const lateResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/rag/retrieve' && response.request().postDataJSON().query === '设备的维护周期是多久？')
  release()
  await (await lateResponse).finished()
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await expect(page.getByRole('heading', { name: '证据不足，已拒答', exact: true }).locator('..').getByText('另一问题：有维护证据吗？', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '已找到证据', exact: true })).toHaveCount(0)
  state.emptyChunks = true
  await openRemaining(page, '/knowledge/nebula', '语义星云')
  await expect(page.getByRole('heading', { name: '当前没有可视化切片', exact: true })).toBeVisible()
  await expect(page.getByText('1 文档 · 0 切片', { exact: true })).toBeVisible()
  state.emptyChunks = false; state.failChunks = true
  await page.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '切片读取暂不可用' })).toBeVisible()
  await expect(page.getByText('1 文档 · 0 切片', { exact: true })).toBeVisible()
})
