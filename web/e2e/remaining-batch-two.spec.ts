import { test, expect } from '@playwright/test'
import { batchTwoFixture } from './remaining-batch-two.helpers'
import { openRemaining, remainingShot } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

test('monitor filters and pages real-shaped tasks, with failure recovery in place', async ({ page }) => {
  const state = await batchTwoFixture(page)
  await openRemaining(page, `/knowledge/ingestion?mode=execution-monitor&datasetId=${policyDatasetId}`, '入库执行监控')
  const table = page.getByRole('table').first()
  await expect(table.getByRole('row')).toHaveCount(21)
  await page.getByRole('button', { name: '下一页任务' }).click()
  await expect(table.getByRole('row')).toHaveCount(5)
  await page.getByRole('group', { name: '任务状态' }).getByRole('button', { name: '失败 6', exact: true }).click()
  await expect(table.getByRole('row')).toHaveCount(7)
  await page.getByRole('textbox', { name: '搜索执行任务' }).fill('无匹配')
  await expect(page.getByRole('heading', { name: '没有匹配的任务' })).toBeVisible()
  await page.getByRole('button', { name: '清除筛选', exact: true }).click()
  await remainingShot(page, 'after-execution-monitor-filled')
  state.failDocuments = true
  await page.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '任务目录暂不可用' })).toBeVisible({ timeout: 20000 })
  state.failDocuments = false
  await page.getByRole('alert').getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(table.getByRole('row')).toHaveCount(21)
  expect(state.base.base.blocked).toEqual([])
})

test('common-line candidates can be edited and failed saves keep selection and edits', async ({ page }) => {
  const state = await batchTwoFixture(page)
  await openRemaining(page, '/data-governance/common-lines', '重复内容规则')
  await expect(page.getByRole('button', { name: /产品内容清洗/ })).toBeVisible()
  expect(state.writes).toEqual([])
  await page.getByRole('button', { name: '扫描重复内容', exact: true }).click()
  const check = page.getByRole('checkbox', { name: '选择重复行 版权所有，未经许可不得转载', exact: true })
  await check.check()
  await page.getByRole('row').filter({ hasText: '版权所有，未经许可不得转载' }).getByRole('button', { name: '预览与编辑' }).click()
  await page.getByLabel('正则表达式', { exact: true }).fill('(?mi)^版权所有.*$')
  await page.getByRole('dialog').getByRole('button', { name: '完成', exact: true }).click()
  state.failSave = true
  await page.getByRole('button', { name: '写入配置 (1)', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '配置保存失败' })).toBeVisible()
  await expect(check).toBeChecked()
  await remainingShot(page, 'after-common-lines-save-failure')
  state.failSave = false
  await page.getByRole('button', { name: '写入配置 (1)', exact: true }).click()
  await expect(page).toHaveURL(/\/data-governance\/common-lines$/)
  await expect(page.getByRole('tab', { name: '已保存规则', exact: true })).toHaveAttribute('data-state', 'active')
  await expect(page.getByText('(?mi)^版权所有.*$', { exact: true })).toBeVisible()
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '重复内容规则', exact: true })).toBeVisible({ timeout: 60000 })
  await page.getByRole('tab', { name: '已保存规则', exact: true }).click()
  await expect(page.getByText('(?mi)^版权所有.*$', { exact: true })).toBeVisible()
  await remainingShot(page, 'after-common-lines-saved')
})

test('industry tables preserve failed edits, reload saved data and ignore a late preview', async ({ page }) => {
  const state = await batchTwoFixture(page)
  await openRemaining(page, '/governance/industry-rules', '行业规则')
  await expect(page.getByRole('cell', { name: '单点登录', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '新增术语', exact: true }).click()
  await page.getByRole('dialog').getByRole('textbox', { name: '术语', exact: true }).fill('知识治理')
  await page.getByRole('dialog').getByRole('textbox', { name: '别名，逗号分隔', exact: true }).fill('清洗, 脱敏')
  await page.getByRole('button', { name: '完成编辑', exact: true }).click()
  state.failSave = true
  await page.getByRole('button', { name: '保存术语', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '规则保存失败' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '知识治理', exact: true })).toBeVisible()
  state.failSave = false
  await page.getByRole('button', { name: '保存术语', exact: true }).click()
  await expect(page.getByText('术语已保存', { exact: true })).toBeVisible()
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('cell', { name: '知识治理', exact: true })).toBeVisible({ timeout: 60000 })
  await remainingShot(page, 'after-industry-rules-filled')
  let release!: () => void
  state.previewGate = new Promise<void>(resolve => { release = resolve })
  await page.getByRole('button', { name: '查询预览', exact: true }).click()
  const query = page.getByRole('textbox', { name: '输入问题', exact: true })
  const first = page.waitForRequest(request => request.url().endsWith('/industry-rules/preview-rewrite') && request.postDataJSON().query === '旧问题')
  await query.fill('旧问题'); await first
  await query.fill('新问题')
  await expect(page.getByText('已补全：新问题', { exact: true })).toBeVisible()
  release()
  await expect(page.getByText('已补全：旧问题', { exact: true })).toHaveCount(0)
  await remainingShot(page, 'after-industry-preview')
})
