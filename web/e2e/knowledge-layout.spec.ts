import { expect, test, type Page } from '@playwright/test'
import {
  installCommonApiMocks,
  UPLOADED_DOCUMENT_FILENAME,
  UPLOADED_DOCUMENT_ID,
} from './enterprise-quality-telemetry.helpers'

async function fixture(page: Page) {
  await installCommonApiMocks(page, { uploaded: true })
  await page.route('**/api/v1/rbac/me', (route) =>
    route.fulfill({
      json: {
        tenant_id: '00000000-0000-0000-0000-000000000000',
        account_id: 'layout-review',
        role: 'owner',
        permissions: ['settings.read', 'settings.write'],
        is_active: true,
        is_current: true,
      },
    }),
  )
  await page.route('**/api/v1/datasets**', (route) =>
    route.fulfill({
      json: {
        items: [
          { id: 'dataset-layout', name: '产品资料', permission: 'me', ingestion_summary: { total_documents: 2 } },
        ],
        total: 1,
      },
    }),
  )
  await page.route('**/api/v1/pipeline/governance-profiles?*', (route) =>
    route.fulfill({ json: { items: [], total: 0 } }),
  )
  await page.route('**/api/v1/documents/stats**', (route) =>
    route.fulfill({
      json: { total: 2, total_chunks: 3, total_size: 2048, by_status: { completed: 1, quarantined: 1 } },
    }),
  )
  await page.route('**/api/v1/documents/folders**', (route) =>
    route.fulfill({
      json: {
        total_documents: 2,
        total_with_source_path: 2,
        root: {
          name: '',
          path: '',
          depth: 0,
          documents: 2,
          children: [{ name: '手册', path: '手册', depth: 1, documents: 2, children: [] }],
        },
      },
    }),
  )
  await page.route(/\/api\/v1\/documents\/?(?:\?.*)?$/, (route) => {
    const document = {
      id: UPLOADED_DOCUMENT_ID,
      dataset_id: 'dataset-layout',
      filename: UPLOADED_DOCUMENT_FILENAME,
      file_type: 'md',
      file_size: 1024,
      status: 'completed',
      chunk_count: 3,
      processing_attempts: 2,
      created_at: '2026-11-24T00:00:00Z',
      updated_at: '2026-11-24T00:00:00Z',
      metadata: {},
    }
    return route.fulfill({
      json: {
        items: [
          document,
          {
            ...document,
            id: 'quarantined-layout',
            filename: '待审查.md',
            status: 'quarantined',
            error_message: '等待内容安全审核',
          },
        ],
        total: 2,
      },
    })
  })
}

const dialogs = [
  { menu: '通过 URL', title: '通过 URL 导入文档', action: '开始导入', close: '取消' },
  { menu: 'URL 批量（Connector）', title: 'URL 批量导入（Connector）', action: '开始导入', close: '取消' },
  { menu: 'Website Crawl', title: 'Website Crawl (Connector)', action: 'Start', close: 'Cancel' },
  { menu: 'Jira Project', title: 'Jira Project (Connector)', action: 'Start Jira Sync', close: 'Cancel' },
  { menu: '管线配置', title: '入库管线配置', action: '完成', close: '完成' },
] as const

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 620 },
]) {
  test(`knowledge import actions remain visible at ${viewport.width}×${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await fixture(page)
    await page.goto('/knowledge')
    for (const entry of dialogs) {
      await page.getByRole('button', { name: '导入文档', exact: true }).click()
      await page.getByRole('menuitem', { name: entry.menu, exact: true }).click()
      const dialog = page.getByRole('dialog', { name: entry.title, exact: true })
      const body = dialog.locator('[data-knowledge-dialog-body]')
      const action = dialog.getByRole('button', { name: entry.action, exact: true })
      const footer = action.locator('..')
      const header = dialog.getByRole('heading', { name: entry.title, exact: true }).locator('..')
      await dialog.getByRole('switch', { name: '切换自定义管线', exact: true }).check()
      await expect(dialog).toBeInViewport({ ratio: 1 })
      await expect(dialog).toHaveCSS('overflow', 'hidden')
      await expect(body).toHaveCSS('overflow-y', 'auto')
      expect(await body.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
      await body.evaluate((element) => {
        element.scrollTop = 0
      })
      await expect(action).toBeInViewport({ ratio: 1 })
      await expect(dialog.getByRole('button', { name: entry.close, exact: true })).toBeInViewport({ ratio: 1 })
      const headerBounds = (await header.boundingBox())!
      const footerBounds = (await footer.boundingBox())!
      const bodyBounds = (await body.boundingBox())!
      expect(bodyBounds.y).toBeGreaterThanOrEqual(headerBounds.y + headerBounds.height - 1)
      expect(bodyBounds.y + bodyBounds.height).toBeLessThanOrEqual(footerBounds.y + 1)
      expect(footerBounds.y + footerBounds.height).toBeLessThanOrEqual(viewport.height)
      await body.evaluate((element) => {
        element.scrollTop = element.scrollHeight
      })
      await expect.poll(() => body.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
      expect((await header.boundingBox())!.y).toBeCloseTo(headerBounds.y, 0)
      expect((await footer.boundingBox())!.y).toBeCloseTo(footerBounds.y, 0)
      await expect(action).toBeInViewport({ ratio: 1 })
      await dialog.getByRole('button', { name: entry.close, exact: true }).click()
      await expect(dialog).toHaveCount(0)
    }
  })
}

async function expectControlsInsideWorkspace(page: Page) {
  const workspace = page.locator('[data-knowledge-page-root]')
  const workspaceBounds = (await workspace.boundingBox())!
  const filters = workspace.locator('[aria-label="处理状态"]')
  await expect(filters.getByRole('button', { name: /隔离\s*1/ })).toBeVisible()
  for (const control of [
    workspace.getByText('导入文档', { exact: true }),
    workspace.getByRole('button', { name: '任务历史', exact: true }),
    workspace.getByRole('button', { name: '任务历史', exact: true }).getByText('任务', { exact: true }),
    ...(await filters.getByRole('button').all()),
  ]) {
    await expect(control).toBeInViewport({ ratio: 1 })
    const bounds = (await control.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(workspaceBounds.x)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(workspaceBounds.x + workspaceBounds.width + 1)
  }
  for (const region of [page.getByTestId('knowledge-page-toolbar'), filters]) {
    expect(await region.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
  }
}

test('knowledge actions and status filters fit the split pane and phone', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await fixture(page)
  await page.goto('/knowledge')
  const table = page.getByRole('table', { name: '知识库文档列表', exact: true })
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: '每页文档数', exact: true })).toBeVisible()
  await expect(page.getByTestId('knowledge-page-toolbar')).toHaveCSS('height', '52px')
  await expect(page.locator('[aria-label="文档筛选与排序"]')).toHaveCSS('height', '44px')
  await expect(table.locator('th').first()).toHaveCSS('height', '36px')
  await expect(table.locator('tbody tr').first()).toHaveCSS('height', '44px')
  await expect(table.locator('tbody tr').last()).toHaveCSS('height', '44px')
  await expect(table.locator('..')).toHaveCSS('border-radius', '0px')
  await expect(table.locator('..')).toHaveCSS('border-left-width', '0px')
  const rail = page.getByRole('complementary', { name: '数据集与目录', exact: true })
  await expect(rail).toBeVisible()
  expect((await table.boundingBox())!.x).toBeCloseTo((await rail.boundingBox())!.x + 224, 0)
  const scopeSummary = page.getByText('2 文档 · 3 分块', { exact: true })
  await expect(scopeSummary).toHaveCount(0)
  await expect(page.getByRole('button', { name: '收起侧边栏', exact: true })).toBeVisible()
  const inspector = page.locator('[data-knowledge-inspector-rail]')
  await expect(inspector).toBeVisible()
  await page.getByRole('button', { name: UPLOADED_DOCUMENT_FILENAME, exact: true }).click()
  const resize = page.getByRole('separator', { name: '拖动调整文档查看器宽度' })
  await expect(resize).toBeVisible()
  await expect(rail).toHaveCount(0)
  await expect(inspector).toHaveCount(0)
  const viewerBounds = (await resize.locator('..').boundingBox())!
  const tableBounds = (await table.boundingBox())!
  expect(tableBounds.x + tableBounds.width).toBeLessThanOrEqual(viewerBounds.x + 1)
  const importButtonBounds = (await page.getByRole('button', { name: '导入文档', exact: true }).boundingBox())!
  expect(importButtonBounds.x + importButtonBounds.width).toBeLessThanOrEqual(viewerBounds.x)
  await expectControlsInsideWorkspace(page)
  expect(
    parseFloat(
      await table
        .locator('th')
        .last()
        .evaluate((cell) => getComputedStyle(cell).paddingRight),
    ),
  ).toBeGreaterThanOrEqual(14)
  await page.screenshot({ path: test.info().outputPath('split-pane.png') })
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(rail).toBeVisible()
  await expect(inspector).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(rail).toHaveCount(0)
  await expect(inspector).toHaveCount(0)
  await expectControlsInsideWorkspace(page)
  expect((await table.boundingBox())!.y).toBeLessThanOrEqual(215)
  const searchBounds = (await page.getByRole('searchbox', { name: '搜索文档名称', exact: true }).boundingBox())!
  const placeholderFits = await page.getByRole('searchbox', { name: '搜索文档名称', exact: true }).evaluate((input) => {
    const style = getComputedStyle(input)
    const context = document.createElement('canvas').getContext('2d')!
    context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
    const available =
      input.getBoundingClientRect().width -
      parseFloat(style.borderLeftWidth) -
      parseFloat(style.borderRightWidth) -
      parseFloat(style.paddingLeft) -
      parseFloat(style.paddingRight)
    return context.measureText((input as HTMLInputElement).placeholder).width <= available
  })
  expect(placeholderFits).toBe(true)
  const detailBounds = (await page.getByRole('button', { name: '展开文档详情', exact: true }).boundingBox())!
  expect(detailBounds.y).toBeCloseTo(searchBounds.y, 0)
  const row = table.locator('tbody tr').last()
  const rowCells = row.locator('td')
  const statusBounds = (await rowCells.nth(3).boundingBox())!
  const actionBounds = (await row.getByRole('button', { name: '待审查.md的更多操作', exact: true }).boundingBox())!
  expect(actionBounds.x).toBeGreaterThanOrEqual(statusBounds.x + statusBounds.width)
  expect(
    await table.locator('..').evaluate((element) => element.scrollWidth - element.clientWidth),
  ).toBeLessThanOrEqual(1)
  await page.screenshot({ path: test.info().outputPath('knowledge-phone-search.png'), animations: 'disabled' })
})

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1680, height: 960 },
]) {
  test(`knowledge scope rail selects datasets and folders at ${viewport.width}×${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await fixture(page)
    await page.goto('/knowledge')
    const rail = page.getByRole('complementary', { name: '数据集与目录', exact: true })
    await expect(rail).toHaveCSS('width', '224px')
    const scope = rail.getByRole('button', { name: '产品资料 2', exact: true })
    await expect(scope).toHaveCSS('height', '32px')
    await expect(scope).toHaveAttribute('title', '产品资料')
    await expect(rail.getByRole('link', { name: '+ 新建', exact: true })).toHaveCount(0)
    await expect(rail.getByRole('button', { name: '收起目录', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '目录', exact: true })).toHaveCount(0)
    await expect(page.getByText('2 文档 · 3 分块', { exact: true })).toHaveCount(0)
    await scope.click()
    await expect(scope).toHaveAttribute('data-active', 'true')
    await expect(page).toHaveURL(/dataset=dataset-layout/)
    await expect(rail.getByRole('button', { name: '全部目录 2', exact: true })).toBeVisible()
    const folderRequest = page.waitForRequest(
      (request) => new URL(request.url()).searchParams.get('source_path_prefix') === '手册',
    )
    await rail.getByRole('button', { name: '手册 2', exact: true }).click()
    await folderRequest
    await expect(rail.getByRole('button', { name: '手册 2', exact: true })).toHaveAttribute('aria-current', 'true')
    await rail.getByRole('button', { name: '收起目录', exact: true }).click()
    await expect(rail).toHaveCount(0)
    await page.getByRole('button', { name: '目录', exact: true }).click()
    await expect(rail).toBeVisible()
    await expect(scope).toHaveAttribute('data-active', 'true')
    await rail.getByRole('button', { name: /全部数据集/, exact: false }).click()
    await expect(page).toHaveURL(/\/knowledge$/)
    await page.screenshot({ path: test.info().outputPath('knowledge-scope-rail.png'), animations: 'disabled' })
  })
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1680, height: 960 },
  { width: 390, height: 844 },
]) {
  test(`knowledge inline drop band uploads files and keeps source actions usable at ${viewport.width}×${viewport.height}`, async ({
    page,
  }, testInfo) => {
    const state = { uploaded: false }
    await installCommonApiMocks(page, state)
    await page.route('**/api/v1/datasets**', (route) =>
      route.fulfill({
        json: {
          items: [{ id: 'dataset-empty', name: 'test121', ingestion_summary: { total_documents: 0 } }],
          total: 1,
        },
      }),
    )
    await page.setViewportSize(viewport)
    await page.goto('/knowledge')
    const dropzone = page.getByRole('region', { name: '文件上传区', exact: true })
    const upload = dropzone.getByRole('button', { name: '选择本地文件', exact: true })
    await expect(upload).toBeInViewport({ ratio: 1 })
    await expect(page.locator('#knowledge-import-title')).toHaveText('知识库暂无文档')
    await expect(page.getByRole('table', { name: '知识库文档列表', exact: true })).toHaveCount(0)
    const rail = page.getByRole('complementary', { name: '数据集与目录', exact: true })
    const header = page.getByTestId('knowledge-page-toolbar')
    if (viewport.width >= 1080) {
      await rail.getByRole('button', { name: '收起目录', exact: true }).click()
      await expect(rail).toHaveCount(0)
      await header.getByRole('button', { name: '目录', exact: true }).click()
      await rail.getByRole('button', { name: 'test121 0', exact: true }).click()
    } else {
      await expect(rail).toHaveCount(0)
      await header.getByRole('button', { name: '目录', exact: true }).click()
      const sheet = page.getByRole('dialog', { name: '数据集与目录', exact: true })
      await sheet.getByRole('combobox', { name: '筛选数据集', exact: true }).click()
      await page.getByRole('option', { name: 'test121', exact: true }).click()
      await sheet.getByRole('button', { name: 'Close', exact: true }).click()
    }
    await expect(page).toHaveURL(/dataset=dataset-empty/)
    await expect(header.getByText('test121', { exact: true })).toBeVisible()
    await expect(header).toHaveCSS('height', '52px')
    await expect(page.locator('#knowledge-import-title')).toHaveText('当前数据集暂无文档')
    await expect(page.locator('#knowledge-import-description')).toContainText('test121')
    await expect(page.locator('[data-task-center-dock]')).toHaveCount(0)
    await expect(page.getByRole('searchbox', { name: '搜索文档名称', exact: true })).toHaveCount(0)
    const bandBounds = (await dropzone.boundingBox())!
    expect(bandBounds.height).toBeGreaterThanOrEqual(viewport.width < 768 ? 280 : 360)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)
    await page.screenshot({ path: testInfo.outputPath('knowledge-inline-drop-band.png'), animations: 'disabled' })
    const picker = page.waitForEvent('filechooser')
    await upload.click()
    await (await picker).setFiles([])

    const urlSource = page.getByRole('button', { name: '导入网页', exact: true })
    await urlSource.click()
    const urlDialog = page.getByRole('dialog', { name: '通过 URL 导入文档', exact: true })
    await expect(urlDialog).toBeVisible()
    await expect(urlDialog.getByRole('combobox', { name: '目标数据集', exact: true })).toHaveText('test121')
    await urlDialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(urlSource).toBeFocused()
    await page.getByRole('button', { name: '采集网站', exact: true }).click()
    const crawlDialog = page.getByRole('dialog', { name: 'Website Crawl (Connector)', exact: true })
    await expect(crawlDialog).toBeVisible()
    await expect(crawlDialog.getByRole('combobox').filter({ hasText: 'test121' })).toHaveCount(1)
    await crawlDialog.getByRole('button', { name: 'Cancel', exact: true }).click()

    const dataTransfer = await page.evaluateHandle(() => {
      const transfer = new DataTransfer()
      transfer.items.add(
        new File(['# Dropped knowledge\nA real upload boundary.'], 'drop-knowledge.md', { type: 'text/markdown' }),
      )
      return transfer
    })
    await dropzone.dispatchEvent('dragenter', { dataTransfer })
    await expect(dropzone).toHaveAttribute('data-dragging', 'true')
    await dropzone.dispatchEvent('dragleave', { dataTransfer })
    await expect(dropzone).toHaveAttribute('data-dragging', 'false')
    await dropzone.dispatchEvent('dragenter', { dataTransfer })
    await dropzone.dispatchEvent('dragover', { dataTransfer })
    const request = page.waitForRequest(
      (request) => request.url().includes('/documents/upload-batch') && request.method() === 'POST',
    )
    await dropzone.dispatchEvent('drop', { dataTransfer })
    const form = (await request).postData()
    expect(form).toContain('drop-knowledge.md')
    expect(form).toMatch(/name="dataset_id"\r?\n\r?\ndataset-empty/)
    await dataTransfer.dispose()
    await expect(page.getByRole('button', { name: UPLOADED_DOCUMENT_FILENAME, exact: true })).toBeVisible()
    expect(state.uploaded).toBe(true)
  })
}

test('dropped files keep the selected dataset and expose failed upload receipts', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: false })
  await page.route('**/api/v1/datasets**', (route) =>
    route.fulfill({
      json: {
        items: [{ id: 'dataset-layout', name: '产品资料', permission: 'me' }],
        total: 1,
      },
    }),
  )
  const uploadBodies: string[] = []
  await page.route('**/api/v1/documents/upload-batch', (route) => {
    uploadBodies.push(route.request().postData() || '')
    return route.fulfill({
      json: {
        total: 1,
        successful_count: 0,
        failed_count: 1,
        successful: [],
        failed: [{ filename: 'failed-drop.md', source_path: 'failed-drop.md', error: '文件解析失败，请检查内容' }],
      },
    })
  })
  await page.goto('/knowledge?dataset=dataset-layout')
  await expect(page.locator('#knowledge-import-title')).toHaveText('当前数据集暂无文档')
  await expect(page.getByRole('columnheader', { name: '所属数据集', exact: true })).toHaveCount(0)
  const selectedDataset = page.locator('[data-knowledge-scope-rail] [data-active="true"]')
  await expect(selectedDataset).toContainText('产品资料')
  const dataTransfer = await page.evaluateHandle(() => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['# Retained failed upload'], 'failed-drop.md', { type: 'text/markdown' }))
    return transfer
  })
  await page.getByRole('region', { name: '文件上传区', exact: true }).dispatchEvent('drop', { dataTransfer })
  await dataTransfer.dispose()
  const receipt = page.getByRole('alert').filter({ hasText: '已上传 0 个文件，失败 1 个' })
  await expect(receipt).toBeVisible()
  await receipt.getByText('查看失败文件', { exact: true }).click()
  await expect(receipt).toContainText('failed-drop.md · 文件解析失败，请检查内容')
  expect(uploadBodies.length).toBeGreaterThan(0)
  expect(uploadBodies.every((body) => body.includes('dataset-layout'))).toBe(true)
  await expect(selectedDataset).toContainText('产品资料')
  await page.getByRole('button', { name: '切换到全部数据集', exact: true }).click()
  await expect(page).toHaveURL(/\/knowledge$/)
})

test('knowledge keeps server pagination and page size controls for multiple pages', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await fixture(page)
  await page.route('**/api/v1/documents/stats**', (route) =>
    route.fulfill({ json: { total: 25, total_chunks: 25, total_size: 25600, by_status: { completed: 25 } } }),
  )
  await page.route('**/api/v1/datasets**', (route) =>
    route.fulfill({
      json: {
        items: [{ id: 'dataset-layout', name: '产品资料', ingestion_summary: { total_documents: 25 } }],
        total: 1,
      },
    }),
  )
  await page.route(/\/api\/v1\/documents\/?(?:\?.*)?$/, (route) => {
    const url = new URL(route.request().url())
    const skip = Number(url.searchParams.get('skip') || 0)
    const limit = Number(url.searchParams.get('limit') || 20)
    const items = Array.from({ length: 25 }, (_, index) => ({
      id: `paged-document-${index + 1}`,
      dataset_id: 'dataset-layout',
      filename: `分页文档 ${index + 1}.md`,
      file_type: 'md',
      file_size: 1024,
      status: 'completed',
      chunk_count: 1,
      created_at: '2026-11-24T00:00:00Z',
      updated_at: '2026-11-24T00:00:00Z',
      metadata: {},
    })).slice(skip, skip + limit)
    return route.fulfill({ json: { items, total: 25 } })
  })
  await page.goto('/knowledge')
  await expect(page.locator('[data-document-row]')).toHaveCount(20)
  const fourteenthRow = page.locator('[data-document-row]').nth(13)
  await expect(fourteenthRow).toHaveCSS('height', '44px')
  await expect(fourteenthRow).toBeInViewport({ ratio: 1 })
  await page.screenshot({ path: test.info().outputPath('knowledge-dense-ledger.png'), animations: 'disabled' })
  const nextPage = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return url.pathname.replace(/\/$/, '') === '/api/v1/documents' && url.searchParams.get('skip') === '20'
  })
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await nextPage
  await expect(page.locator('[data-document-row]')).toHaveCount(5)
  await expect(page.getByRole('button', { name: '分页文档 21.md', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '每页文档数', exact: true }).click()
  await page.getByRole('option', { name: '10 条 / 页', exact: true }).click()
  await expect(page.locator('[data-document-row]')).toHaveCount(10)
  await expect(page.getByRole('button', { name: '分页文档 1.md', exact: true })).toBeVisible()
})

for (const width of [1280, 1440, 1680]) {
  test(`knowledge live inspector collapses, persists and selects rows at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await fixture(page)
    await page.goto('/knowledge')
    const rail = page.locator('[data-knowledge-inspector-rail]')
    const table = page.getByRole('table', { name: '知识库文档列表', exact: true })
    const toolbar = page.locator('[aria-label="文档筛选与排序"]')
    await expect(rail).toHaveCSS('width', '336px')
    await expect(page.locator('[data-knowledge-inspector]')).toHaveCount(1)
    await expect(rail.getByRole('heading', { name: UPLOADED_DOCUMENT_FILENAME, exact: true })).toBeVisible()
    const datasetPill = table.locator('tbody tr').first().locator('[data-tone="knowledge"]')
    await expect(datasetPill).toHaveText('产品资料')
    expect(await datasetPill.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(
      'rgba(0, 0, 0, 0)',
    )
    await expect(page.locator('[data-knowledge-scope-rail] button').filter({ hasText: '产品资料' })).toHaveAttribute(
      'data-tone',
      'knowledge',
    )
    const dots = toolbar.locator('[aria-label="处理状态"] span[data-state]')
    await expect(dots).toHaveCount(4)
    expect(
      new Set(
        await dots.evaluateAll((elements) => elements.map((element) => getComputedStyle(element).backgroundColor)),
      ).size,
    ).toBe(4)
    const size = table.getByRole('columnheader', { name: '大小', exact: true })
    const date = table.getByRole('columnheader', { name: '上传时间', exact: true })
    if (width <= 1520) {
      await expect(size).toBeHidden()
      await expect(date).toBeHidden()
    } else {
      await expect(size).toBeVisible()
      await expect(date).toBeVisible()
    }
    for (const region of [table.locator('..'), toolbar]) {
      expect(await region.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
    }
    await table.locator('tbody tr').last().locator('td').nth(3).click()
    await expect(table.locator('tbody tr').last()).toHaveAttribute('data-inspected', 'true')
    await expect(rail.getByRole('heading', { name: '待审查.md', exact: true })).toBeVisible()
    await expect(rail).toContainText('等待内容安全审核')
    await page.screenshot({ path: test.info().outputPath('knowledge-three-zone.png'), animations: 'disabled' })
    await expect(rail.getByRole('button', { name: '收起文档详情', exact: true })).toHaveCount(0)
    await toolbar.getByRole('button', { name: '收起文档详情', exact: true }).click()
    await expect(rail).toHaveCount(0)
    await expect(size).toBeVisible()
    await expect(date).toBeVisible()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('ragvia.knowledge.inspectorOpen'))).toBe('false')
    await page.reload()
    await expect(table).toBeVisible()
    await expect(rail).toHaveCount(0)
    await toolbar.getByRole('button', { name: '展开文档详情', exact: true }).click()
    await expect(rail).toBeVisible()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('ragvia.knowledge.inspectorOpen'))).toBe('true')
  })
}

test('knowledge inspector loads real chunks on demand and performs single-document maintenance', async ({ page }) => {
  await fixture(page)
  let disabled = false
  let archived = false
  let rejectLifecycle = false
  const actions: { action: string; body: unknown }[] = []
  await page.route(/\/api\/v1\/documents\/?(?:\?.*)?$/, (route) =>
    route.fulfill({
      json: {
        total: 1,
        items: [
          {
            id: UPLOADED_DOCUMENT_ID,
            dataset_id: 'dataset-layout',
            filename: UPLOADED_DOCUMENT_FILENAME,
            file_type: 'md',
            file_size: 2048,
            chunk_count: 3,
            status: 'processing',
            processing_progress: 67,
            processing_attempts: 2,
            created_at: '2026-11-24T00:00:00Z',
            updated_at: '2026-11-24T00:00:00Z',
            disabled_at: disabled ? '2026-11-24T00:00:00Z' : null,
            archived_at: archived ? '2026-11-24T00:00:00Z' : null,
            metadata: { parser_backend: 'auto', source_path: '手册/产品.md' },
          },
        ],
      },
    }),
  )
  let chunkRequests = 0
  await page.route(`**/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks?*`, (route) => {
    chunkRequests += 1
    expect(new URL(route.request().url()).searchParams.get('limit')).toBe('8')
    return route.fulfill({
      json: {
        total: 1,
        items: [
          {
            id: 'chunk-preview',
            chunk_index: 0,
            page_number: 2,
            content: '真实分块预览内容',
            metadata: { header_path: ['产品说明'] },
          },
        ],
      },
    })
  })
  await page.route('**/api/v1/documents/batch/*', (route) => {
    const action = new URL(route.request().url()).pathname.split('/').pop()!
    actions.push({ action, body: route.request().postDataJSON() })
    if (action === 'reingest')
      return route.fulfill({ json: { queued: 1, skipped: 0, denied: [], conflicts: [], not_found: [] } })
    if (rejectLifecycle)
      return route.fulfill({ json: { updated: 0, denied: [UPLOADED_DOCUMENT_ID], conflicts: [], not_found: [] } })
    if (action === 'disable' || action === 'enable') disabled = action === 'disable'
    if (action === 'archive' || action === 'unarchive') archived = action === 'archive'
    return route.fulfill({ json: { updated: 1, denied: [], conflicts: [], not_found: [] } })
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/knowledge')
  const rail = page.locator('[data-knowledge-inspector-rail]')
  await expect(rail).toBeVisible()
  expect(chunkRequests).toBe(0)
  const progress = page.getByRole('progressbar', { name: '文档处理进度', exact: true })
  await expect(progress).toHaveAttribute('aria-valuenow', '67')
  await expect(progress).toHaveCSS('width', '40px')
  await expect(progress).toHaveCSS('height', '4px')
  await rail.getByRole('tab', { name: '分块', exact: true }).click()
  await expect(rail).toContainText('真实分块预览内容')
  await expect(rail).toContainText('第 2 页')
  await expect(rail).toContainText('产品说明')
  expect(chunkRequests).toBe(1)
  await rail.getByRole('tab', { name: '概览', exact: true }).click()
  await rail.getByRole('button', { name: '重新入库', exact: true }).click()
  await expect(page.getByText('已提交重新入库', { exact: true })).toBeVisible()
  expect(actions[0]).toEqual({
    action: 'reingest',
    body: { document_ids: [UPLOADED_DOCUMENT_ID], replace: false, force: true, skip_if_unchanged: false },
  })
  await rail.getByRole('tab', { name: '管理', exact: true }).click()
  for (const label of ['禁用', '启用', '归档', '取消归档']) {
    await rail.getByRole('button', { name: label, exact: true }).click()
    await expect(page.getByText(`文档已${label}`, { exact: true })).toBeVisible()
  }
  expect(actions.slice(1)).toEqual(
    ['disable', 'enable', 'archive', 'unarchive'].map((action) => ({
      action,
      body: { document_ids: [UPLOADED_DOCUMENT_ID] },
    })),
  )
  rejectLifecycle = true
  await rail.getByRole('button', { name: '禁用', exact: true }).click()
  await expect(page.getByText('文档未更新，请检查权限或处理状态。', { exact: true })).toBeVisible()
  await expect(rail.getByRole('button', { name: '禁用', exact: true })).toBeEnabled()
  await rail.getByRole('button', { name: '删除文档', exact: true }).click()
  const confirmation = page.getByRole('alertdialog')
  await expect(confirmation).toContainText(UPLOADED_DOCUMENT_FILENAME)
  await confirmation.getByRole('button', { name: '取消', exact: true }).click()
})

test('knowledge phone opens one shared inspector sheet and yields to the reader', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await fixture(page)
  await page.goto('/knowledge')
  await expect(page.locator('[data-knowledge-inspector-rail]')).toHaveCount(0)
  await page.getByRole('button', { name: '展开文档详情', exact: true }).click()
  const sheet = page.getByRole('dialog', { name: '文档详情', exact: true })
  await expect(sheet).toBeInViewport({ ratio: 1 })
  await expect(page.locator('[data-knowledge-inspector]')).toHaveCount(1)
  await expect(sheet.getByRole('heading', { name: UPLOADED_DOCUMENT_FILENAME, exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('knowledge-phone-inspector.png'), animations: 'disabled' })
  await sheet.getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: '待审查.md的更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '查看详情', exact: true }).click()
  await expect(sheet.getByRole('heading', { name: '待审查.md', exact: true })).toBeVisible()
  await sheet.getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: UPLOADED_DOCUMENT_FILENAME, exact: true }).click()
  await expect(sheet).toHaveCount(0)
  await expect(page.getByRole('button', { name: '关闭', exact: true })).toBeVisible()
})
