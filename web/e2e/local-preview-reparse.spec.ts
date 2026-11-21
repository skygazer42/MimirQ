import { expect, test, type Page } from '@playwright/test'

import { installCommonApiMocks, type EnterpriseTelemetryMockState } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

async function readLocalDocuments(page: Page) {
  return page.evaluate(async () => {
    const storageKey = Object.keys(localStorage).find((key) => key.startsWith('mimirq_parsed_files:'))
    if (storageKey === undefined) throw new Error('Document index was not initialized')
    const snapshot = JSON.parse(localStorage.getItem(storageKey)!) as { state: { files: Array<{ id: string }> } }
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('mimirq', 2)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    try {
      const bodies = await new Promise<Array<{ id: string; markdownContent: string; originalMarkdownContent: string }>>(
        (resolve, reject) => {
          const request = database.transaction('doc_contents', 'readonly').objectStore('doc_contents').getAll()
          request.onsuccess = () => resolve(request.result)
          request.onerror = () => reject(request.error)
        },
      )
      return { ids: snapshot.state.files.map((file) => file.id), bodies }
    } finally {
      database.close()
    }
  })
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
]) {
  test(`saves and replaces one local preview at width ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const state: EnterpriseTelemetryMockState = { uploaded: false, parsingDocuments: [] }
    await installCommonApiMocks(page, state)
    let uploads = 0
    let parses = 0
    let deletions = 0
    let remoteEdits = 0
    let releaseFailure!: () => void
    const pendingFailure = new Promise<void>((resolve) => {
      releaseFailure = resolve
    })
    await page.route(
      (url) => url.pathname === '/api/v1/parsing/documents',
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.fallback()
          return
        }
        uploads += 1
        const document = {
          id: `server-${uploads}`,
          filename: 'local-preview.md',
          file_type: 'md',
          file_size: 11,
          status: 'pending',
          error_message: null,
          created_at: '2026-11-13T00:00:00Z',
          updated_at: '2026-11-13T00:00:00Z',
        }
        state.parsingDocuments = [document]
        await route.fulfill({ json: document })
      },
    )
    await page.route(
      (url) => /^\/api\/v1\/parsing\/documents\/server-\d+\/parse$/.test(url.pathname),
      async (route) => {
        parses += 1
        if (parses === 1) {
          await pendingFailure
          await route.fulfill({ status: 503, json: { detail: 'Parser unavailable' } })
          return
        }
        state.parsingDocuments = [
          {
            id: 'server-2',
            filename: 'local-preview.md',
            file_type: 'md',
            file_size: 11,
            status: 'completed',
            error_message: null,
            created_at: '2026-11-13T00:00:00Z',
            updated_at: '2026-11-13T00:00:00Z',
            markdown_content: '# Full parsed result',
            original_markdown_content: '# Original parsed text',
            parser_backend: 'text',
          },
        ]
        await route.fulfill({
          json: {
            document_id: 'server-2',
            parser_backend: 'text',
            markdown_content: '# Full parsed result',
            original_markdown_content: '# Original parsed text',
            edited: false,
            parse_duration_sec: 0,
          },
        })
      },
    )
    await page.route(
      (url) => /^\/api\/v1\/parsing\/documents\/server-\d+$/.test(url.pathname),
      async (route) => {
        if (route.request().method() !== 'DELETE') {
          await route.fallback()
          return
        }
        deletions += 1
        state.parsingDocuments = []
        await route.fulfill({ status: 204, body: '' })
      },
    )
    await page.route('**/api/v1/parsing/documents/*/content', async (route) => {
      if (route.request().method() === 'PATCH') remoteEdits += 1
      await route.fulfill({ status: 404, json: { detail: 'Local IDs have no server content' } })
    })
    await page.goto('/parsing')
    await expect(page.getByRole('heading', { name: '文档解析', exact: true })).toBeVisible()
    await page.evaluate(async () => {
      const storageKey = Object.keys(localStorage).find((key) => key.startsWith('mimirq_parsed_files:'))
      if (storageKey === undefined) throw new Error('Document index was not initialized')
      const id = `${storageKey.slice('mimirq_parsed_files:'.length)}:local-preview`
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          version: 0,
          state: {
            folders: [],
            activeFolderId: 'root',
            files: [
              {
                id: 'local-preview',
                filename: 'local-preview.md',
                fileType: 'md',
                fileSize: 11,
                markdownContent: '',
                originalMarkdownContent: '',
                parsedAt: '2026-11-13T00:00:00Z',
                parser: 'Text',
                parserBackend: 'text',
                folderId: 'root',
                status: 'parsed',
              },
            ],
          },
        }),
      )
      const database = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('mimirq', 2)
        request.onupgradeneeded = () => {
          request.result.createObjectStore('doc_contents', { keyPath: 'id' })
          request.result.createObjectStore('doc_sources', { keyPath: 'id' })
        }
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
      })
      try {
        await new Promise<void>((resolve, reject) => {
          const transaction = database.transaction(['doc_contents', 'doc_sources'], 'readwrite')
          transaction.objectStore('doc_contents').put({
            id,
            markdownContent: '# Local preview',
            originalMarkdownContent: '# Local original',
            updatedAt: Date.now(),
          })
          transaction.objectStore('doc_sources').put({
            id,
            filename: 'local-preview.md',
            mimeType: 'text/markdown',
            size: 11,
            lastModified: 0,
            updatedAt: Date.now(),
            blob: new Blob(['Source text'], { type: 'text/markdown' }),
          })
          transaction.oncomplete = () => resolve()
          transaction.onerror = () => reject(transaction.error)
          transaction.onabort = () => reject(transaction.error)
        })
      } finally {
        database.close()
      }
    })
    await page.reload()
    await page.getByLabel('选择文档', { exact: true }).click()
    const directory = page.getByRole('dialog', { name: '文件目录', exact: true })
    await directory.getByText('local-preview.md', { exact: true }).click()
    const result = page.getByRole('region', { name: '解析结果', exact: true })
    await expect(result).toContainText('Local preview')
    if (viewport.width < 768) await page.getByRole('button', { name: '原文', exact: true }).click()
    await page
      .getByRole('region', { name: '原文', exact: true })
      .getByRole('button', { name: '恢复源文件', exact: true })
      .click()
    await result.getByRole('button', { name: '更多结果操作', exact: true }).click()
    await page.getByRole('menuitem', { name: '编辑 Markdown', exact: true }).click()
    await page.getByLabel('编辑 Markdown', { exact: true }).fill('# Local saved draft')
    await page.getByRole('button', { name: '保存修改', exact: true }).click()
    await expect(page.getByText('已保存到本地', { exact: true })).toBeVisible()
    await expect
      .poll(async () => (await readLocalDocuments(page)).bodies.map((record) => record.markdownContent))
      .toEqual(['# Local saved draft'])
    await page.getByRole('button', { name: '重新解析', exact: true }).click()
    try {
      await expect.poll(() => parses).toBe(1)
      expect((await readLocalDocuments(page)).ids).toEqual(['local-preview'])
    } finally {
      releaseFailure()
    }
    await expect(page.getByLabel('重试解析', { exact: true })).toBeVisible()
    await expect.poll(() => deletions).toBe(1)
    await expect(result).toContainText('Local saved draft')
    expect((await readLocalDocuments(page)).ids).toEqual(['local-preview'])
    expect((await readLocalDocuments(page)).bodies.map((record) => record.markdownContent)).toEqual([
      '# Local saved draft',
    ])
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/parsing-actions/local-reparse-failure-${viewport.width}.png`,
    })
    await page.getByLabel('重试解析', { exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(result).toContainText('Full parsed result')
    await expect.poll(async () => (await readLocalDocuments(page)).ids).toEqual(['server-2'])
    await expect
      .poll(async () =>
        (await readLocalDocuments(page)).bodies.map((record) => [
          record.markdownContent,
          record.originalMarkdownContent,
        ]),
      )
      .toEqual([['# Full parsed result', '# Original parsed text']])
    await page.reload()
    await page.getByLabel('选择文档', { exact: true }).click()
    await expect(directory.getByText('local-preview.md', { exact: true })).toHaveCount(1)
    await directory.getByText('local-preview.md', { exact: true }).click()
    await expect(result).toContainText('Full parsed result')
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/parsing-actions/local-reparse-success-${viewport.width}.png`,
    })
    expect(uploads).toBe(2)
    expect(parses).toBe(2)
    expect(remoteEdits).toBe(0)
    expect(pageErrors).toEqual([])
  })
}
