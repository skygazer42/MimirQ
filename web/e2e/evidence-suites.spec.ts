import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'
import type { EvidenceItem, EvidenceItemCreate, EvidenceSuite } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

const datasetId = '11111111-1111-4111-8111-111111111111'
const suiteId = '22222222-2222-4222-8222-222222222222'
const otherSuiteId = '33333333-3333-4333-8333-333333333333'
const documentId = '44444444-4444-4444-8444-444444444444'
const chunkId = '55555555-5555-4555-8555-555555555555'
const timestamp = '2026-11-16T00:00:00Z'
const source = {
  document_id: documentId,
  document_name: '证据原文',
  chunk_id: chunkId,
  chunk_content: '  😀原文\n\n',
  chunk_index: 0,
  page_number: null,
  retrieval_score: 0,
  relevance_score: 0.9,
  metadata: { active: false, label: '' },
}

function gate() {
  let release!: () => void
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

async function installSuiteApi(page: Page) {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  const suites: Pick<EvidenceSuite, 'id' | 'name' | 'dataset_id' | 'tags' | 'created_at' | 'updated_at'>[] = [
    { id: suiteId, name: '原文核验集', dataset_id: datasetId, tags: [], created_at: timestamp, updated_at: timestamp },
    {
      id: otherSuiteId,
      name: '另一证据集',
      dataset_id: datasetId,
      tags: [],
      created_at: timestamp,
      updated_at: timestamp,
    },
  ]
  const state = {
    suites,
    items: [] as EvidenceItem[],
    bodies: [] as EvidenceItemCreate[],
    createAttempts: 0,
    syncCalls: 0,
    failItemRead: false,
  }
  await page.route(
    (url) => url.pathname === `/api/v1/datasets/${datasetId}`,
    (route) => route.fulfill({ json: { id: datasetId, name: '证据知识库' } }),
  )
  await page.route('**/api/v1/evidence/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/evidence/suites' && request.method() === 'GET')
      return route.fulfill({ json: { total: suites.length, items: suites } })
    if (path === `/api/v1/evidence/suites/${suiteId}/items` && request.method() === 'GET') {
      if (state.failItemRead) {
        state.failItemRead = false
        return route.fulfill({ status: 503, json: { detail: '列表刷新失败 503' } })
      }
      return route.fulfill({ json: { total: state.items.length, items: state.items } })
    }
    if (path === `/api/v1/evidence/suites/${otherSuiteId}/items`)
      return route.fulfill({ json: { total: 0, items: [] } })
    if (path === `/api/v1/evidence/suites/${suiteId}/items` && request.method() === 'POST') {
      state.createAttempts += 1
      const body = request.postDataJSON() as EvidenceItemCreate
      state.bodies.push(body)
      if (state.createAttempts === 1) return route.fulfill({ status: 503, json: { detail: '创建尚未保存 503' } })
      const created: EvidenceItem = {
        ...body,
        id: '66666666-6666-4666-8666-666666666666',
        tenant_id: '77777777-7777-4777-8777-777777777777',
        status: 'draft',
        created_at: timestamp,
        updated_at: timestamp,
      }
      state.items = [created]
      return route.fulfill({ json: created })
    }
    const action = path.split('/').at(-1)
    if (
      path.startsWith('/api/v1/evidence/items/') &&
      (action === 'review' || action === 'approve' || action === 'archive')
    ) {
      const status = action === 'review' ? 'reviewed' : action === 'approve' ? 'approved' : 'archived'
      state.items = state.items.map((item) => ({ ...item, status }))
      return route.fulfill({ json: state.items[0] })
    }
    if (path === `/api/v1/evidence/suites/${suiteId}/sync-regression`) {
      state.syncCalls += 1
      state.failItemRead = true
      return route.fulfill({
        json: { suite_id: suiteId, dataset_id: datasetId, created: 1, updated: 0, skipped: 0, errors: [] },
      })
    }
    throw new Error(`Unexpected evidence API: ${request.method()} ${path}`)
  })
  return state
}

async function openWorkbench(page: Page) {
  await page.goto(`/datasets/${datasetId}/evidence`)
  await page.getByRole('button', { name: /原文核验集/ }).click()
  await expect(page.getByRole('heading', { name: '证据条目', exact: true })).toBeVisible()
}

for (const width of [1440, 390]) {
  test('validates tags before creating a suite at width ' + width, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    const server = await installSuiteApi(page)
    const writes: Array<{ name: string; description: string; tags: string[] }> = []
    await page.route('**/api/v1/evidence/suites/99999999-9999-4999-8999-999999999999/items*', (route) =>
      route.fulfill({ json: { total: 0, items: [] } }),
    )
    await page.route(
      (url) => url.pathname === '/api/v1/evidence/suites',
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.fallback()
          return
        }
        const body = route.request().postDataJSON() as { name: string; description: string; tags: string[] }
        writes.push(body)
        if (writes.length === 1) {
          await route.fulfill({ status: 503, json: { detail: '证据集尚未保存' } })
          return
        }
        const created = { ...server.suites[0], ...body, id: '99999999-9999-4999-8999-999999999999' }
        server.suites.push(created)
        await route.fulfill({ json: created })
      },
    )
    await page.goto(`/datasets/${datasetId}/evidence`)
    await page.getByRole('button', { name: '新建', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '新建证据集', exact: true })
    await dialog.getByRole('textbox', { name: '名称', exact: true }).fill('标签核验集')
    const input = dialog.getByRole('textbox', { name: '标签（选填）', exact: true })
    await input.fill('长'.repeat(65))
    await dialog.getByRole('button', { name: '创建', exact: true }).click()
    expect(writes).toEqual([])
    await expect(input).toHaveValue('长'.repeat(65))
    await input.fill('已核验')
    await input.press('Enter')
    await dialog.getByRole('button', { name: '创建', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('证据集尚未保存')
    await expect(dialog.getByRole('button', { name: '移除标签 已核验', exact: true })).toBeVisible()
    await dialog.getByRole('button', { name: '创建', exact: true }).click()
    await expect(dialog).toBeHidden()
    expect(writes).toHaveLength(2)
    expect(writes[1].tags).toEqual(['已核验'])
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: /标签核验集/ })).toBeVisible()
  })

  test('preserves evidence drafts and reads confirmed status back at width ' + width, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    const server = await installSuiteApi(page)
    const response = {
      schema: 'mimirq.evidence.v1',
      query_for_retrieval: '原文问题',
      has_evidence: true,
      abstain_triggered: false,
      citations: [{ document_id: 'minimal' }, source],
      metrics: {},
      retrieval_trace: { kept: false },
    }
    await page.route(
      (url) => url.pathname === '/api/v1/rag/retrieve',
      (route) => route.fulfill({ json: response }),
    )
    await openWorkbench(page)
    await page.getByRole('button', { name: '新建条目', exact: true }).click()
    const create = page.getByRole('dialog', { name: '新建 Evidence Item', exact: true })
    await create.getByRole('textbox', { name: 'Query', exact: true }).fill('原文问题')
    await create.getByRole('textbox', { name: 'Notes（可选）', exact: true }).fill('  保留备注\n')
    await create.getByRole('button', { name: '运行检索', exact: true }).click()
    const choices = create.getByRole('checkbox', { name: '选择该引用', exact: true })
    await expect(choices).toHaveCount(2)
    await expect(choices.nth(0)).toBeDisabled()
    await expect(create).toContainText('0.0000')
    await choices.nth(1).click()
    await create.getByRole('button', { name: '创建 Item（draft）', exact: true }).click()
    await expect(page.getByText(/创建尚未保存 503/)).toBeVisible()
    await expect(create).toBeVisible()
    await expect(create.getByRole('textbox', { name: 'Notes（可选）', exact: true })).toHaveValue('  保留备注\n')
    await expect(choices.nth(1)).toBeChecked()
    await page.screenshot({ path: testInfo.outputPath('create-failed-draft.png') })
    await create.getByRole('button', { name: '创建 Item（draft）', exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(create).toBeHidden()
    expect(server.createAttempts).toBe(2)
    expect(server.bodies[1]).toMatchObject({
      expected_answer: '',
      notes: '  保留备注\n',
      retrieval_snapshot: response,
      reference_sources: [{ document_id: documentId, chunk_id: chunkId, chunk_index: 0, quote: source.chunk_content }],
    })
    await page.getByRole('button', { name: '原文问题', exact: true }).click()
    const detail = page.getByRole('dialog', { name: '证据条目', exact: true })
    await detail.getByRole('button', { name: 'Review', exact: true }).click()
    await detail.getByRole('button', { name: 'Approve', exact: true }).click()
    await expect(detail.getByText('approved', { exact: true })).toBeVisible()
    await detail.getByRole('button', { name: 'Close', exact: true }).click()
    await page.reload()
    await page.getByRole('button', { name: /原文核验集/ }).click()
    await expect(
      page.getByRole('row').filter({ has: page.getByRole('button', { name: '原文问题', exact: true }) }),
    ).toContainText('已通过')
    await page.getByRole('button', { name: '同步到回归用例', exact: true }).click()
    const confirm = page.getByRole('alertdialog', { name: '同步到回归用例库？', exact: true })
    await confirm.getByRole('button', { name: '同步用例', exact: true }).click()
    await expect(confirm.getByRole('alert')).toContainText('只刷新列表')
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: '重试刷新', exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(confirm).toBeHidden()
    expect(server.syncCalls).toBe(1)
    expect(server.items[0].status).toBe('approved')
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('approved-readback.png') })
  })

  test(
    'retains accepted imports and retires closed reads and old downloads at width ' + width,
    async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      await installSuiteApi(page)
      const retrieval = gate()
      await page.route(
        (url) => url.pathname === '/api/v1/rag/retrieve',
        async (route) => {
          await retrieval.promise
          return route.fulfill({
            json: {
              schema: 'mimirq.evidence.v1',
              query_for_retrieval: '旧请求',
              citations: [source],
              metrics: {},
              has_evidence: true,
              abstain_triggered: false,
            },
          })
        },
      )
      await openWorkbench(page)
      await page.getByRole('button', { name: '新建条目', exact: true }).click()
      const create = page.getByRole('dialog', { name: '新建 Evidence Item', exact: true })
      await create.getByRole('textbox', { name: 'Query', exact: true }).fill('旧请求')
      const responded = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/v1/rag/retrieve')
      await create.getByRole('button', { name: '运行检索', exact: true }).click()
      try {
        await create.getByRole('button', { name: '取消', exact: true }).click()
      } finally {
        retrieval.release()
      }
      await (await responded).finished()
      await expect(create).toBeHidden()
      await page.getByRole('button', { name: '新建条目', exact: true }).click()
      await expect(create.getByRole('checkbox', { name: '选择该引用', exact: true })).toHaveCount(0)
      await create.getByRole('tab', { name: '导入 Evidence Pack', exact: true }).click()
      const pack = { version: 0, citations: [source], selected_chunk_ids: [chunkId], metadata: { flag: false } }
      const file = create.locator('input[type="file"]')
      await file.setInputFiles({
        name: 'pack.json',
        mimeType: 'application/json',
        buffer: Buffer.from(JSON.stringify(pack)),
      })
      await expect(create.getByRole('checkbox', { name: '选择该引用', exact: true })).toBeChecked()
      await file.setInputFiles({ name: 'broken.json', mimeType: 'application/json', buffer: Buffer.from('{') })
      await expect(create.getByRole('alert')).toContainText('解析失败')
      await expect(create.getByRole('checkbox', { name: '选择该引用', exact: true })).toBeChecked()
      await expect(create).toContainText('pack version 0')
      await page.screenshot({ path: testInfo.outputPath('import-failed-retained.png') })
      await create.getByRole('button', { name: '取消', exact: true }).click()
      const exportGate = gate()
      const exported = {
        schema: 'mimirq.evidence_suite.v1',
        exported_at: timestamp,
        dataset_id: datasetId,
        suite: { id: suiteId, name: '原文核验集' },
        items: [],
        raw: { kept: false },
      }
      let exports = 0
      await page.route(
        (url) => url.pathname === `/api/v1/evidence/suites/${suiteId}/export`,
        async (route) => {
          exports += 1
          if (exports === 2) await exportGate.promise
          return route.fulfill({ json: exported })
        },
      )
      await page.getByRole('button', { name: '证据集操作', exact: true }).click()
      const downloadEvent = page.waitForEvent('download')
      await page.getByRole('menuitem', { name: '导出证据集', exact: true }).click()
      const download = await downloadEvent
      const path = testInfo.outputPath('suite.json')
      await download.saveAs(path)
      expect(JSON.parse(await readFile(path, 'utf8'))).toEqual(exported)
      const downloads: string[] = []
      page.on('download', (event) => downloads.push(event.suggestedFilename()))
      const exportResponse = page.waitForResponse(
        (response) => new URL(response.url()).pathname === `/api/v1/evidence/suites/${suiteId}/export`,
      )
      await page.getByRole('button', { name: '证据集操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '导出证据集', exact: true }).click()
      try {
        if (width === 390) await page.getByRole('button', { name: '证据集', exact: true }).click()
        await page.getByRole('button', { name: /另一证据集/ }).click()
      } finally {
        exportGate.release()
      }
      await (await exportResponse).finished()
      await page.evaluate(
        () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
      )
      expect(downloads).toEqual([])
      await page.screenshot({ path: testInfo.outputPath('retired-suite-export.png') })
    },
  )
}
