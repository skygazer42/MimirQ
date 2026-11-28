import { expect, test, type Page } from '@playwright/test'
import { installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

const existingChunk = {
  id: 'edit-hit',
  content: 'Original chunk text',
  chunk_index: 0,
  page_number: 0,
  start_char: 0,
  end_char: 2,
  disabled_at: null,
  created_at: null,
  updated_at: null,
  metadata: {},
}

async function openChunkViewer(page: Page) {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks/edit-hit`,
    (route) => route.fulfill({ json: existingChunk }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks`,
    (route) => route.fulfill({ json: { total: 1, items: [existingChunk] } }),
  )
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}&chunk=edit-hit`)
  await page.getByRole('tab', { name: '切片', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Edit chunk', exact: true })).toBeEnabled()
}

test('saves exact text, locks the accepted draft and supports clearing an existing chunk', async ({ page }) => {
  await openChunkViewer(page)
  const raw = '  const value = 1\n\n'
  let release!: () => void
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  const updates: unknown[] = []
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks/edit-hit`,
    async (route) => {
      if (route.request().method() !== 'PATCH') {
        await route.fallback()
        return
      }
      updates.push(route.request().postDataJSON())
      if (updates.length === 1) await pending
      await route.fulfill({ json: { ...existingChunk, content: updates.length === 1 ? raw : '' } })
    },
  )
  await page.getByRole('button', { name: 'Edit chunk', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Edit chunk #0', exact: true })
  await dialog.getByRole('textbox', { name: 'Content', exact: true }).fill(raw)
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  try {
    await expect(dialog.getByRole('textbox', { name: 'Content', exact: true })).toBeDisabled()
    await expect(dialog.getByRole('textbox', { name: 'Page (optional)', exact: true })).toBeDisabled()
  } finally {
    release()
  }
  await expect(dialog).toHaveCount(0)
  expect(updates[0]).toMatchObject({ content: raw, page_number: 0, start_char: 0, end_char: 2 })
  await page.getByRole('button', { name: 'Edit chunk', exact: true }).click()
  await expect(dialog.getByRole('textbox', { name: 'Content', exact: true })).toHaveValue(raw)
  await dialog.getByRole('textbox', { name: 'Content', exact: true }).fill('')
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(updates[1]).toMatchObject({ content: '' })
})

test('preserves invalid position text and submits legitimate zero positions', async ({ page }) => {
  await openChunkViewer(page)
  const created: unknown[] = []
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks`,
    async (route) => {
      if (route.request().method() !== 'POST') {
        await route.fallback()
        return
      }
      created.push(route.request().postDataJSON())
      await route.fulfill({
        json: { ...existingChunk, id: 'created-hit', content: 'New chunk', page_number: 0, start_char: 0, end_char: 0 },
      })
    },
  )
  await page.getByRole('button', { name: 'Add chunk', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Add chunk', exact: true })
  await dialog.getByRole('textbox', { name: 'Content', exact: true }).fill('New chunk')
  await dialog.getByRole('textbox', { name: 'Page (optional)', exact: true }).fill('1.5')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog.getByRole('textbox', { name: 'Page (optional)', exact: true })).toHaveValue('1.5')
  await expect(page.getByText('页码必须为 0 到 100000 之间的整数', { exact: true })).toBeVisible()
  expect(created).toEqual([])
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/viewer-edits/invalid-position.png',
    fullPage: true,
  })
  await dialog.getByRole('textbox', { name: 'Page (optional)', exact: true }).fill('0')
  await dialog.getByRole('textbox', { name: 'Start Char', exact: true }).fill('0')
  await dialog.getByRole('textbox', { name: 'End Char', exact: true }).fill('0')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(created).toContainEqual(expect.objectContaining({ page_number: 0, start_char: 0, end_char: 0 }))
})

test('keeps invalid Q&A drafts and submits exact valid integers and false flags', async ({ page }) => {
  await openChunkViewer(page)
  const requests: unknown[] = []
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/qa/generate`,
    async (route) => {
      requests.push(route.request().postDataJSON())
      await route.fulfill({
        json: {
          document_id: UPLOADED_DOCUMENT_ID,
          mode: 'extract',
          created: 0,
          deleted: 0,
          chunk_ids: [],
          preview: [],
        },
      })
    },
  )
  await page.getByRole('button', { name: 'Q&A', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Generate Q&A chunks', exact: true })
  await dialog.getByRole('textbox', { name: 'Num pairs', exact: true }).fill('0')
  await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
  await expect(dialog.getByRole('textbox', { name: 'Num pairs', exact: true })).toHaveValue('0')
  expect(requests).toEqual([])
  await dialog.getByRole('textbox', { name: 'Num pairs', exact: true }).fill('1')
  await dialog.getByRole('textbox', { name: 'Max source chars', exact: true }).fill('500')
  await dialog.getByRole('checkbox', { name: 'Replace existing QA chunks', exact: true }).uncheck()
  await dialog.getByRole('checkbox', { name: 'Prefer LLM (if configured)', exact: true }).uncheck()
  await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toMatchObject({ num_pairs: 1, max_source_chars: 500, replace_existing: false, prefer_llm: false })
})
