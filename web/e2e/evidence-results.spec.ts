import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'
import { fulfillChatStream, installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

const datasetId = '11111111-1111-4111-8111-111111111111'

async function installDatasets(page: Page) {
  await page.route(
    (url) => url.pathname === '/api/v1/datasets' || url.pathname === '/api/v1/datasets/',
    (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: datasetId,
              name: '证据知识库',
              created_at: '2026-11-15T00:00:00Z',
              updated_at: '2026-11-15T00:00:00Z',
            },
          ],
          total: 1,
        },
      }),
  )
}

for (const width of [1440, 390]) {
  test('retains truthful evidence and exports its committed response at width ' + width, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
    const raw = {
      schema: 'mimirq.evidence.v1',
      query_for_retrieval: '',
      has_evidence: true,
      abstain_triggered: false,
      citations: [
        { document_id: 'minimal-id' },
        {
          document_id: 'same-id',
          document_name: '原始文档',
          chunk_content: '',
          page_number: 0,
          chunk_index: 0,
          retrieval_score: 0.875,
          relevance_score: 0.1,
        },
        {
          document_id: 'same-id',
          document_name: '保留原文',
          chunk_content: '  😀 source\n\n',
          retrieval_score: 0,
          extra: { active: false },
        },
      ],
      metrics: { top_relevance_score: 0, retrieval_elapsed_sec: 0 },
      retrieval_trace: { preserved: false },
      query_debug: { original: '' },
    }
    let attempts = 0
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.route(
      (url) => url.pathname === '/api/v1/rag/retrieve',
      async (route) => {
        attempts += 1
        if (attempts === 1) {
          await gate
          return route.fulfill({ json: raw })
        }
        if (attempts === 2) return route.fulfill({ status: 503, json: { detail: '证据服务暂时不可用 503' } })
        return route.fulfill({ json: { ...raw, citations: [{ document_id: 'malformed', relevance_score: false }] } })
      },
    )
    await page.goto('/knowledge/evidence')
    await page.getByRole('textbox', { name: '检索问题', exact: true }).fill('  当前检索问题  ')
    await page.getByRole('button', { name: '运行检索', exact: true }).click()
    try {
      await expect(page.getByRole('status', { name: '正在检索当前问题的证据', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '导出结果', exact: true })).toBeDisabled()
      await page.screenshot({ path: testInfo.outputPath('retrieval-loading.png') })
    } finally {
      release()
    }
    const citations = page.getByRole('region', { name: '引用证据列表', exact: true })
    await expect(citations.locator('article')).toHaveCount(3)
    await expect(citations.locator('article').nth(0)).toContainText('未提供')
    await expect(citations.locator('article').nth(1)).toContainText('P.0')
    await expect(citations.locator('article').nth(1)).toContainText('0.8750')
    await expect(citations.locator('article').nth(1)).toContainText('原文为空')
    expect(await citations.locator('article').nth(2).locator('p').textContent()).toBe('  😀 source\n\n')
    if (width === 390) await page.getByRole('button', { name: '问题与范围', exact: true }).click()
    await page.getByRole('button', { name: '运行检索', exact: true }).click()
    const notice = page.getByRole('alert').filter({ has: page.getByRole('button', { name: '重新检索', exact: true }) })
    await expect(notice).toContainText('503')
    await expect(citations.locator('article')).toHaveCount(3)
    const downloaded = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出结果', exact: true }).click()
    const download = await downloaded
    const path = testInfo.outputPath('evidence-pack.json')
    await download.saveAs(path)
    const pack = JSON.parse(await readFile(path, 'utf8'))
    expect(pack).toMatchObject(raw)
    expect(pack.request.query).toBe('当前检索问题')
    await page.getByRole('button', { name: '重新检索', exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(notice).toContainText('relevance_score')
    await expect(citations.locator('article')).toHaveCount(3)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('retrieval-error-retained.png') })
  })

  test(
    'retains failed JSON drafts and suppresses downloads after tools close at width ' + width,
    async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
      await installDatasets(page)
      let saves = 0
      await page.route(
        (url) => url.pathname === '/api/v1/evidence/capsules',
        (route) => {
          saves += 1
          return route.fulfill({ status: 503, json: { detail: '保存未完成 503' } })
        },
      )
      await page.goto('/knowledge/evidence')
      await page.getByRole('button', { name: '高级工具', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '证据高级工具', exact: true })
      await dialog.locator('summary').filter({ hasText: '高级参数' }).click()
      const payload = dialog.getByRole('textbox', { name: '高级载荷（JSON）', exact: true })
      await payload.fill('')
      await dialog.getByRole('button', { name: '保存证据快照', exact: true }).click()
      await expect(dialog.getByRole('alert')).toBeVisible()
      expect(saves).toBe(0)
      const source = '{"capsule":{"schema":"mimirq.evidence_capsule.v1","claims":[]},"overwrite":false}'
      await payload.fill(source)
      await dialog.getByRole('button', { name: '保存证据快照', exact: true }).click()
      await expect(dialog.getByRole('alert')).toContainText('503')
      await expect(dialog.getByRole('alert')).toBeInViewport()
      await expect(payload).toHaveValue(source)
      expect(saves).toBe(1)
      await page.screenshot({ path: testInfo.outputPath('tools-failed-draft.png') })
      await dialog.getByRole('combobox', { name: '数据集', exact: true }).click()
      await page.getByRole('option', { name: '证据知识库', exact: true }).click()
      let release!: () => void
      const gate = new Promise<void>((resolve) => {
        release = resolve
      })
      await page.route(
        (url) => url.pathname === '/api/v1/evidence/training-export',
        async (route) => {
          await gate
          return route.fulfill({ contentType: 'application/jsonl', body: '{"row":1}\n' })
        },
      )
      const downloads: string[] = []
      page.on('download', (download) => downloads.push(download.suggestedFilename()))
      const responded = page.waitForResponse(
        (response) => new URL(response.url()).pathname === '/api/v1/evidence/training-export',
      )
      await dialog.getByRole('button', { name: '导出训练集', exact: true }).click()
      try {
        await expect(dialog.getByRole('button', { name: '导出训练集', exact: true })).toHaveAttribute(
          'aria-busy',
          'true',
        )
        await dialog.getByRole('button', { name: '完成', exact: true }).click()
      } finally {
        release()
      }
      await (await responded).finished()
      await expect(dialog).toBeHidden()
      await page.evaluate(
        () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
      )
      expect(downloads).toEqual([])
      await expect(page.getByText('导出训练集完成', { exact: true })).toHaveCount(0)
    },
  )
}

test('recovers clipboard failure in the real evidence dialog without changing source JSON', async ({
  page,
  context,
}, testInfo) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  await installDatasets(page)
  const citation = {
    document_id: UPLOADED_DOCUMENT_ID,
    document_name: '  😀证据文档  ',
    chunk_id: 'clipboard-chunk',
    hit_type: 'table',
    chunk_content: '  😀原文\n\n',
    relevance_score: 0,
    page_number: 0,
    evidence_start_char: 0,
    evidence_end_char: 2,
  }
  await page.route(
    (url) => url.pathname === '/api/v1/chat/stream',
    (route) =>
      fulfillChatStream(route, {
        contentParts: ['请查看原文。'],
        citations: [citation],
        requestId: 'evidence-copy',
      }),
  )
  await page.goto('/')
  await expect(page.getByRole('button', { name: '证据知识库', exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: '消息输入框', exact: true }).fill('查看原文')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.locator('summary').filter({ hasText: '来源与证据' }).click()
  await page.getByRole('button', { name: 'view-evidence', exact: true }).click()
  const dialog = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: /证据.*P\.0/ }) })
  await expect(dialog).toBeVisible()
  expect(await dialog.locator('pre').textContent()).toBe(citation.chunk_content)
  await page.evaluate(() =>
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async () => {
          throw new Error('复制被浏览器拒绝')
        },
      },
    }),
  )
  await dialog.getByRole('button', { name: '复制 JSON', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('复制被浏览器拒绝')
  await page.screenshot({ path: testInfo.outputPath('clipboard-error.png') })
  await page.evaluate(() => Reflect.deleteProperty(navigator, 'clipboard'))
  await dialog.getByRole('button', { name: '复制 JSON', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: '复制 JSON', exact: true })).toBeEnabled()
  expect(JSON.parse(await page.evaluate(() => navigator.clipboard.readText()))).toEqual(citation)
  await page.screenshot({ path: testInfo.outputPath('clipboard-recovered.png') })
})
