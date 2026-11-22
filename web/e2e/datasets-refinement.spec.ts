import { expect, test, type Page } from '@playwright/test'

import type { Dataset, DatasetUpdate } from '../types/datasets'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

function dataset(id: number, name: string, documents: number, chunks: number): Dataset {
  return {
    id: '10000000-0000-4000-8000-' + String(id).padStart(12, '0'),
    tenant_id: '20000000-0000-4000-8000-000000000001',
    name,
    description: '团队共享的产品与运维资料',
    permission: 'only_me',
    pipeline: null,
    operational_status: 'active',
    ingestion_summary: {
      total_documents: documents,
      total_chunks: chunks,
      total_size: 0,
      total_characters: 0,
      by_status: { completed: documents },
      last_processed_at: null,
    },
  }
}

async function mockDatasets(page: Page) {
  await installCommonApiMocks(page, { uploaded: false })
  const state = {
    items: [dataset(1, '产品资料', 0, 0), dataset(2, '运维手册', 2, 0), dataset(3, '接口文档', 3, 24)],
    patches: [] as Array<{ id: string; updates: DatasetUpdate }>,
    categoryIds: [] as string[],
    holdPatch: null as Promise<void> | null,
    failNextPatch: false,
    failList: false,
  }
  state.items[2].permission = 'partial_members'
  state.items[2].partial_member_list = ['member-1']
  const categoryId = '30000000-0000-4000-8000-000000000001'
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => {} } })
  })
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname.replace(/\/$/, '')
    if (pathname === '/api/v1/dataset-categories') {
      return route.fulfill({ json: { items: [{ id: categoryId, name: '生产文档', children: [] }] } })
    }
    if (pathname === '/api/v1/datasets' && request.method() === 'GET') {
      if (state.failList) return route.fulfill({ status: 503, json: { detail: '数据集服务暂时不可用' } })
      const empty = url.searchParams.get('operational_status') === 'testing'
      const skip = Number(url.searchParams.get('skip') || 0)
      const limit = Number(url.searchParams.get('limit') || 20)
      return route.fulfill({
        json: {
          items: empty ? [] : state.items.slice(skip, skip + limit),
          total: empty ? 0 : state.items.length,
          facets: {
            scope_total: state.items.length,
            filtered_total: empty ? 0 : state.items.length,
            status_counts: { active: state.items.length, testing: 0 },
          },
        },
      })
    }
    const assigned = /^\/api\/v1\/datasets\/([^/]+)\/categories$/.exec(pathname)
    if (assigned) {
      if (request.method() === 'PUT') state.categoryIds = request.postDataJSON().category_ids
      return route.fulfill({ json: { dataset_id: assigned[1], category_ids: state.categoryIds } })
    }
    const update = /^\/api\/v1\/datasets\/([^/]+)$/.exec(pathname)
    if (update && request.method() === 'PATCH') {
      const updates: DatasetUpdate = request.postDataJSON()
      state.patches.push({ id: update[1], updates })
      const gate = state.holdPatch
      state.holdPatch = null
      if (gate) await gate
      if (state.failNextPatch) {
        state.failNextPatch = false
        return route.fulfill({ status: 503, json: { detail: '保存服务暂时不可用' } })
      }
      const index = state.items.findIndex((item) => item.id === update[1])
      expect(index).toBeGreaterThanOrEqual(0)
      const next = { ...state.items[index], ...updates } as Dataset
      if (updates.pipeline && Object.keys(updates.pipeline).length === 0) next.pipeline = null
      state.items[index] = next
      return route.fulfill({ json: next })
    }
    return route.fallback()
  })
  return state
}

async function openDetails(page: Page, name: string) {
  await page.getByRole('button', { name: '查看 ' + name + ' 详情', exact: true }).click()
  await expect(page.getByTestId('dataset-inspector').getByRole('heading', { name, exact: true })).toBeVisible()
}

test('分类展开保持文字，状态与空数据分页如实表达，筛选不推动表头', async ({ page }, testInfo) => {
  await mockDatasets(page)
  await page.goto('/datasets')
  await expect(page.getByText('空数据集', { exact: true })).toBeVisible()
  await expect(page.getByText('待切块', { exact: true })).toBeVisible()
  await expect(page.getByText('已有切块', { exact: true })).toBeVisible()
  await expect(page.getByText('已就绪', { exact: true })).toHaveCount(0)
  const trigger = page.getByRole('button', { name: '选择数据集分类', exact: true })
  await trigger.click()
  await expect(trigger).toContainText('全部分类')
  const colors = await trigger.evaluate((element) => ({
    color: getComputedStyle(element).color,
    background: getComputedStyle(element).backgroundColor,
  }))
  expect(colors.color).not.toBe(colors.background)
  await expect(page.getByRole('button', { name: '管理分类', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('category-open.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  const table = page.getByRole('table', { name: '数据集', exact: true })
  const headerY = (await table.locator('thead').boundingBox())!.y
  const bounds = (await table.boundingBox())!
  const footer = (await page.locator('footer[data-task-center-dock]').boundingBox())!
  expect(footer.y - bounds.y - bounds.height).toBeLessThan(20)
  await page.getByRole('button', { name: '测试集', exact: true }).click()
  await expect(page.getByRole('heading', { name: '未找到匹配的数据集' })).toBeVisible()
  expect((await table.locator('thead').boundingBox())!.y).toBe(headerY)
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '重置筛选', exact: true })).toHaveCount(1)
  await expect(page.getByRole('button', { name: '清除筛选', exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('filtered-empty.png'), animations: 'disabled' })
})

test('配置保存归属原数据集，失败保留已确认值，刷新读回成功配置', async ({ page }, testInfo) => {
  const state = await mockDatasets(page)
  await page.goto('/datasets')
  await openDetails(page, '产品资料')
  let releaseSave = () => {}
  state.holdPatch = new Promise<void>((resolve) => {
    releaseSave = resolve
  })
  await page.getByRole('combobox', { name: '访问权限', exact: true }).click()
  await page.getByRole('option', { name: '全员可见', exact: true }).click()
  try {
    await expect(page.getByRole('status').filter({ hasText: '正在保存…' })).toBeVisible()
    await openDetails(page, '运维手册')
    await expect(page.getByText('正在保存其他更改', { exact: true })).toBeVisible()
    await expect(page.getByRole('switch')).toBeDisabled()
  } finally {
    releaseSave()
  }
  await expect(page.getByRole('switch')).toBeEnabled()
  await expect(page.getByRole('combobox', { name: '访问权限', exact: true })).toContainText('仅自己')
  expect(state.patches[0].id).toBe(state.items[0].id)
  expect(state.patches[0].updates).toEqual({ permission: 'all_team_members' })
  await openDetails(page, '产品资料')
  await expect(page.getByRole('combobox', { name: '访问权限', exact: true })).toContainText('全员可见')
  state.failNextPatch = true
  await page.getByRole('switch').click()
  await expect(page.getByText('未保存，请重试', { exact: true })).toBeVisible()
  await expect(page.getByRole('switch')).not.toBeChecked()
  await page.getByRole('switch').click()
  await expect(page.getByRole('switch')).toBeChecked()
  await expect(page.getByText('已自动保存', { exact: true })).toBeVisible()
  await page.reload()
  await openDetails(page, '产品资料')
  await expect(page.getByRole('switch')).toBeChecked()
  await expect(page.getByRole('combobox', { name: '访问权限', exact: true })).toContainText('全员可见')
  await page.screenshot({ path: testInfo.outputPath('detail-saved.png'), animations: 'disabled' })
})

test('基础信息不覆盖权限管线，可清空描述，已有部分成员和分类仍能编辑', async ({ page }) => {
  const state = await mockDatasets(page)
  await page.goto('/datasets')
  await openDetails(page, '接口文档')
  await page.getByRole('button', { name: '编辑允许成员', exact: true }).click()
  const access = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '编辑访问权限', exact: true }) })
  await expect(access).toBeVisible()
  expect(state.patches).toHaveLength(0)
  await access.getByLabel(/允许成员/).fill('member-2')
  await access.getByRole('button', { name: '保存变更', exact: true }).click()
  await expect(access).toHaveCount(0)
  expect(state.patches[0].updates).toEqual({
    permission: 'partial_members',
    partial_member_list: ['member-2'],
    partial_group_list: [],
  })
  await openDetails(page, '产品资料')
  await page.getByRole('button', { name: '编辑基础信息', exact: true }).click()
  const basics = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '编辑基础信息', exact: true }) })
  await expect(basics.getByRole('combobox')).toHaveCount(0)
  await expect(basics.getByRole('switch')).toHaveCount(0)
  await basics.getByLabel('名称', { exact: true }).fill('产品资料（已整理）')
  await basics.getByLabel('描述（可选）', { exact: true }).fill('')
  await basics.getByRole('button', { name: '保存变更', exact: true }).click()
  await expect(basics).toHaveCount(0)
  expect(state.patches[1].updates).toEqual({ name: '产品资料（已整理）', description: '' })
  await page.reload()
  await openDetails(page, '产品资料（已整理）')
  await page.getByRole('button', { name: '复制数据集 ID', exact: true }).click()
  await expect(page.getByRole('button', { name: '已复制数据集 ID', exact: true })).toBeVisible()
  await page.getByTestId('dataset-inspector').getByRole('button', { name: '编辑', exact: true }).click()
  const categories = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '编辑分类', exact: true }) })
  await categories.getByRole('checkbox', { name: '生产文档', exact: true }).check()
  await categories.getByRole('button', { name: '保存', exact: true }).click()
  await expect(categories).toHaveCount(0)
  await expect(page.getByTestId('dataset-inspector').getByText('生产文档', { exact: true })).toBeVisible()
  expect(state.categoryIds).toHaveLength(1)
  await page.getByRole('button', { name: '调整管线选项', exact: true }).click()
  const pipeline = page.getByRole('dialog', { name: '编辑默认管线', exact: true })
  await expect(pipeline.getByRole('button', { name: '保存变更', exact: true })).toBeEnabled()
  await pipeline.getByRole('button', { name: '保存变更', exact: true }).click()
  await expect(pipeline).toHaveCount(0)
  expect(state.patches.at(-1)?.updates).toEqual({ pipeline: {} })
})

test('基础信息打开时光标置尾，只有有效改动允许保存，失败保留输入', async ({ page }, testInfo) => {
  const state = await mockDatasets(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/datasets')
  await page.getByRole('button', { name: '产品资料的更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '编辑基础信息', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '编辑基础信息', exact: true })
  const name = dialog.getByLabel('名称', { exact: true })
  const description = dialog.getByLabel('描述（可选）', { exact: true })
  const save = dialog.getByRole('button', { name: '保存变更', exact: true })
  await expect(name).toBeFocused()
  expect(await name.evaluate((input: HTMLInputElement) => [input.selectionStart, input.selectionEnd])).toEqual([
    state.items[0].name.length,
    state.items[0].name.length,
  ])
  await expect(save).toBeDisabled()
  await page.screenshot({ path: testInfo.outputPath('basics-pristine.png'), animations: 'disabled' })
  await name.fill('  产品资料  ')
  await description.fill('  团队共享的产品与运维资料  ')
  await expect(save).toBeDisabled()
  await description.fill('更新后的用途说明')
  await name.fill('   ')
  await expect(save).toBeDisabled()
  await name.fill('产品资料')
  await expect(save).toBeEnabled()
  await page.screenshot({ path: testInfo.outputPath('basics-dirty.png'), animations: 'disabled' })
  state.failNextPatch = true
  await save.click()
  await expect(page.getByText('保存服务暂时不可用', { exact: false })).toBeVisible()
  await expect(description).toHaveValue('更新后的用途说明')
  await expect(save).toBeEnabled()
  await save.click()
  await expect(dialog).toHaveCount(0)
  expect(state.patches.at(-1)?.updates).toEqual({ name: '产品资料', description: '更新后的用途说明' })
  await page.reload()
  await page.getByRole('button', { name: '产品资料的更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '编辑基础信息', exact: true }).click()
  await expect(description).toHaveValue('更新后的用途说明')
  await expect(save).toBeDisabled()
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await openDetails(page, '产品资料')
  await page.getByRole('button', { name: '编辑基础信息', exact: true }).click()
  await expect(name).toBeFocused()
  expect(await name.evaluate((input: HTMLInputElement) => [input.selectionStart, input.selectionEnd])).toEqual([4, 4])
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await page.getByRole('button', { name: '产品资料的更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '编辑基础信息', exact: true }).click()
  await expect(save).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: testInfo.outputPath('basics-mobile.png'), animations: 'disabled' })
})

test('行级菜单分组完整，浅色焦点支持键盘导航与危险操作确认', async ({ page }, testInfo) => {
  await mockDatasets(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/datasets')
  const trigger = page.getByRole('button', { name: '产品资料的更多操作', exact: true })
  await trigger.focus()
  await page.keyboard.press('ArrowDown')
  const menu = page.getByRole('menu')
  const details = menu.getByRole('menuitem', { name: '数据集详情', exact: true })
  await expect(details).toBeFocused()
  const focused = await details.evaluate((element) => ({
    text: getComputedStyle(element).color,
    background: getComputedStyle(element).backgroundColor,
    menuText: getComputedStyle(element.closest('[role="menu"]')!).color,
  }))
  expect(focused.text).toBe(focused.menuText)
  expect(focused.background).not.toBe('rgba(0, 0, 0, 0)')
  await expect(menu.getByRole('group', { name: '基础信息', exact: true }).getByRole('menuitem')).toHaveText([
    '数据集详情',
    '编辑基础信息',
  ])
  await expect(menu.getByRole('group', { name: '数据集工具', exact: true }).getByRole('menuitem')).toHaveText([
    '文档预检',
    '数据画像',
    '表格资产',
    '数据库目录',
  ])
  await expect(menu.getByRole('group', { name: '危险操作', exact: true }).getByRole('menuitem')).toHaveText([
    '删除数据集',
  ])
  await page.screenshot({ path: testInfo.outputPath('row-menu-focused.png'), animations: 'disabled' })
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByRole('menuitem', { name: '编辑基础信息', exact: true })).toBeFocused()
  await page.keyboard.press('End')
  const remove = menu.getByRole('menuitem', { name: '删除数据集', exact: true })
  await expect(remove).toBeFocused()
  expect(await remove.evaluate((element) => getComputedStyle(element).color)).not.toBe(focused.text)
  await page.keyboard.press('Enter')
  await expect(page.getByRole('alertdialog')).toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByRole('button', { name: '查看 产品资料 详情', exact: true })).toBeFocused()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await trigger.click()
  await expect(page.getByRole('menuitem', { name: '入库管理', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: '检索测试', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: '流程编排', exact: true })).toHaveCount(0)
  const mobileMenu = (await menu.boundingBox())!
  expect(mobileMenu.y).toBeGreaterThanOrEqual(0)
  expect(mobileMenu.y + mobileMenu.height).toBeLessThanOrEqual(844)
  await page.keyboard.press('End')
  await expect(remove).toBeFocused()
  const mobileRemove = (await remove.boundingBox())!
  expect(mobileRemove.y + mobileRemove.height).toBeLessThanOrEqual(844)
  await page.screenshot({ path: testInfo.outputPath('row-menu-mobile.png'), animations: 'disabled' })
})

test('旧数据集编排地址返回页面不存在', async ({ page }) => {
  const state = await mockDatasets(page)
  for (const prefix of ['', '/zh-CN']) {
    const response = await page.goto(`${prefix}/datasets/${state.items[0].id}/workflow`)
    expect(response?.status()).toBe(404)
    await expect(page.getByRole('heading', { name: '页面不存在', exact: true })).toBeVisible()
  }
})

test('手机列表与详情无横向溢出，加载失败不显示成功空态', async ({ page }, testInfo) => {
  const state = await mockDatasets(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/datasets')
  await expect(page.getByRole('button', { name: '查看 产品资料 详情', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: testInfo.outputPath('mobile-list.png'), animations: 'disabled' })
  await openDetails(page, '产品资料')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  const edit = (await page.getByRole('button', { name: '编辑基础信息', exact: true }).boundingBox())!
  expect(edit.y + edit.height).toBeLessThanOrEqual(844)
  await page.screenshot({ path: testInfo.outputPath('mobile-detail.png'), animations: 'disabled' })
  state.failList = true
  await page.reload()
  await expect(page.getByRole('heading', { name: '数据集加载失败' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '暂无数据集', exact: true })).toHaveCount(0)
})

test('长列表在表格内滚动，翻页继续使用服务端分页', async ({ page }) => {
  const state = await mockDatasets(page)
  state.items = Array.from({ length: 25 }, (_, index) => dataset(index + 1, '资料 ' + (index + 1), 1, 8))
  await page.goto('/datasets')
  await expect(page.locator('[data-dataset-row]')).toHaveCount(20)
  const scroll = await page.locator('[data-dataset-catalog-scroll]').evaluate((element) => ({
    height: element.clientHeight,
    content: element.scrollHeight,
  }))
  expect(scroll.content).toBeGreaterThan(scroll.height)
  const nextPage = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return url.pathname.replace(/\/$/, '') === '/api/v1/datasets' && url.searchParams.get('skip') === '20'
  })
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await nextPage
  await expect(page.locator('[data-dataset-row]')).toHaveCount(5)
  await expect(page.getByRole('button', { name: '查看 资料 21 详情', exact: true })).toBeVisible()
})
