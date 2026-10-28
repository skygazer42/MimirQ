import { expect, test } from '@playwright/test'
import { auditFixture, openAudit, waitAudit } from './audit-table.helpers'

test('a late filter response cannot replace the currently selected action', async ({ page }) => {
  const state = await auditFixture(page); await openAudit(page); await waitAudit(page)
  let release = () => {}; state.holdAction = 'observability.index_audit.daily'; state.hold = new Promise<void>(resolve => { release = resolve })
  try {
    await page.getByRole('button', { name: '索引审计', exact: true }).click()
    await expect(page.getByRole('heading', { name: '正在读取审计记录…', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '访问回溯', exact: true }).click(); await waitAudit(page)
    await expect(page.locator('tbody tr')).toHaveCount(2)
    await expect(page.getByRole('button', { name: '访问回溯', exact: true })).toHaveAttribute('aria-pressed', 'true')
  } finally { release(); state.hold = null }
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await expect(page.locator('tbody')).toContainText('访问回溯导出')
  expect(state.errors).toEqual([])
})

test('a pending preview locks its scope and sends only one operation', async ({ page }) => {
  const state = await auditFixture(page); await openAudit(page); await waitAudit(page)
  await page.getByRole('button', { name: '打开清理工具', exact: true }).click()
  const d = page.getByRole('dialog', { name: '清理工具', exact: true })
  let release = () => {}; state.hold = new Promise<void>(resolve => { release = resolve })
  try {
    await d.getByRole('button', { name: '预演清理', exact: true }).click()
    await expect(d.getByRole('button', { name: '正在执行', exact: true })).toBeDisabled()
    await expect(d.getByLabel('最多清理', { exact: true })).toBeDisabled()
    await expect(d.getByRole('radio', { name: '按当前筛选', exact: true })).toBeDisabled()
    await page.keyboard.press('Escape'); await expect(d).toBeVisible()
    expect(state.requests.filter(r => r.path.endsWith('/purge'))).toHaveLength(1)
  } finally { release(); state.hold = null }
  await expect(d.getByRole('region', { name: '清理结果', exact: true })).toBeVisible()
  await d.getByRole('button', { name: '关闭', exact: true }).click(); await waitAudit(page)
  expect(state.errors).toEqual([])
})
