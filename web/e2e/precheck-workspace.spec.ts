import { test, expect } from '@playwright/test'
import { openPrecheck, precheckFixture, precheckRoute, precheckShot, runOne, runTwo } from './precheck-workspace.helpers'

test('read a report, inspect a finding and file, export and compare without changing the run', async ({ page }) => {
  const state = await precheckFixture(page)
  await openPrecheck(page)
  await expect(page.locator('[data-precheck-total]')).toContainText('128', { timeout: 30000 })
  await expect(page.getByText('数据良好', { exact: true })).toHaveCount(0)
  await precheckShot(page, 'after-desktop')
  await page.getByRole('button', { name: '查看扫描版 PDF文件' }).click()
  const finding = page.getByRole('dialog')
  await expect(finding.getByRole('button', { name: 'product-guide.pdf', exact: true })).toBeVisible({ timeout: 30000 })
  await finding.getByRole('button', { name: 'product-guide.pdf', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(finding.getByRole('heading', { name: '文件详情', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await finding.getByRole('button', { name: '返回问题清单' }).click()
  await expect(finding.getByRole('button', { name: 'product-guide.pdf', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  for (const format of ['JSON', 'HTML']) {
    await page.getByRole('button', { name: '导出报告', exact: true }).click()
    const download = page.waitForEvent('download')
    await page.getByRole('menuitem', { name: `${format} 报告`, exact: true }).click()
    expect((await download).suggestedFilename()).toMatch(new RegExp(`\\.precheck\\.${format.toLowerCase()}$`))
  }
  await page.getByRole('tab', { name: '样本与近重复', exact: true }).click()
  await page.getByRole('button', { name: '加载', exact: true }).nth(0).click()
  await expect(page.getByRole('table', { name: '预检代表性样本' })).toContainText('product-guide.pdf')
  await page.getByRole('button', { name: '加载', exact: true }).nth(1).click()
  await expect(page.getByText('候选分组 1 · 相似对 1 · 阈值 5', { exact: true })).toBeVisible()
  await page.getByRole('tab', { name: '运行对比', exact: true }).click()
  await page.getByRole('combobox', { name: '选择对比运行', exact: true }).click()
  await page.getByRole('option').click()
  await page.getByRole('button', { name: '开始对比', exact: true }).click()
  await expect(page.getByRole('table', { name: '预检 Top Findings 差异' })).toContainText('pdf_scanned')
  expect(state.starts).toEqual([])
  expect(state.base.blocked).toEqual([])
})

test('read failures remain distinct from empty runs and recover in place', async ({ page }) => {
  const state = await precheckFixture(page); state.failRead = true
  await openPrecheck(page)
  await expect(page.getByRole('alert').filter({ hasText: '预检记录暂不可用' })).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('heading', { name: '还没有预检记录', exact: true })).toHaveCount(0)
  state.failRead = false; state.failSummary = true
  await page.getByRole('button', { name: '重新读取页面', exact: true }).click()
  await expect(page.getByRole('button', { name: '重新读取报告', exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('[data-precheck-total]')).toHaveCount(0)
  state.failSummary = false
  await page.getByRole('button', { name: '重新读取报告', exact: true }).click()
  await expect(page.locator('[data-precheck-total]')).toContainText('128', { timeout: 30000 })
  state.failFinding = true
  await page.getByRole('button', { name: '查看扫描版 PDF文件' }).click()
  await expect(page.getByRole('button', { name: '重新读取清单', exact: true })).toBeVisible({ timeout: 30000 })
  state.failFinding = false
  await page.getByRole('button', { name: '重新读取清单', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('button', { name: 'product-guide.pdf', exact: true })).toBeVisible()
})

test('a delayed previous report cannot replace the selected history run', async ({ page }) => {
  const state = await precheckFixture(page)
  let release!: () => void
  state.summaryGates[runOne] = new Promise<void>(resolve => { release = resolve })
  await openPrecheck(page)
  await expect.poll(() => state.reads.includes(`${runOne}/summary`)).toBeTruthy()
  await page.getByRole('combobox', { name: '历史运行', exact: true }).click()
  await page.getByRole('option').filter({ hasText: '2026/10/25' }).click()
  await expect(page.locator('[data-precheck-total]')).toContainText('64', { timeout: 30000 })
  const oldResponse = page.waitForResponse(response => response.url().includes(`${runOne}/summary`))
  release(); await oldResponse
  await expect(page.locator('[data-precheck-total]')).toContainText('64')
  expect(state.reads).toContain(`${runTwo}/summary`)
})

test('configuration survives a failed start, submits once and reads the new run after reload', async ({ page }) => {
  const state = await precheckFixture(page); state.runs = []; state.failStart = '目录当前无法访问'
  await openPrecheck(page)
  await page.getByRole('button', { name: '新建预检', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('扫描目录', { exact: true }).fill('/uploads/reports')
  await dialog.getByLabel('最大文件数', { exact: true }).fill('50')
  await dialog.getByRole('switch', { name: '个人信息检测', exact: true }).check()
  await dialog.getByRole('tab', { name: '高级选项', exact: true }).click()
  await dialog.getByRole('switch', { name: '近重复候选', exact: true }).check()
  await dialog.getByLabel('抽样数量', { exact: true }).fill('24')
  await dialog.getByRole('button', { name: '开始预检', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('目录当前无法访问')
  await expect(dialog.getByLabel('抽样数量', { exact: true })).toHaveValue('24')
  state.failStart = ''
  let release!: () => void
  state.startGate = new Promise<void>(resolve => { release = resolve })
  await dialog.getByRole('button', { name: '开始预检', exact: true }).click()
  await expect(dialog.getByRole('button', { name: '正在启动…', exact: true })).toBeDisabled()
  await expect.poll(() => state.starts.length).toBe(2)
  release()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('[data-precheck-total]')).toBeVisible()
  expect(state.starts[1]).toMatchObject({ root_path: '/uploads/reports', max_files: 50, enable_pii: true, enable_near_dup: true, sample_size: 24 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-precheck-total]')).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('/uploads/reports', { exact: true })).toBeVisible()
  expect(state.base.blocked).toEqual([])
})

test('cancel failure retains the running state and allows retry', async ({ page }) => {
  const state = await precheckFixture(page); state.runs[0].status = 'running'; state.runs[0].progress = 25; state.failCancel = '取消请求暂不可用'
  await openPrecheck(page)
  await page.getByRole('button', { name: '取消预检', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '取消请求暂不可用' })).toBeVisible()
  await expect(page.getByRole('button', { name: '新建预检', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '取消预检', exact: true })).toBeEnabled()
  state.failCancel = ''
  await page.getByRole('button', { name: '取消预检', exact: true }).click()
  await expect(page.getByRole('heading', { name: '已取消', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '新建预检', exact: true })).toBeEnabled()
  expect(state.cancels).toEqual([runOne, runOne])
})

test('policy application retains its choice on failure and phone dialogs stay inside the viewport', async ({ page }) => {
  const state = await precheckFixture(page, 'dark')
  await page.setViewportSize({ width: 390, height: 844 })
  await openPrecheck(page)
  await expect(page.locator('[data-precheck-total]')).toBeVisible({ timeout: 30000 })
  await precheckShot(page, 'after-phone-dark')
  await page.getByRole('button', { name: '生成策略', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('覆盖已有入库策略', { exact: true }).check()
  state.failApply = '策略暂时无法写入'
  await dialog.getByRole('button', { name: '应用到数据集', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('策略暂时无法写入')
  await expect(dialog.getByLabel('覆盖已有入库策略', { exact: true })).toBeChecked()
  state.failApply = ''
  await dialog.getByRole('button', { name: '应用到数据集', exact: true }).click()
  await expect(page.getByText('已应用入库策略，共 4 条规则', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '新建预检', exact: true }).click()
  await dialog.getByRole('tab', { name: '高级选项', exact: true }).click()
  await precheckShot(page, 'config-phone-dark')
  const box = await dialog.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.y).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(390); expect(box!.y + box!.height).toBeLessThanOrEqual(844)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: '新建预检', exact: true })).toBeFocused()
  expect(state.applies).toEqual([true, true])
  expect(page.url()).toContain(precheckRoute)
})
