import { test, expect } from '@playwright/test'
import { datasetRoute, openRemaining, remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

test('table tools use tabs, retain failed queries and keep results bound to their table', async ({ page }) => {
  const state = await remainingFixture(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const tables = [{ table_id: 'sales-q1', sheet_index: 0, sheet_name: '一季度销售', row_count: 80, col_count: 2, document_id: 'document-one', document_filename: '季度销售.xlsx', truncated: false, columns: [{ name: 'region', dtype: 'string' }, { name: 'sales', dtype: 'number' }], sample_rows: [{ region: '华东', sales: 1200 }] }, { table_id: 'sales-q2', sheet_index: 1, sheet_name: '二季度销售', row_count: 90, col_count: 2, document_id: 'document-one', document_filename: '季度销售.xlsx', truncated: false, columns: [{ name: 'region', dtype: 'string' }, { name: 'sales', dtype: 'number' }], sample_rows: [{ region: '华南', sales: 1500 }] }]
  let fail = false
  await page.route(`**/api/v1/datasets/${policyDatasetId}/tables**`, async route => {
    const p = new URL(route.request().url()).pathname
    if (p.endsWith('/query')) {
      if (p.includes('sales-q1')) await gate
      return route.fulfill({ status: fail ? 503 : 200, contentType: 'application/json', body: JSON.stringify(fail ? { detail: '查询服务暂不可用' } : { columns: ['region', 'sales'], rows: [['旧表结果', 100]], truncated: false }) })
    }
    const data = p.endsWith('/tables') ? { total: 2, items: tables } : tables.find(item => p.endsWith(item.table_id))
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
  })
  await openRemaining(page, datasetRoute('tables'), '表格资产')
  await expect(page.getByRole('button', { name: '选择表 一季度销售', exact: true })).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: '选择表 一季度销售', exact: true }).click()
  await page.getByRole('tab', { name: 'SQL 查询', exact: true }).click()
  await page.getByRole('textbox', { name: 'SQL 查询语句', exact: true }).fill('SELECT region, sales FROM sheet_0')
  await page.getByRole('button', { name: '执行查询', exact: true }).click()
  await page.getByRole('button', { name: '选择表 二季度销售', exact: true }).click()
  release()
  await page.getByRole('tab', { name: 'SQL 查询', exact: true }).click()
  await expect(page.getByText('旧表结果', { exact: true })).toHaveCount(0)
  fail = true
  await page.getByRole('textbox', { name: 'SQL 查询语句', exact: true }).fill('SELECT * FROM sheet_1 LIMIT 10')
  await page.getByRole('button', { name: '执行查询', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '查询服务暂不可用' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'SQL 查询语句', exact: true })).toHaveValue('SELECT * FROM sheet_1 LIMIT 10')
  expect(state.base.blocked).toEqual([])
})
