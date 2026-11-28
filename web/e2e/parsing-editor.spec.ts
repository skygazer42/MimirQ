import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'

import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'
import { readParsingLibrary, seedTextParsingLibrary } from './parsing-library.helpers'
import type { ParsedFileData } from '../store/use-parsed-files-store'

test.use({ serviceWorkers: 'block' })

test('keeps a pending handoff when moving its document to another folder', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  const file = localFile('moving-editor')
  const storageKey = await seedTextParsingLibrary(
    page,
    [file],
    [{ id: 'target-folder', name: 'Target folder', parentId: 'root', createdAt: '2026-11-13T00:00:00Z' }],
  )
  await page.getByLabel('选择文档', { exact: true }).click()
  const directory = page.getByRole('dialog', { name: '文件目录', exact: true })
  await directory.getByText(file.filename, { exact: true }).click()
  await page
    .getByRole('region', { name: '原文', exact: true })
    .getByRole('button', { name: '恢复源文件', exact: true })
    .click()
  const gate = await page.evaluateHandle(() => {
    const open = IDBFactory.prototype.open
    const descriptor = Object.getOwnPropertyDescriptor(IDBRequest.prototype, 'onsuccess')
    if (descriptor?.set === undefined) throw new Error('Expected the native IndexedDB success callback setter')
    const setSuccess = descriptor.set
    let armed = true
    let released = false
    let resume: (() => void) | undefined
    IDBFactory.prototype.open = function (this: IDBFactory, name: string, version?: number) {
      const request = version === undefined ? open.call(this, name) : open.call(this, name, version)
      if (!armed || name !== 'mimirq') return request
      armed = false
      Object.defineProperty(request, 'onsuccess', {
        configurable: true,
        set(handler: IDBOpenDBRequest['onsuccess']) {
          setSuccess.call(
            request,
            handler === null
              ? null
              : (event: Event) => {
                  if (released) handler.call(request, event)
                  else resume = () => handler.call(request, event)
                },
          )
        },
      })
      return request
    }
    const release = () => {
      released = true
      const callback = resume
      resume = undefined
      callback?.()
    }
    return {
      blocked: () => resume !== undefined,
      release,
      restore: () => {
        IDBFactory.prototype.open = open
        release()
      },
    }
  })
  try {
    await page.getByRole('button', { name: '继续数据治理', exact: true }).click()
    await expect.poll(() => gate.evaluate((control) => control.blocked())).toBe(true)
    await page.getByLabel('选择文档', { exact: true }).click()
    const row = directory.getByRole('treeitem').filter({ hasText: file.filename })
    const target = directory.getByRole('treeitem').filter({ hasText: 'Target folder' })
    await row.dragTo(target)
    await expect.poll(async () => (await readParsingLibrary(page, storageKey)).files[0].folderId).toBe('target-folder')
    await gate.evaluate((control) => control.release())
    await expect
      .poll(async () => (await readParsingLibrary(page, storageKey)).files[0].governanceStatus)
      .toBe('submitted')
    expect((await readParsingLibrary(page, storageKey)).bodies[0]).toMatchObject({
      markdownContent: file.markdownContent,
      originalMarkdownContent: file.originalMarkdownContent,
    })
    await expect(page.getByText(/文档移交未完成/)).toHaveCount(0)
    await page.screenshot({
      path: '../.frontend-structure/20261112-full-frontend-guidelines/parsing-editor/moved-handoff.png',
    })
  } finally {
    await gate.evaluate((control) => control.restore())
    await gate.dispose()
  }
})

function localFile(id: string, folderId = 'root'): ParsedFileData {
  const originalMarkdownContent = `# Original ${id}`
  return {
    id,
    filename: `${id}.md`,
    fileType: 'md',
    fileSize: Buffer.byteLength(originalMarkdownContent, 'utf8'),
    markdownContent: `# Processed ${id}`,
    originalMarkdownContent,
    parsedAt: '2026-11-13T00:00:00Z',
    parser: 'Text',
    parserBackend: 'text',
    folderId,
    status: 'parsed',
    governanceStatus: 'ready',
  }
}

for (const viewport of [
  { width: 1440, height: 900, theme: 'light' },
  { width: 390, height: 844, theme: 'light' },
  { width: 1120, height: 850, theme: 'dark' },
] as const) {
  test(`copies, downloads and hands off the edited document at width ${viewport.width}`, async ({ page, context }) => {
    await page.setViewportSize(viewport)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
    await page.addInitScript((theme) => localStorage.setItem('theme', theme), viewport.theme)
    const file = localFile('editor-local')
    const body = `## 文件导入

在数据集中上传文件，确认原文与解析结果后，再继续数据治理。原始文件会保留，方便核对内容。

### 支持的文档

| 文件类型 | 处理方式 |
| --- | --- |
| PDF | 识别正文、标题与表格 |
| Markdown | 保留段落与标题结构 |
| 电子表格 | 按工作表提取数据 |

## 核对与保存

1. 检查标题层级和段落顺序。
2. 对照原文确认表格内容。
3. 保存修改后，继续数据治理。

编辑正文不会覆盖原始文件。`
    file.filename = '数据接入操作手册.md'
    file.markdownContent = `# 数据接入操作手册\n\n${body}`
    file.originalMarkdownContent = `# Original editor-local\n\n${body}`
    file.fileSize = Buffer.byteLength(file.originalMarkdownContent, 'utf8')
    const storageKey = await seedTextParsingLibrary(page, [file])
    await expect(page.getByTestId('parsing-workbench-title')).toBeVisible()
    await expect(page.getByLabel('选择文档', { exact: true })).toBeVisible()
    if (viewport.theme === 'dark') await expect(page.locator('html')).toHaveClass(/dark/)
    await page.screenshot({ path: test.info().outputPath('parsing-empty.png'), animations: 'disabled' })
    await page.getByRole('button', { name: '解析设置', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.screenshot({ path: test.info().outputPath('parsing-settings.png'), animations: 'disabled' })
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(page.url()).origin })
    await page.getByLabel('选择文档', { exact: true }).click()
    const directory = page.getByRole('dialog', { name: '文件目录', exact: true })
    const row = directory.getByRole('treeitem').filter({ hasText: file.filename })
    await row.getByRole('button', { name: '选择待提交文档', exact: true }).click()
    await row.getByText(file.filename, { exact: true }).click()
    const result = page.getByRole('region', { name: '解析结果', exact: true })
    await expect(result.getByRole('heading', { name: /^数据接入操作手册/ })).toBeVisible()
    const sourceTab = page.getByRole('button', { name: '原文', exact: true })
    if (await sourceTab.isVisible()) await sourceTab.click()
    await page
      .getByRole('region', { name: '原文', exact: true })
      .getByRole('button', { name: '恢复源文件', exact: true })
      .click()
    await expect(result.getByRole('button', { name: '复制 Markdown', exact: true })).toBeVisible()
    await page.getByLabel('选择文档', { exact: true }).click()
    await expect(directory.getByRole('button', { name: '取消选择待提交文档', exact: true })).toHaveCount(1)
    await expect(directory.getByText('1 / 1 个待治理文件已选', { exact: true })).toBeVisible()
    await page.screenshot({ path: test.info().outputPath('parsing-directory.png'), animations: 'disabled' })
    await page.keyboard.press('Escape')
    await expect(directory).toBeHidden()
    if (viewport.width < 640) {
      const copyBox = await result.getByRole('button', { name: '复制 Markdown', exact: true }).boundingBox()
      expect(copyBox!.width).toBeGreaterThanOrEqual(44)
      expect(copyBox!.height).toBeGreaterThanOrEqual(44)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      const headerBox = await page.getByTestId('parsing-workbench-title').boundingBox()
      expect(headerBox!.height).toBeLessThan(90)
    }
    await page.screenshot({ path: test.info().outputPath('parsing-document.png'), animations: 'disabled' })
    if (viewport.width < 640) {
      await sourceTab.click()
      await expect(result.getByRole('button', { name: '复制 Markdown', exact: true })).toHaveCount(0)
      await page.getByRole('button', { name: '解析结果', exact: true }).click()
      await result.getByRole('button', { name: '更多结果操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '查看 Markdown 源码', exact: true }).click()
      await expect(result.locator('pre')).toContainText('# 数据接入操作手册')
      await result.getByRole('button', { name: '更多结果操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '预览 Markdown', exact: true }).click()
    }
    await result.getByRole('button', { name: '复制 Markdown', exact: true }).click()
    await expect(result.getByRole('button', { name: '已复制 Markdown', exact: true })).toBeVisible()
    expect((await page.evaluate(() => navigator.clipboard.readText())).replaceAll('\r\n', '\n')).toBe(
      file.markdownContent,
    )
    if (viewport.width < 640) await result.getByRole('button', { name: '更多结果操作', exact: true }).click()
    const downloadEvent = page.waitForEvent('download')
    await (
      viewport.width < 640
        ? page.getByRole('menuitem', { name: '下载 Markdown', exact: true })
        : result.getByRole('button', { name: '下载 Markdown', exact: true })
    ).click()
    const download = await downloadEvent
    expect(download.suggestedFilename()).toBe(file.filename)
    const downloadPath = await download.path()
    if (downloadPath === null) throw new Error('Expected a completed local download')
    expect(await readFile(downloadPath, 'utf8')).toBe(file.markdownContent)
    await page.getByRole('button', { name: '编辑 Markdown', exact: true }).click()
    await page.getByLabel('编辑 Markdown', { exact: true }).fill('# Edited processed document')
    if (await sourceTab.isVisible()) {
      await sourceTab.click()
      await expect(page.getByLabel('编辑 Markdown', { exact: true })).toBeHidden()
      await page.getByRole('button', { name: '解析结果', exact: true }).click()
      await expect(page.getByLabel('编辑 Markdown', { exact: true })).toHaveValue('# Edited processed document')
    }
    await page.screenshot({ path: test.info().outputPath('parsing-editor.png'), animations: 'disabled' })
    await page.getByRole('button', { name: '保存修改', exact: true }).click()
    await expect(result).toContainText('Edited processed document')
    await expect
      .poll(async () =>
        (await readParsingLibrary(page, storageKey)).bodies.map((record) => [
          record.markdownContent,
          record.originalMarkdownContent,
        ]),
      )
      .toEqual([['# Edited processed document', file.originalMarkdownContent]])
    await page.getByRole('button', { name: '继续数据治理', exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect
      .poll(async () => (await readParsingLibrary(page, storageKey)).files[0].governanceStatus)
      .toBe('submitted')
    await expect(page).toHaveURL(/\/data-governance$/)
    await page.getByRole('button', { name: '选择文档', exact: true }).click()
    await page.locator(`[data-governance-file="${file.id}"]`).click()
    await expect(page.locator('[data-governance-document]')).toContainText('Edited processed document')
    await page.getByRole('button', { name: '原文', exact: true }).click()
    await expect(page.locator('[data-governance-document]')).toContainText('Original editor-local')
    await page.reload()
    await page.getByRole('button', { name: '选择文档', exact: true }).click()
    await page.locator(`[data-governance-file="${file.id}"]`).click()
    await expect(page.locator('[data-governance-document]')).toContainText('Edited processed document')
    await page.getByRole('button', { name: '原文', exact: true }).click()
    await expect(page.locator('[data-governance-document]')).toContainText('Original editor-local')
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/parsing-editor/handoff-${viewport.width}.png`,
    })
    expect(pageErrors).toEqual([])
  })
}

test('retains cross-folder selections, clears a changed dataset scope and retries only failed handoffs', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/datasets' || url.pathname === '/api/v1/datasets/',
    (route) => route.fulfill({ json: { items: [{ id: 'dataset-a', name: 'Dataset A' }], total: 1 } }),
  )
  const first = localFile('editor-a')
  const second = localFile('editor-b', 'other-folder')
  const storageKey = await seedTextParsingLibrary(
    page,
    [first, second],
    [{ id: 'other-folder', name: 'Other folder', parentId: 'root', createdAt: '2026-11-13T00:00:00Z' }],
  )
  const directory = page.getByRole('dialog', { name: '文件目录', exact: true })
  const firstRow = directory.getByRole('treeitem').filter({ hasText: first.filename })
  const secondRow = directory.getByRole('treeitem').filter({ hasText: second.filename })
  const folderRow = directory.getByRole('treeitem').filter({ hasText: 'Other folder' })
  await page.getByLabel('选择文档', { exact: true }).click()
  await expect(directory.getByText('2 个文件 · 2 已解析', { exact: true })).toBeVisible()
  await folderRow.getByRole('button', { name: 'Expand', exact: true }).click()
  await firstRow.getByRole('button', { name: '选择待提交文档', exact: true }).click()
  await secondRow.getByRole('button', { name: '选择待提交文档', exact: true }).click()
  await expect(directory.getByText(/2 \/ 2 个待治理文件已选/)).toContainText('其中 1 个在其他文件夹')
  await page.keyboard.press('Escape')
  await page.getByLabel('数据范围', { exact: true }).click()
  await page.getByRole('option', { name: 'Dataset A · 0', exact: true }).click()
  await page.getByLabel('数据范围', { exact: true }).click()
  await page.getByRole('option', { name: '全部来源', exact: true }).click()
  await page.getByLabel('选择文档', { exact: true }).click()
  await expect(directory.getByText('0 / 2 个待治理文件已选', { exact: true })).toBeVisible()
  await folderRow.getByRole('button', { name: 'Expand', exact: true }).click()
  await firstRow.getByRole('button', { name: '选择待提交文档', exact: true }).click()
  await secondRow.getByRole('button', { name: '选择待提交文档', exact: true }).click()
  const restore = await page.evaluateHandle((id) => {
    const setItem = Storage.prototype.setItem
    Storage.prototype.setItem = function (this: Storage, key: string, value: string) {
      if (key.startsWith('mimirq_parsed_files:')) {
        const snapshot = JSON.parse(value) as { state: { files: Array<{ id: string; governanceStatus?: string }> } }
        if (snapshot.state.files.some((file) => file.id === id && file.governanceStatus === 'submitted'))
          throw new DOMException('文档索引写入被拒绝', 'QuotaExceededError')
      }
      setItem.call(this, key, value)
    }
    return () => {
      Storage.prototype.setItem = setItem
    }
  }, second.id)
  try {
    await directory.getByRole('button', { name: '提交所选文件', exact: true }).click()
    await expect(page.getByText(/已移交 1 个，1 个失败/)).toContainText(second.filename)
    await expect(secondRow.getByRole('button', { name: '取消选择待提交文档', exact: true })).toBeVisible()
    await expect(directory.getByText(/1 \/ 1 个待治理文件已选/)).toBeVisible()
    const saved = await readParsingLibrary(page, storageKey)
    expect(saved.files.find((file) => file.id === first.id)?.governanceStatus).toBe('submitted')
    expect(saved.files.find((file) => file.id === second.id)?.governanceStatus).toBe('ready')
    await page.screenshot({
      path: '../.frontend-structure/20261112-full-frontend-guidelines/parsing-editor/partial-handoff.png',
    })
  } finally {
    await restore.evaluate((release) => release())
    await restore.dispose()
  }
  await directory.getByRole('button', { name: '提交所选文件', exact: true }).focus()
  await page.keyboard.press('Enter')
  await page.waitForURL(/\/data-governance$/)
  const saved = await readParsingLibrary(page, storageKey)
  expect(saved.files.every((file) => file.governanceStatus === 'submitted')).toBe(true)
  expect(saved.bodies.map((record) => record.originalMarkdownContent).sort()).toEqual(
    [first.originalMarkdownContent, second.originalMarkdownContent].sort(),
  )
  expect(pageErrors).toEqual([])
})
