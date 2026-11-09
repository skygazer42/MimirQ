import { test, expect } from '@playwright/test'
import { remainingFixture, openRemaining, datasetRoute, remainingShot } from './remaining-pages.helpers'

test('KG read failure remains near the action and selection survives recovery', async ({ page }) => {
  await remainingFixture(page)
  let fail = true
  await page.route('**/api/v1/documents?**', route => route.fulfill({ json: { total: 2, items: [
    { id: '7dd88ec6-fb81-4ad1-a6ec-f47fef562111', filename: '产品说明与运维记录.pdf', status: 'completed', file_type: 'pdf' },
    { id: '7dd88ec6-fb81-4ad1-a6ec-f47fef562222', filename: '长名称的售后服务知识与维护手册.pdf', status: 'completed', file_type: 'pdf' },
  ] } }))
  await page.route('**/api/v1/kg/**', async route => {
    const p = new URL(route.request().url()).pathname
    if (p.endsWith('/graph')) return route.fulfill({ status: fail ? 503 : 200, json: fail ? { detail: '图谱读取暂不可用' } : { nodes: [], links: [] } })
    return route.fulfill({ json: { event_count: 0, entity_count: 0 } })
  })
  await openRemaining(page, datasetRoute('kg'), '数据集图谱')
  const selected = page.getByRole('checkbox', { name: '选择文档 产品说明与运维记录.pdf', exact: true })
  await selected.check()
  await page.getByRole('button', { name: '加载图谱', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '图谱读取暂不可用' })).toBeVisible()
  await expect(selected).toBeChecked()
  await remainingShot(page, 'after-kg-read-failure')
  fail = false
  await page.getByRole('button', { name: '重试加载图谱', exact: true }).click()
  await expect(page.getByText('当前范围暂无图谱数据', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: '图谱读取暂不可用' })).toHaveCount(0)
  await remainingShot(page, 'after-kg-filled-directory')
})
