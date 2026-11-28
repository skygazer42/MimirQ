import { expect, test } from '@playwright/test'

import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'
import { readParsingLibrary, seedTextParsingLibrary } from './parsing-library.helpers'
import type { ParsedFileData } from '../store/use-parsed-files-store'

test.use({ serviceWorkers: 'block' })

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
]) {
  test(`reassociates a preview without changing the saved server source at width ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    const document = {
      id: 'remote-source',
      filename: 'server-source.md',
      file_type: 'md',
      file_size: 77,
      status: 'completed',
      error_message: null,
      created_at: '2026-11-14T00:00:00Z',
      updated_at: '2026-11-14T00:00:00Z',
      markdown_content: '# Saved server result',
      original_markdown_content: '# Saved server original',
      parser_backend: 'text',
    }
    await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [document] })
    const file: ParsedFileData = {
      id: document.id,
      filename: document.filename,
      fileType: document.file_type,
      fileSize: document.file_size,
      status: 'parsed',
      source: 'parsing_workspace',
      markdownContent: document.markdown_content,
      originalMarkdownContent: document.original_markdown_content,
      parsedAt: document.updated_at,
      parser: 'Text',
      parserBackend: 'text',
      folderId: 'root',
    }
    let uploads = 0
    let parses = 0
    await page.route(
      (url) => url.pathname === '/api/v1/parsing/documents',
      async (route) => {
        if (route.request().method() === 'POST') uploads += 1
        await route.fallback()
      },
    )
    await page.route(
      (url) => url.pathname === `/api/v1/parsing/documents/${document.id}/parse`,
      async (route) => {
        parses += 1
        await route.fulfill({
          json: {
            document_id: document.id,
            parser_backend: 'text',
            markdown_content: '# Reparsed saved server source',
            original_markdown_content: '# Saved server original',
            edited: false,
            parse_duration_sec: 0,
          },
        })
      },
    )
    const storageKey = await seedTextParsingLibrary(page, [file])
    await page.getByLabel('选择文档', { exact: true }).click()
    await page
      .getByRole('dialog', { name: '文件目录', exact: true })
      .getByText(document.filename, { exact: true })
      .click()
    if (viewport.width < 768) await page.getByRole('button', { name: '原文', exact: true }).click()
    const source = page.getByRole('region', { name: '原文', exact: true })
    await source.getByRole('button', { name: '关联本地原文件', exact: true }).click()
    await page.getByLabel('重新关联原文件', { exact: true }).setInputFiles({
      name: 'local-preview.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# Locally selected preview'),
    })
    await expect(page.getByRole('button', { name: '复制 Markdown', exact: true })).toBeVisible()
    if (viewport.width < 768) await page.getByRole('button', { name: '原文', exact: true }).click()
    await expect(source).toContainText('Locally selected preview')
    const result = page.getByRole('region', { name: '解析结果', exact: true })
    if (viewport.width < 768) await page.getByRole('button', { name: '解析结果', exact: true }).click()
    await expect(result).toContainText('Saved server result')
    await expect(page.getByLabel('选择文档', { exact: true })).toContainText('77 B')
    const before = await readParsingLibrary(page, storageKey)
    expect(before.files[0]).toMatchObject({ filename: 'server-source.md', fileSize: 77, source: 'parsing_workspace' })
    await page.getByRole('button', { name: '重新解析', exact: true }).click()
    await expect(result).toContainText('Reparsed saved server source')
    expect(parses).toBe(1)
    expect(uploads).toBe(0)
    expect((await readParsingLibrary(page, storageKey)).files).toHaveLength(1)
    expect(errors).toEqual([])
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/parsing-restoration/reassociated-${viewport.width}.png`,
    })
  })
}

test('restores saved failed workspace tasks with originals and all source files after reload', async ({ page }) => {
  const files: ParsedFileData[] = ['first', 'second'].map((name) => ({
    id: `local-${name}`,
    filename: `${name}.md`,
    fileType: 'md',
    fileSize: 20,
    status: 'error',
    source: 'parsing_workspace',
    markdownContent: `# Saved ${name} draft`,
    originalMarkdownContent: `# Saved ${name} original`,
    parsedAt: '2026-11-14T00:00:00Z',
    parser: 'Text',
    parserBackend: 'text',
    folderId: 'root',
    error: `Failed ${name} parse`,
  }))
  await installCommonApiMocks(page, {
    uploaded: false,
    parsingDocuments: files.map((file) => ({
      id: file.id,
      filename: file.filename,
      file_type: file.fileType,
      file_size: file.fileSize,
      status: 'failed',
      error_message: file.error ?? null,
      created_at: file.parsedAt,
      updated_at: file.parsedAt,
    })),
  })
  const storageKey = await seedTextParsingLibrary(page, files)
  await page.getByLabel('选择文档', { exact: true }).click()
  const directory = page.getByRole('dialog', { name: '文件目录', exact: true })
  await expect(directory.getByRole('treeitem').filter({ hasText: 'first.md' })).toHaveCount(1)
  await expect(directory.getByRole('treeitem').filter({ hasText: 'second.md' })).toHaveCount(1)
  await directory.getByText('second.md', { exact: true }).click()
  const result = page.getByRole('region', { name: '解析结果', exact: true })
  await expect(result).toContainText('Failed second parse')
  await expect(result).toContainText('Saved second draft')
  await expect(page.getByRole('region', { name: '原文', exact: true })).toContainText('Saved second original')
  await page.reload()
  await page.getByLabel('选择文档', { exact: true }).click()
  await directory.getByText('first.md', { exact: true }).click()
  await expect(result).toContainText('Saved first draft')
  await expect(result).toContainText('Failed first parse')
  await expect(page.getByRole('region', { name: '原文', exact: true })).toContainText('Saved first original')
  expect((await readParsingLibrary(page, storageKey)).files).toHaveLength(2)
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/parsing-restoration/restored-failed-task.png',
  })
})
