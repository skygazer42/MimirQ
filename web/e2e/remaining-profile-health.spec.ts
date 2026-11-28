import { readFile } from 'node:fs/promises'
import { makeProfileScan } from '../test/dataset-profile-fixtures'
import { test, expect } from '@playwright/test'
import { datasetRoute, openRemaining, remainingFixture, remainingShot } from './remaining-pages.helpers'

test('profile separates problems, distribution and scan history with explicit failed reads', async ({ page }) => {
  const state = await remainingFixture(page)
  state.scanRuns = [makeProfileScan(state.profile)]
  await openRemaining(page, datasetRoute('profile'), '数据画像')
  await page.getByRole('tab', { name: '问题与概览', exact: true }).click()
  await expect(page.getByRole('table', { name: '画像问题清单' })).toContainText('扫描版 PDF')
  await page.getByRole('button', { name: '查看扫描版 PDF文件', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('product-guide.pdf', { timeout: 30000 })
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: '分布分析', exact: true }).click()
  await expect(page.getByRole('tab', { name: '文档分布', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: '扫描历史', exact: true }).click()
  state.failHistory = true
  await page.getByRole('button', { name: '重新读取扫描历史', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '扫描历史读取暂不可用' })).toBeVisible({ timeout: 30000 })
  await page.getByRole('tab', { name: '问题与概览', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '保留上次有效结果' })).toBeVisible()
  await expect(page.getByRole('table', { name: '画像问题清单' })).toContainText('扫描版 PDF')
  expect(state.base.blocked).toEqual([])
})

test('health presents actual exceptions and a failed read can recover without reporting zero', async ({ page }) => {
  const state = await remainingFixture(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  state.failHealth = true
  await openRemaining(page, datasetRoute('health'), '健康概览')
  await expect(page.getByRole('button', { name: '重新读取健康概览', exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('[data-health-document-count]')).toHaveCount(0)
  state.failHealth = false
  await page.getByRole('button', { name: '重新读取健康概览', exact: true }).click()
  await expect(page.locator('[data-health-document-count]')).toContainText('128', { timeout: 30000 })
  await expect(page.getByRole('table', { name: '健康异常清单' })).toContainText('扫描版 PDF')
  await remainingShot(page, 'health-desktop')
  await page.screenshot({ path: test.info().outputPath('health-desktop.png'), animations: 'disabled' })
  await page.getByText('状态与格式分布', { exact: true }).click()
  const legend = page.getByRole('list', { name: '格式分布图例', exact: true })
  const legendColors = await legend
    .getByRole('listitem')
    .evaluateAll((items) =>
      items.map((item) => getComputedStyle(item.querySelector('[aria-hidden="true"]')!).backgroundColor),
    )
  expect(new Set(legendColors).size).toBeGreaterThan(1)
  await expect
    .poll(async () => {
      const sectorColors = await page
        .locator('.recharts-pie-sector path')
        .evaluateAll((paths) => paths.map((path) => getComputedStyle(path).fill))
      return legendColors.every((color) => sectorColors.includes(color))
    })
    .toBe(true)
  await page.getByRole('button', { name: '导出健康报告', exact: true }).click()
  const exported = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: 'JSON 报告', exact: true }).click()
  const exportPath = test.info().outputPath('health-report.json')
  await (await exported).saveAs(exportPath)
  const exportedHealth = JSON.parse(await readFile(exportPath, 'utf8'))
  expect(exportedHealth.schema).toBe('mimirq.dataset_health.v1')
  expect(exportedHealth.dataset.id).toBe(datasetRoute('health').split('/')[2])
  expect(exportedHealth.health.profile.total_documents).toBe(128)
  await page.screenshot({ path: test.info().outputPath('health-distribution.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('health-phone.png'), animations: 'disabled' })
})

test('capture current profile and health workspaces', async ({ page }) => {
  await remainingFixture(page)
  for (const [name, title] of [
    ['profile', '数据画像'],
    ['health', '健康概览'],
  ]) {
    await openRemaining(page, datasetRoute(name), title)
    await expect(page.getByText('产品知识库', { exact: true }).first()).toBeVisible({ timeout: 30000 })
    await remainingShot(page, `after-${name}`)
  }
})

test('health exception links retain the dataset and status scope', async ({ page }) => {
  await remainingFixture(page)
  const datasetId = datasetRoute('health').split('/')[2]
  for (const [label, status] of [
    ['查看处理失败文档', 'failed'],
    ['查看隔离文档', 'quarantined'],
  ]) {
    await openRemaining(page, datasetRoute('health'), '健康概览')
    const target = page.getByRole('link', { name: label, exact: true })
    const expected = '/knowledge?' + new URLSearchParams({ dataset: datasetId, status, lifecycle: 'all' })
    await expect(target).toHaveAttribute('href', expected)
    await Promise.all([
      page.waitForRequest((value) => {
        const url = new URL(value.url())
        return (
          url.pathname === '/api/v1/documents' &&
          url.searchParams.get('dataset_id') === datasetId &&
          url.searchParams.get('status') === status &&
          url.searchParams.get('lifecycle') === 'all'
        )
      }),
      target.click(),
    ])
    await expect(page).toHaveURL(
      (url) =>
        url.pathname === '/knowledge' &&
        url.searchParams.get('dataset') === datasetId &&
        url.searchParams.get('status') === status &&
        url.searchParams.get('lifecycle') === 'all',
    )
  }
})
