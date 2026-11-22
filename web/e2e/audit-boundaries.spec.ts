import { expect, test } from '@playwright/test'
import { auditFixture, openAudit, waitAudit } from './audit-table.helpers'

test('a late filter response cannot replace the currently selected action', async ({ page }) => {
  const state = await auditFixture(page)
  await openAudit(page)
  await waitAudit(page)
  let release = () => {}
  state.holdAction = 'observability.index_audit.daily'
  state.hold = new Promise<void>((resolve) => {
    release = resolve
  })
  const pendingFilter = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return url.pathname === '/api/v1/audit/logs' && url.searchParams.get('action') === state.holdAction
  })
  const rows = page.locator('tbody tr')
  const accessFilter = page.getByRole('button', { name: '访问回溯', exact: true })
  try {
    await page.getByRole('button', { name: '索引审计', exact: true }).click()
    const request = await pendingFilter
    await expect(page.getByRole('button', { name: '刷新审计日志', exact: true })).toHaveAttribute('aria-busy', 'true')
    await expect(page.getByText('正在更新 · 按时间倒序', { exact: true })).toBeVisible()
    await expect(page.getByRole('region', { name: '当前已显示范围', exact: true })).toBeVisible()
    await expect(rows).toHaveCount(20)
    await accessFilter.click()
    await waitAudit(page)
    await expect(rows).toHaveCount(2)
    release()
    const response = await request.response()
    await response?.finished()
  } finally {
    release()
    state.hold = null
  }
  await expect(accessFilter).toHaveAttribute('aria-pressed', 'true')
  await expect(rows).toHaveCount(2)
  await expect(page.locator('tbody')).toContainText('访问回溯导出')
  expect(state.errors).toEqual([])
})

test('a pending preview locks its scope and sends only one operation', async ({ page }) => {
  const state = await auditFixture(page)
  await openAudit(page)
  await waitAudit(page)
  await page.getByRole('button', { name: '打开清理工具', exact: true }).click()
  const d = page.getByRole('dialog', { name: '清理工具', exact: true })
  const preview = d.getByRole('button', { name: '预演清理', exact: true })
  const close = d.getByRole('button', { name: '关闭', exact: true })
  const headerClose = d.getByRole('button', { name: 'Close', exact: true })
  const purgeRequests = () => state.requests.filter((r) => r.path.endsWith('/purge'))
  await expect(headerClose).toBeVisible()
  let release = () => {}
  state.hold = new Promise<void>((resolve) => {
    release = resolve
  })
  try {
    await preview.dblclick()
    await expect.poll(purgeRequests).toHaveLength(1)
    await expect(preview).toBeDisabled()
    await expect(preview).toHaveAttribute('aria-busy', 'true')
    await expect(close).toBeDisabled()
    await expect(headerClose).toHaveCount(0)
    await expect(d.getByLabel('保留天数', { exact: true })).toBeDisabled()
    await expect(d.getByLabel('最多清理', { exact: true })).toBeDisabled()
    await expect(d.getByRole('radio', { name: '按保留期', exact: true })).toBeDisabled()
    await expect(d.getByRole('radio', { name: '按当前筛选', exact: true })).toBeDisabled()
    await expect(d.getByRole('radio', { name: '预演', exact: true })).toBeDisabled()
    await expect(d.getByRole('radio', { name: '真实清理', exact: true })).toBeDisabled()
    await page.keyboard.press('Escape')
    await expect(d).toBeVisible()
    await page.mouse.click(10, 10)
    await expect(d).toBeVisible()
  } finally {
    release()
    state.hold = null
  }
  await expect(d.getByRole('heading', { name: '上次预演结果', exact: true })).toBeVisible()
  await expect(preview).toBeEnabled()
  await expect(headerClose).toBeVisible()
  await close.click()
  await waitAudit(page)
  expect(purgeRequests()).toHaveLength(1)
  expect(state.errors).toEqual([])
})
