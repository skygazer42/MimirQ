import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { fixture, json, noOverflow, open } from './chunk-compare.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/chunk-config-workbench-v1/tests')
const notifications = (page: Page, type: string) => page.locator(`[data-sonner-toast][data-type=${type}]`)

async function setup(page: Page, options: { gaps?: boolean } = {}) {
  const state = await fixture(page, options)
  await page.addInitScript(() => { if (!localStorage.getItem('mimirq_pipeline_options')) localStorage.setItem('mimirq_pipeline_options', JSON.stringify({ enabled: true, options: { chunk_size: 1000, chunk_overlap: 200 } })) })
  await page.route('**/api/v1/pipeline/plugins**', route => json(route, { items: [], total: 0 }))
  const presets = { fail: false, items: [] as Array<{ id: string; name: string; payload: Record<string, unknown> }> }
  await page.route('**/api/v1/chunk-presets**', async route => {
    if (route.request().method() === 'POST' || route.request().method() === 'PUT') {
      if (presets.fail) return json(route, { detail: '预设保存服务暂不可用' }, 503)
      const item = { ...route.request().postDataJSON(), id: 'saved-preset' }
      presets.items = [item]
      return json(route, item)
    }
    return json(route, { items: presets.items, total: presets.items.length })
  })
  return { state, presets }
}

async function config(page: Page) {
  await page.getByRole('button', { name: '打开高级切块配置', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '高级切块配置', exact: true })
  await expect(dialog.locator('[data-config-workbench]')).toBeVisible({ timeout: 30_000 })
  return dialog
}

test('B opens as a centered workbench; changes, failures and retry retain values while notifications expire', async ({ page }) => {
  const { state } = await setup(page)
  await open(page)
  const dialog = await config(page)
  const rect = await dialog.boundingBox()
  expect(rect!.width).toBeGreaterThanOrEqual(1000)
  expect(Math.abs(rect!.x + rect!.width / 2 - 800)).toBeLessThan(2)
  const editor = await dialog.locator('[data-config-editor]').boundingBox()
  const results = await dialog.locator('[data-config-results]').boundingBox()
  expect(editor!.width).toBeGreaterThan(results!.width)
  await dialog.getByRole('spinbutton', { name: '目标长度（字符）', exact: true }).fill('800')
  await dialog.getByRole('spinbutton', { name: '重叠长度（字符）', exact: true }).fill('120')
  const warning = notifications(page, 'warning').filter({ hasText: '参数已变更' })
  await expect(warning).toBeVisible()
  const toastRect = await warning.boundingBox()
  expect(Math.abs(toastRect!.x + toastRect!.width / 2 - 800)).toBeLessThan(12)
  expect(toastRect!.y).toBeLessThan(70)
  await page.mouse.move(20, 950)
  await expect(warning).toBeHidden({ timeout: 8000 })
  await expect(dialog.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })).toHaveValue('800')
  await expect(page.getByRole('button', { name: '确认入库', exact: true, includeHidden: true })).toBeDisabled()
  await dialog.getByRole('switch', { name: '切换全文索引 (BM25)', exact: true }).click()
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('mimirq_pipeline_options') || '{}').options?.bm25_index_enabled)).toBe(false)
  state.failPreview = true
  await dialog.getByRole('button', { name: '生成预览', exact: true }).click()
  await expect(notifications(page, 'error').filter({ hasText: '切块服务暂不可用' })).toBeVisible()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })).toHaveValue('800')
  state.failPreview = false
  await dialog.getByRole('button', { name: '生成预览', exact: true }).click()
  await expect.poll(() => state.previewQueries.at(-1)).toMatchObject({ chunk_size: '800', chunk_overlap: '120' })
  await expect(dialog.getByRole('button', { name: '生成预览', exact: true })).toBeEnabled()
  await page.screenshot({ path: path.join(evidence, 'desktop-b.png') })
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: '打开高级切块配置', exact: true })).toBeFocused()
  await page.reload()
  await expect(page.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })).toHaveValue('800')
})

test('preset editing stays inside B and retains input after failure, then reads the saved preset after reload', async ({ page }) => {
  const { presets } = await setup(page)
  await open(page)
  const dialog = await config(page)
  await dialog.getByRole('spinbutton', { name: '目标长度（字符）', exact: true }).fill('600')
  await dialog.getByRole('button', { name: '保存为预设', exact: true }).click()
  const form = dialog.getByRole('group', { name: '保存切块预设', exact: true })
  await form.getByRole('textbox', { name: '预设名称', exact: true }).fill('维护手册参数')
  await form.getByRole('textbox', { name: '预设说明', exact: true }).fill('保留这次的切分长度')
  presets.fail = true
  await form.getByRole('button', { name: '保存', exact: true }).click()
  await expect(notifications(page, 'error').filter({ hasText: '预设保存服务暂不可用' })).toBeVisible()
  await expect(form.getByRole('textbox', { name: '预设名称', exact: true })).toHaveValue('维护手册参数')
  expect(await page.getByRole('dialog').count()).toBe(1)
  presets.fail = false
  await form.getByRole('button', { name: '保存', exact: true }).click()
  await expect(form).toBeHidden()
  expect(presets.items[0]).toMatchObject({ name: '维护手册参数', payload: { chunk_size: 600 } })
  await page.screenshot({ path: path.join(evidence, 'preset-saved.png') })
  await page.reload()
  const reopened = await config(page)
  await reopened.getByRole('combobox', { name: '选择切块预设', exact: true }).click()
  await page.getByRole('option', { name: '维护手册参数', exact: true }).click()
  await expect(reopened.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })).toHaveValue('600')
})

test('B keeps its footer and input state reachable on phone and follows the global dark surface', async ({ page }) => {
  await setup(page)
  await open(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  const dialog = await config(page)
  await expect(dialog.getByRole('button', { name: '生成预览', exact: true })).toBeInViewport()
  await expect(dialog.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })).toHaveValue('1000')
  await dialog.getByRole('spinbutton', { name: '目标长度（字符）', exact: true }).fill('700')
  const message = notifications(page, 'warning').filter({ hasText: '参数已变更' })
  await expect(message).toBeVisible()
  const titleRect = await dialog.getByRole('heading', { name: '高级切块配置', exact: true }).boundingBox()
  await expect.poll(async () => (await message.boundingBox())?.y || 0).toBeGreaterThan(titleRect!.y + titleRect!.height)
  await dialog.getByRole('button', { name: '上次预览', exact: true }).click()
  await expect(dialog.locator('[data-config-results]')).toBeVisible()
  await expect(dialog.locator('[data-config-editor]')).toBeHidden()
  await page.screenshot({ path: path.join(evidence, 'phone-result.png') })
  await dialog.getByRole('button', { name: '参数设置', exact: true }).click()
  await expect(dialog.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })).toHaveValue('700')
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'phone-settings.png') })
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.evaluate(() => { localStorage.setItem('theme', 'dark'); localStorage.setItem('mimirq.surfaceTheme', 'earth') })
  await page.reload()
  const dark = await config(page)
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(dark.locator('[data-config-editor]')).toBeVisible()
  await expect(dark.locator('[data-config-results]')).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'dark-b.png') })
})

test('a second application page uses the same centered, finite success and error feedback', async ({ page }) => {
  await fixture(page)
  const state = { fail: true, items: [] as Array<Record<string, unknown>> }
  await page.route('**/api/v1/datasets**', async route => {
    if (route.request().method() === 'POST') {
      if (state.fail) return json(route, { detail: '数据集服务暂不可用' }, 503)
      const item = { ...route.request().postDataJSON(), id: 'created-feedback-dataset', document_count: 0, created_at: '2026-10-25T01:00:00Z' }
      state.items = [item]
      return json(route, item)
    }
    return json(route, { items: state.items, total: state.items.length })
  })
  await page.goto('/datasets', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '数据集', exact: true })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: '新建数据集', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: '新建数据集', exact: true })
  await dialog.getByRole('textbox', { name: '名称', exact: true }).fill('设备维护资料')
  await dialog.getByRole('button', { name: '确认创建', exact: true }).click()
  await expect(notifications(page, 'error').filter({ hasText: '数据集服务暂不可用' })).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: '名称', exact: true })).toHaveValue('设备维护资料')
  state.fail = false
  await dialog.getByRole('button', { name: '确认创建', exact: true }).click()
  await expect(dialog).toBeHidden()
  const success = notifications(page, 'success').filter({ hasText: '已创建数据集' })
  await expect(success).toBeVisible()
  const rect = await success.boundingBox()
  expect(Math.abs(rect!.x + rect!.width / 2 - 800)).toBeLessThan(12)
  expect(rect!.y).toBeLessThan(70)
  await page.screenshot({ path: path.join(evidence, 'dataset-success-toast.png') })
  await page.mouse.move(20, 950)
  await expect(success).toBeHidden({ timeout: 8000 })
  await expect(page.getByRole('button', { name: '查看 设备维护资料 详情', exact: true })).toBeVisible()
})

test('the gap metric opens the existing quality filter and retains a usable source/result view', async ({ page }) => {
  await setup(page, { gaps: true })
  await open(page)
  await page.getByRole('textbox', { name: '搜索切块内容', exact: true }).fill('保养记录')
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  const dialog = await config(page)
  await dialog.getByRole('button', { name: '查看断点', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('textbox', { name: '搜索切块内容', exact: true })).toHaveValue('')
  await expect(page.locator('[data-chunk-card]')).toHaveCount(2)
  await expect(page.locator('[data-compare-results] [data-page-scroll-container]')).toBeFocused()
  await page.getByRole('button', { name: '切块 #2', exact: true }).click()
  await expect(page.locator('[data-compare-original] mark')).toContainText('日常检查')
  await page.screenshot({ path: path.join(evidence, 'gap-review.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  await page.getByRole('button', { name: '文档原文', exact: true }).click()
  const phone = await config(page)
  await phone.getByRole('button', { name: '上次预览', exact: true }).click()
  await phone.getByRole('button', { name: '查看断点', exact: true }).click()
  await expect(phone).toBeHidden()
  await expect(page.locator('[data-compare-results]')).toBeVisible()
  await expect(page.locator('[data-compare-original]')).toBeHidden()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(2)
  await noOverflow(page)
})
