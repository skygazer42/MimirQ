import type { Page } from '@playwright/test'

import type { DocContentCacheRecord } from '../lib/doc-content-cache'
import type { FolderNode, ParsedFileData } from '../store/use-parsed-files-store'

export async function seedTextParsingLibrary(page: Page, files: ParsedFileData[], folders: FolderNode[] = []) {
  await page.goto('/parsing')
  await page.waitForFunction(() => Object.keys(localStorage).some((key) => key.startsWith('mimirq_parsed_files:')))
  const storageKey = await page.evaluate(() => {
    const key = Object.keys(localStorage).find((entry) => entry.startsWith('mimirq_parsed_files:'))
    if (key === undefined) throw new Error('Expected the initialized document index')
    return key
  })
  await page.route('**/__parsing-library-fixture', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Parsing fixture</title>' }),
  )
  await page.goto('/__parsing-library-fixture')
  await page.evaluate(
    async ({ storageKey, files, folders }) => {
      const scope = storageKey.slice('mimirq_parsed_files:'.length)
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
          const contents = transaction.objectStore('doc_contents')
          const sources = transaction.objectStore('doc_sources')
          contents.clear()
          sources.clear()
          for (const file of files) {
            const id = `${scope}:${file.id}`
            const originalMarkdownContent = file.originalMarkdownContent ?? file.markdownContent
            const blob = new Blob([originalMarkdownContent], { type: 'text/markdown' })
            contents.put({ id, markdownContent: file.markdownContent, originalMarkdownContent, updatedAt: Date.now() })
            sources.put({
              id,
              filename: file.filename,
              mimeType: blob.type,
              size: blob.size,
              lastModified: 0,
              updatedAt: Date.now(),
              blob,
            })
          }
          transaction.oncomplete = () => resolve()
          transaction.onerror = () => reject(transaction.error)
          transaction.onabort = () => reject(transaction.error)
        })
      } finally {
        database.close()
      }
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          version: 0,
          state: {
            files: files.map((file) => ({ ...file, markdownContent: '', originalMarkdownContent: '' })),
            folders,
            activeFolderId: 'root',
          },
        }),
      )
    },
    { storageKey, files, folders },
  )
  await page.goto('/parsing')
  return storageKey
}

export async function readParsingLibrary(page: Page, storageKey: string) {
  return page.evaluate(async (key) => {
    const raw = localStorage.getItem(key)
    if (raw === null) throw new Error('Expected the persisted document index')
    const snapshot = JSON.parse(raw) as { state: { files: ParsedFileData[] } }
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('mimirq', 2)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    try {
      const bodies = await new Promise<DocContentCacheRecord[]>((resolve, reject) => {
        const request = database.transaction('doc_contents', 'readonly').objectStore('doc_contents').getAll()
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
      })
      return { files: snapshot.state.files, bodies }
    } finally {
      database.close()
    }
  }, storageKey)
}
