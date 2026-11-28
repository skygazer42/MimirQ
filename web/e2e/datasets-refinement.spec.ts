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
      return route.fulfill({
        json: {
          total: 2,
          items: [
            {
              id: categoryId,
              name: '生产文档',
              depth: 0,
              datasets: 3,
              children: [{ id: categoryId + '-child', name: '技术规范', depth: 1, datasets: 1, children: [] }],
            },
          ],
        },
      })
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
    if (pathname === '/api/v1/datasets' && request.method() === 'POST') {
      const created = dataset(4, request.postDataJSON().name, 0, 0)
      state.items.unshift(created)
      return route.fulfill({ status: 201, json: created })
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
  const surface =
    page.viewportSize()!.width >= 1280
      ? page.getByRole('complementary', { name: '数据集详情', exact: true })
      : page.getByRole('dialog', { name: '数据集详情', exact: true })
  await expect(surface.getByRole('heading', { name, exact: true })).toBeVisible()
  await expect(page.getByTestId('dataset-inspector')).toHaveCount(1)
  await expect(page.getByTestId('dataset-inspector')).toBeVisible()
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 620 },
  { width: 390, height: 844 },
]) {
  test(`新建和编辑默认管线在 ${viewport.width}×${viewport.height} 内滚动且不遮挡操作`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    const state = await mockDatasets(page)
    await page.route('**/api/v1/pipeline/governance-profiles?*', (route) =>
      route.fulfill({ json: { items: [], total: 0 } }),
    )
    await page.goto('/datasets')

    for (const mode of ['create', 'edit'] as const) {
      if (mode === 'create') {
        await page.getByRole('button', { name: '新建数据集', exact: true }).click()
      } else {
        await openDetails(page, '产品资料')
        await page.getByRole('button', { name: '调整管线选项', exact: true }).click()
      }
      const dialog = page.getByRole('dialog', {
        name: mode === 'create' ? '新建数据集' : '编辑默认管线',
        exact: true,
      })
      if (mode === 'create') await dialog.getByLabel('名称', { exact: true }).fill('管线布局验证')
      await dialog.getByRole('checkbox', { name: '数据集默认管线', exact: true }).check()
      await dialog.locator('summary').filter({ hasText: '高级治理参数' }).click()
      await expect(dialog.getByText('详情', { exact: true })).toHaveCount(0)
      expect(
        await dialog
          .locator('details')
          .evaluateAll((elements) => elements.every((element) => element.firstElementChild?.tagName === 'SUMMARY')),
      ).toBe(true)

      const body = dialog.locator('[data-dataset-dialog-body="true"]')
      const submit = dialog.getByRole('button', { name: mode === 'create' ? '确认创建' : '保存变更', exact: true })
      const footer = submit.locator('..')
      const header = dialog.getByRole('heading').locator('..')
      await expect(body).toHaveCSS('overflow-y', 'auto')
      await expect(dialog).toHaveCSS('overflow', 'hidden')
      await body.evaluate((element) => {
        element.scrollTop = 0
      })
      const content = await body.evaluate((element) => ({
        height: element.clientHeight,
        scrollHeight: element.scrollHeight,
        width: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }))
      expect(content.scrollHeight).toBeGreaterThan(content.height)
      expect(content.scrollWidth).toBeLessThanOrEqual(content.width)
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)

      const shellBounds = (await dialog.boundingBox())!
      expect(shellBounds.x).toBeGreaterThanOrEqual(0)
      expect(shellBounds.y).toBeGreaterThanOrEqual(0)
      expect(shellBounds.x + shellBounds.width).toBeLessThanOrEqual(viewport.width)
      expect(shellBounds.y + shellBounds.height).toBeLessThanOrEqual(viewport.height)
      for (const surface of [header, footer]) {
        await expect(surface).toHaveCSS('flex-shrink', '0')
        expect(await surface.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(
          'rgba(0, 0, 0, 0)',
        )
      }
      const headerBounds = (await header.boundingBox())!
      const bodyBounds = (await body.boundingBox())!
      const footerBounds = (await footer.boundingBox())!
      expect(bodyBounds.y).toBeGreaterThanOrEqual(headerBounds.y + headerBounds.height - 1)
      expect(bodyBounds.y + bodyBounds.height).toBeLessThanOrEqual(footerBounds.y + 1)
      await page.screenshot({ path: testInfo.outputPath(`${mode}-pipeline-top.png`), animations: 'disabled' })

      await body.hover()
      await page.mouse.wheel(0, content.scrollHeight)
      await expect.poll(() => body.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
      expect((await header.boundingBox())!.y).toBeCloseTo(headerBounds.y, 0)
      expect((await footer.boundingBox())!.y).toBeCloseTo(footerBounds.y, 0)
      await expect(dialog.getByText('自定义配置已生效', { exact: true })).toBeInViewport({ ratio: 1 })
      await expect(submit).toBeEnabled()
      await submit.click({ trial: true })
      await page.screenshot({ path: testInfo.outputPath(`${mode}-pipeline-bottom.png`), animations: 'disabled' })
      await dialog.getByRole('button', { name: '取消', exact: true }).click()
      await expect(dialog).toHaveCount(0)
    }
    expect(state.patches).toHaveLength(0)
  })
}

test('三分区保留轻字重、真实状态与分类，卡片列表切换持久化且筛选不推动内容区', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockDatasets(page)
  await page.goto('/datasets')
  const catalog = page.getByRole('region', { name: '数据集列表', exact: true })
  await expect(page.locator('[data-dataset-card]')).toHaveCount(3)
  for (const status of ['空数据集', '待切块', '已有切块']) {
    await expect(catalog.getByText(status, { exact: true })).toBeVisible()
  }
  await expect(page.getByText('已就绪', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '查看 产品资料 详情', exact: true })).toHaveCSS('font-weight', '500')
  await expect(page.getByRole('button', { name: '查看 产品资料 详情', exact: true })).toHaveCSS('font-size', '14px')
  await expect(page.getByTestId('datasets-page-toolbar')).toHaveCSS('height', '52px')
  await expect(page.getByTestId('datasets-command-toolbar')).toHaveCSS('height', '48px')
  const rail = page.getByRole('complementary', { name: '数据分类', exact: true })
  await expect(rail).toHaveCSS('width', '208px')
  await expect(rail.getByRole('button', { name: '全部数据集', exact: false })).toContainText('3')
  await expect(rail.getByRole('button', { name: '技术规范', exact: false })).toBeVisible()
  await rail.getByRole('button', { name: '收起生产文档', exact: true }).click()
  await expect(rail.getByRole('button', { name: '技术规范', exact: false })).toHaveCount(0)
  await rail.getByRole('button', { name: '展开生产文档', exact: true }).click()
  await rail.getByRole('button', { name: '生产文档', exact: true }).click()
  await expect(page.getByRole('button', { name: '重置筛选', exact: true })).toHaveCount(1)
  await page.getByRole('button', { name: '重置筛选', exact: true }).click()
  await rail.getByRole('button', { name: '管理分类', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '管理分类', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: '收起分类目录', exact: true }).click()
  await expect(rail).toHaveCount(0)
  await page.getByRole('button', { name: '切换分类目录', exact: true }).click()
  await expect(rail).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('datasets-desktop-cards.png'), animations: 'disabled' })

  await page.getByRole('button', { name: '列表视图', exact: true }).click()
  const table = page.getByRole('table', { name: '数据集', exact: true })
  await expect(page.locator('[data-dataset-card]')).toHaveCount(0)
  await expect(table.locator('th').first()).toHaveCSS('height', '38px')
  await expect(table.locator('tbody tr').first()).toHaveCSS('height', '48px')
  const statusDots = table.locator('[data-state] > span[aria-hidden="true"]')
  await expect(statusDots).toHaveCount(3)
  for (const dot of await statusDots.all()) {
    await expect(dot).toHaveCSS('width', '6px')
    await expect(dot).toHaveCSS('height', '6px')
  }
  expect(
    new Set(await statusDots.evaluateAll((dots) => dots.map((dot) => getComputedStyle(dot).backgroundColor))).size,
  ).toBe(3)
  await expect(rail).toHaveCount(0)
  const categoryTrigger = page.getByRole('button', { name: '切换分类目录', exact: true })
  await categoryTrigger.click()
  const categoryPopover = page.getByRole('dialog', { name: '数据分类', exact: true })
  await expect(categoryPopover.getByRole('button', { name: '技术规范', exact: true })).toBeVisible()
  await categoryPopover.getByRole('button', { name: '技术规范', exact: true }).click()
  await expect(categoryPopover).toBeHidden()
  await expect(categoryTrigger).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('button', { name: '重置筛选', exact: true })).toHaveCount(1)
  await page.getByRole('button', { name: '重置筛选', exact: true }).click()
  await page.reload()
  await expect(page.getByRole('button', { name: '列表视图', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(table).toBeVisible()
  await page.getByRole('button', { name: '产品资料的更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '数据集详情', exact: true }).click()
  await expect(page.getByRole('complementary', { name: '数据集详情', exact: true })).toBeFocused()
  await page.screenshot({ path: testInfo.outputPath('datasets-desktop-list.png'), animations: 'disabled' })
  const scroll = page.locator('[data-dataset-catalog-scroll]')
  const stageY = (await scroll.boundingBox())!.y
  const stageBounds = (await scroll.boundingBox())!
  const footer = (await page.locator('footer[data-task-center-dock]').boundingBox())!
  expect(footer.y).toBeCloseTo(stageBounds.y + stageBounds.height, 0)
  expect(footer.height).toBe(44)
  await page.getByRole('button', { name: '测试集', exact: true }).click()
  await expect(page.getByRole('heading', { name: '未找到匹配的数据集' })).toBeVisible()
  expect((await scroll.boundingBox())!.y).toBe(stageY)
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '重置筛选', exact: true })).toHaveCount(1)
  await page.screenshot({ path: testInfo.outputPath('filtered-empty.png'), animations: 'disabled' })
})

test('empty dataset catalog offers one primary create action on desktop and phone', async ({ page }, testInfo) => {
  const state = await mockDatasets(page)
  state.items = []
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/datasets')
  const workspace = page.getByTestId('datasets-workspace')
  const create = workspace.getByRole('button', { name: '新建数据集', exact: true })
  await expect(workspace.getByRole('heading', { name: '暂无数据集', exact: true })).toBeVisible()
  await expect(workspace.getByRole('table', { name: '数据集', exact: true })).toHaveCount(0)
  const band = workspace.locator('[data-dataset-empty-band]')
  const bandBounds = (await band.boundingBox())!
  const stageBounds = (await page.locator('[data-dataset-catalog-scroll]').boundingBox())!
  expect(Math.abs(bandBounds.y - stageBounds.y)).toBeLessThanOrEqual(1)
  expect(bandBounds.height).toBeGreaterThanOrEqual(360)
  await expect(page.getByTestId('datasets-command-toolbar')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('datasets-starter-desktop.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(create).toBeInViewport({ ratio: 1 })
  expect((await band.boundingBox())!.height).toBeGreaterThanOrEqual(360)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: testInfo.outputPath('datasets-starter-mobile.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 1440, height: 900 })

  await page.getByRole('link', { name: '知识库', exact: true }).click()
  const knowledgeHeader = page.getByTestId('knowledge-page-toolbar')
  await expect(knowledgeHeader).toHaveCSS('height', '52px')
  await expect(knowledgeHeader.getByRole('heading', { name: '知识库', exact: true })).toBeVisible()
  await expect(knowledgeHeader.getByRole('button', { name: '任务历史', exact: true })).toBeVisible()
  await expect(knowledgeHeader.getByRole('button', { name: '检索测试', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '知识库暂无文档', exact: true })).toBeVisible()
  await expect(page.locator('[data-knowledge-scope-rail], [aria-label="文档筛选与排序"], [data-task-center-dock]')).toHaveCount(0)
  await expect(page.getByRole('table', { name: '知识库文档列表', exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('knowledge-no-datasets.png'), animations: 'disabled' })

  await page.getByRole('link', { name: '数据集', exact: true }).click()
  await create.click()
  const dialog = page.getByRole('dialog', { name: '新建数据集', exact: true })
  await dialog.getByLabel('名称', { exact: true }).fill('gfgfd')
  await dialog.getByRole('button', { name: '确认创建', exact: true }).click()
  await expect(workspace.getByRole('button', { name: '查看 gfgfd 详情', exact: true })).toBeVisible()
  await page.getByRole('link', { name: '知识库', exact: true }).click()
  const rail = page.getByRole('complementary', { name: '数据集与目录', exact: true })
  await expect(rail.getByRole('button', { name: 'gfgfd 0', exact: true })).toBeVisible()
  await expect(knowledgeHeader.getByText('全部数据集', { exact: true })).toBeVisible()
})

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 390, height: 844 },
]) {
  test(`dense dataset catalog fills the workspace at ${viewport.width}×${viewport.height}`, async ({ page }) => {
    const state = await mockDatasets(page)
    state.items = Array.from({ length: 25 }, (_, index) => dataset(index + 1, '资料 ' + (index + 1), 1, 8))
    await page.setViewportSize(viewport)
    await page.goto('/datasets')
    await expect(page.locator('[data-dataset-row]')).toHaveCount(20)
    await expect(page.getByTestId('datasets-page-toolbar')).toHaveCSS('height', '52px')
    const scroll = page.locator('[data-dataset-catalog-scroll]')
    await expect(page.locator('[data-dataset-card]')).toHaveCount(20)
    const grid = page.locator('[data-dataset-card]').first().locator('..')
    expect(await grid.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(
      viewport.width < 640 ? 1 : 2,
    )
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)
    expect(await scroll.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
    await page.getByRole('button', { name: '列表视图', exact: true }).click()
    const table = page.getByRole('table', { name: '数据集', exact: true })
    expect((await table.boundingBox())!.width).toBeCloseTo(await scroll.evaluate((element) => element.clientWidth), 0)
    await expect(table.locator('tbody tr').first()).toHaveCSS('height', viewport.width < 768 ? '64px' : '48px')
    await expect(page.getByRole('button', { name: '查看 资料 1 详情', exact: true })).toHaveCSS('font-size', '13px')
    await expect(page.getByRole('button', { name: '查看 资料 1 详情', exact: true })).toHaveCSS('font-weight', '400')
    await page.screenshot({ path: test.info().outputPath('datasets-dense-catalog.png'), animations: 'disabled' })
  })
}

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
    '入库管理',
    '检索测试',
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
  await page.getByRole('button', { name: '列表视图', exact: true }).click()
  await expect(page.getByText('2 篇文档', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '切换分类目录', exact: true }).click()
  const categorySheet = page.getByRole('dialog', { name: '数据分类', exact: true })
  await expect(categorySheet.getByRole('button', { name: '生产文档', exact: true })).toBeVisible()
  await categorySheet.getByRole('button', { name: 'Close', exact: true }).click()
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
  await page.screenshot({ path: testInfo.outputPath('mobile-load-error.png'), animations: 'disabled' })
})

test('检查器在桌面、平板和短手机只渲染一份，保留真实指标、工具与固定操作', async ({ page }, testInfo) => {
  const state = await mockDatasets(page)
  const item = state.items[0]
  item.name = 'ui-redesign-verification-20261027'
  item.description = 'Dedicated UI verification dataset; no production documents.'
  item.ingestion_summary!.total_size = 4.6 * 1024 * 1024
  item.ingestion_summary!.total_documents = 3
  item.ingestion_summary!.by_status = { failed: 2, quarantined: 1 }
  item.operational_status = 'anomaly'
  item.pipeline = { governance_enabled: true, chunk_vector_enabled: true, bm25_index_enabled: true, kg_enabled: true }
  item.embedding_defaults = { model: 'text-embedding-3-small' }
  await page.goto('/datasets')
  for (const [label, width, height] of [
    ['desktop', 1440, 1000],
    ['tablet', 1100, 844],
    ['phone', 390, 844],
    ['short-phone', 390, 640],
  ] as const) {
    await page.setViewportSize({ width, height })
    await page.locator('[data-dataset-card]').first().locator('dl').click()
    const surface =
      width >= 1280
        ? page.getByRole('complementary', { name: '数据集详情', exact: true })
        : page.getByRole('dialog', { name: '数据集详情', exact: true })
    const inspector = page.getByTestId('dataset-inspector')
    await expect(inspector).toHaveCount(1)
    await inspector.evaluate((element) => {
      element.scrollTop = 0
    })
    await expect(page.getByRole('combobox', { name: '访问权限', exact: true })).toHaveCount(1)
    await expect(inspector.getByText(item.description, { exact: true })).toBeVisible()
    await expect(inspector.getByText('4.6 MB', { exact: true })).toBeVisible()
    await expect(inspector.getByText('异常文档 3 篇', { exact: true })).toHaveAttribute(
      'href',
      '/knowledge?dataset=' + item.id,
    )
    await expect(inspector.getByText('已启用默认管线（治理 · 向量 · BM25 · 图谱）', { exact: true })).toHaveCount(1)
    await expect(surface.getByRole('heading', { name: item.name, exact: true })).toHaveCSS('font-weight', '500')
    await expect(surface.getByRole('heading', { name: item.name, exact: true })).toHaveAttribute('title', item.name)
    const footer = surface.locator('footer')
    await expect(footer).toBeInViewport({ ratio: 1 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await inspector.evaluate((element) => {
      element.scrollTop = element.scrollHeight
    })
    const nav = surface.getByRole('navigation', { name: '数据集操作' })
    await expect(nav.getByRole('link')).toHaveCount(5)
    await expect(nav.getByRole('link', { name: /数据画像/ })).toBeInViewport({ ratio: 1 })
    await expect(surface.getByRole('link', { name: '知识图谱', exact: true })).toHaveAttribute(
      'href',
      '/datasets/' + item.id + '/kg',
    )
    await page.screenshot({ path: testInfo.outputPath('inspector-' + label + '.png'), animations: 'disabled' })
    if (width < 1280) {
      await surface.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(surface).toHaveCount(0)
    }
  }
  expect(state.patches).toHaveLength(0)
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
