import { test, expect } from '@playwright/test'
import { remainingFixture, openRemaining, datasetRoute, remainingShot } from './remaining-pages.helpers'

test('graph tools keep the current dataset selected', async ({ page }) => {
  await remainingFixture(page)
  const workbenchPath = datasetRoute('kg')
  const datasetId = workbenchPath.split('/')[2]

  for (const [label, destination, selectorLabel] of [
    ['图谱诊断', '/graph/diagnostics', '数据集'],
    ['图谱快照', '/graph/snapshots', '快照数据集'],
  ]) {
    await openRemaining(page, workbenchPath, '数据集图谱')
    await page.getByRole('button', { name: '图谱工具', exact: true }).click()
    await page.getByRole('menuitem', { name: label, exact: true }).click()
    await expect(page).toHaveURL(
      (url) => url.pathname.endsWith(destination) && url.searchParams.get('dataset_id') === datasetId,
    )
    await expect(page.getByRole('combobox', { name: selectorLabel, exact: true })).toHaveValue(datasetId)
  }
})

test('KG read failure remains near the action and selection survives recovery', async ({ page }) => {
  await remainingFixture(page)
  await page.route('**/api/v1/meta/details', (route) => route.fulfill({ json: { features: { kg_enabled: true } } }))
  let fail = true
  await page.route('**/api/v1/documents?**', (route) =>
    route.fulfill({
      json: {
        total: 2,
        items: [
          {
            id: '7dd88ec6-fb81-4ad1-a6ec-f47fef562111',
            filename: '产品说明与运维记录.pdf',
            status: 'completed',
            file_type: 'pdf',
          },
          {
            id: '7dd88ec6-fb81-4ad1-a6ec-f47fef562222',
            filename: '长名称的售后服务知识与维护手册.pdf',
            status: 'completed',
            file_type: 'pdf',
          },
        ],
      },
    }),
  )
  await page.route('**/api/v1/kg/**', async (route) => {
    const p = new URL(route.request().url()).pathname
    if (p.endsWith('/graph'))
      return route.fulfill({
        status: fail ? 503 : 200,
        json: fail ? { detail: '图谱读取暂不可用' } : { nodes: [], links: [] },
      })
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

test('graph extraction shows queue acceptance for both document and bulk actions', async ({ page }) => {
  await remainingFixture(page)
  const documentId = '7dd88ec6-fb81-4ad1-a6ec-f47fef562111'
  const filename = '产品说明与运维记录.pdf'
  await page.route('**/api/v1/documents?**', (route) =>
    route.fulfill({ json: { total: 1, items: [{ id: documentId, filename, status: 'completed', file_type: 'pdf' }] } }),
  )
  const extractionPath = `/api/v1/kg/documents/${documentId}/extract`
  await page.route(`**${extractionPath}*`, (route) => {
    const request = route.request()
    expect(request.headers().prefer).toBe('respond-async')
    expect(new URL(request.url()).searchParams.has('async')).toBe(false)
    return route.fulfill({ status: 202, json: { document_id: documentId, chunk_count: 1, event_count: 0 } })
  })

  await openRemaining(page, datasetRoute('kg'), '数据集图谱')
  await page.getByRole('button', { name: '抽取', exact: true }).click()
  await expect(page.getByText('已提交图谱抽取任务', { exact: true })).toBeVisible()
  await page.getByRole('checkbox', { name: `选择文档 ${filename}`, exact: true }).check()
  await page.getByRole('button', { name: '抽取配置', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '抽取配置', exact: true })
  await dialog.getByRole('button', { name: '抽取选中文档', exact: true }).click()
  await expect(dialog.getByText('已提交', { exact: true })).toBeVisible()
})
