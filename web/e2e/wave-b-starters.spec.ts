import { expect, test, type Page } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'
import { fixture as chunkFixture, noOverflow, open as openChunkPreview } from './chunk-compare.helpers'

async function emptyLibrary(page: Page) {
  await installCommonApiMocks(page, { uploaded: false })
  await page.route('**/api/v1/datasets**', (route) =>
    route.fulfill({ json: { items: [{ id: 'starter-dataset', name: '产品资料', permission: 'me' }], total: 1 } }),
  )
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`ingestion opens a two-column import dialog and stages selected or dropped files at ${viewport.width}`, async ({
    page,
  }) => {
    await emptyLibrary(page)
    await page.setViewportSize(viewport)
    await page.goto('/knowledge/ingestion?datasetId=starter-dataset')
    await expect(page.locator('[data-ingestion-document-empty]')).toContainText('开始导入你的第一份文档')
    await expect(page.getByRole('navigation', { name: '文件来源' })).toHaveCount(0)
    await page.locator('[data-ingestion-import-trigger]').click()
    const dialog = page.getByRole('dialog', { name: '导入文档', exact: true })
    const dropzone = dialog.locator('[data-ingestion-empty-file-drop]')
    await expect(dropzone).toContainText('拖入或选择文件，添加到本次导入')
    await expect(dialog.getByText('尚未添加文件', { exact: true })).toBeVisible()
    await expect(dropzone).toBeInViewport({ ratio: 1 })
    await noOverflow(page)
    await page.screenshot({ path: test.info().outputPath('ingestion-import-dialog.png'), animations: 'disabled' })
    const chooser = page.waitForEvent('filechooser')
    await dropzone.click()
    await (
      await chooser
    ).setFiles({ name: 'selected.md', mimeType: 'text/markdown', buffer: Buffer.from('# Selected') })
    await expect(dialog.getByRole('table', { name: '本次待入库文件' })).toContainText('selected.md')
    await dialog.getByRole('button', { name: '清空', exact: true }).click()
    await expect(dialog.getByRole('table', { name: '本次待入库文件' })).toHaveCount(0)
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    const transfer = await page.evaluateHandle(() => {
      const data = new DataTransfer()
      data.items.add(new File(['# Dropped'], 'dropped.md', { type: 'text/markdown' }))
      return data
    })
    await page.locator('[data-ingestion-operation-root]').dispatchEvent('dragover', { dataTransfer: transfer })
    await expect(dialog).toBeVisible()
    await dialog.dispatchEvent('drop', { dataTransfer: transfer })
    await expect(dialog.getByRole('table', { name: '本次待入库文件' })).toContainText('dropped.md')
    await expect(dialog.locator('[data-ingestion-submit]')).toBeEnabled()
    await expect(dialog.locator('[data-ingestion-submit]')).toBeInViewport({ ratio: 1 })
    await expect(dialog.getByRole('radio', { name: /仅传原件/ })).toBeChecked()
    await noOverflow(page)
  })

  test(`parsing starter retains scoped navigation and accepts real file drops at ${viewport.width}`, async ({
    page,
  }) => {
    await emptyLibrary(page)
    await page.setViewportSize(viewport)
    await page.goto('/parsing')
    const starter = page.getByRole('heading', { name: '上传待解析的文档', exact: true })
    await expect(starter).toBeVisible()
    await expect(page.getByLabel('选择文档', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '选择文件', exact: true })).toBeInViewport({ ratio: 1 })
    await noOverflow(page)
    await page.screenshot({ path: test.info().outputPath('parsing-starter.png'), animations: 'disabled' })
    const chooser = page.waitForEvent('filechooser')
    await page.getByRole('button', { name: '上传文件夹', exact: true }).click()
    const folderChooser = await chooser
    expect(await folderChooser.element().getAttribute('webkitdirectory')).toBe('')
    await page.getByRole('combobox', { name: '数据范围', exact: true }).click()
    await page.getByRole('option', { name: '产品资料 · 0', exact: true }).click()
    await expect(page.getByLabel('选择文档', { exact: true })).toBeVisible()
    const transfer = await page.evaluateHandle(() => {
      const data = new DataTransfer()
      data.items.add(new File(['# Dropped parsing document'], 'parsing-drop.md', { type: 'text/markdown' }))
      return data
    })
    const upload = page.waitForRequest(
      (request) => request.url().endsWith('/parsing/documents') && request.method() === 'POST',
    )
    await starter.locator('..').dispatchEvent('drop', { dataTransfer: transfer })
    expect((await upload).postData()).toContain('parsing-drop.md')
    await transfer.dispose()
    await expect(starter).toHaveCount(0)
    await expect(page.getByLabel('选择文档', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '开始解析', exact: true })).toBeVisible()
  })

  test(`chunk starter keeps sample and guide actions connected at ${viewport.width}`, async ({ page }) => {
    await chunkFixture(page, { empty: true })
    await page.setViewportSize(viewport)
    await openChunkPreview(page, true)
    await expect(page.getByRole('heading', { name: '预览文档切片', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '选择已有文档', exact: true })).toBeInViewport({ ratio: 1 })
    await noOverflow(page)
    await page.screenshot({ path: test.info().outputPath('chunk-starter.png'), animations: 'disabled' })
    await page.getByRole('button', { name: '切块指南', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '打开示例文档', exact: true }).click()
    await expect(page.locator('[data-compare-original]')).toBeAttached()
    await expect(page.locator('[data-chunk-card]').first()).toBeVisible()
  })

  test(`governance starter keeps dataset selection and configuration reachable at ${viewport.width}`, async ({
    page,
  }) => {
    await emptyLibrary(page)
    await page.setViewportSize(viewport)
    await page.goto('/data-governance')
    const reader = page.getByRole('main', { name: '文档治理工作区', exact: true })
    await expect(reader.getByRole('heading', { name: '选择需要治理的文档', exact: true })).toBeVisible()
    await expect(page.getByRole('complementary', { name: '文档队列', exact: true })).toBeVisible()
    await expect(reader.getByRole('button', { name: '添加文档', exact: true })).toBeInViewport({ ratio: 1 })
    await noOverflow(page)
    await page.screenshot({ path: test.info().outputPath('governance-starter.png'), animations: 'disabled' })
    await reader.getByRole('button', { name: '治理配置', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '治理配置', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    const chooser = page.waitForEvent('filechooser')
    await reader.getByRole('button', { name: '添加文档', exact: true }).click()
    expect((await chooser).isMultiple()).toBe(true)
  })
}
