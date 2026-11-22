import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'
import type { EvidenceItem } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

const datasetId = '11111111-1111-4111-8111-111111111111'
const suiteId = '22222222-2222-4222-8222-222222222222'
const documentId = '33333333-3333-4333-8333-333333333333'
const chunkId = '44444444-4444-4444-8444-444444444444'
const itemId = '55555555-5555-4555-8555-555555555555'
const convertedId = '66666666-6666-4666-8666-666666666666'
const feedbackId = '77777777-7777-4777-8777-777777777777'
const timestamp = '2026-11-16T00:00:00Z'
const questionHash = 'a1b2c3d4e5f60718'
const sourceText = '  😀诊断原文\n\n'
const currentReference = {
  document_id: documentId,
  chunk_id: chunkId,
  chunk_index: 0,
  family_collapse_key: null,
  hierarchy_family_key: null,
  page_number: null,
  start_char: null,
  end_char: null,
  pipeline_hash: 'current',
  doc_pipeline_key: 'current-key',
  record_identity: null,
  semantic_keys: [],
  quote: sourceText,
  label: '当前引用',
}
const staleReference = { ...currentReference, chunk_index: 1, label: '历史引用' }

function gate() {
  let release!: () => void
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

function dashboard() {
  const empty = { count: 0, p50_sec: null, p90_sec: null, mean_sec: null }
  return {
    generated_at: timestamp,
    suite_id: suiteId,
    dataset_id: datasetId,
    throughput: {
      window_days: 7,
      last_window: { created: 1, reviewed: 1, approved: 0 },
      draft_to_reviewed: { count: 1, p50_sec: 0, p90_sec: 0, mean_sec: 0 },
      reviewed_to_approved: empty,
      draft_to_approved: empty,
    },
    coverage: {
      language: [{ key: 'zh', items: 1, references: 2 }],
      file_type: [{ key: 'pdf', items: 1, references: 2 }],
      quality_bucket: [],
      channel: [],
      heatmaps: { language_x_file_type: { x: ['pdf', 'md'], y: ['zh'], z: [[1, 0]], metric: 'items' } },
    },
  }
}

async function installWorkbench(page: Page) {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  const seed: EvidenceItem = {
    id: itemId,
    tenant_id: '88888888-8888-4888-8888-888888888888',
    dataset_id: datasetId,
    suite_id: suiteId,
    status: 'reviewed',
    query: '重复引用诊断',
    expected_answer: '',
    tags: [],
    notes: '',
    source_metadata: {},
    reference_sources: [currentReference, staleReference],
    retrieval_snapshot: {},
    rag_config_snapshot: {},
    regression_case_id: null,
    created_by: null,
    reviewed_by: null,
    approved_by: null,
    archived_by: null,
    created_at: timestamp,
    updated_at: timestamp,
    reviewed_at: timestamp,
    approved_at: null,
    archived_at: null,
  }
  const state = {
    items: [seed] as EvidenceItem[],
    limits: [] as string[],
    conversions: 0,
    converted: false,
    conversionBodies: [] as Array<{ suite_id: string; tags: string[] }>,
  }
  await page.route(
    (url) => url.pathname === `/api/v1/datasets/${datasetId}`,
    (route) => route.fulfill({ json: { id: datasetId, name: '诊断知识库' } }),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/evidence/suites',
    (route) =>
      route.fulfill({
        json: {
          total: 1,
          items: [
            {
              id: suiteId,
              dataset_id: datasetId,
              name: '诊断核验集',
              tags: [],
              created_at: timestamp,
              updated_at: timestamp,
            },
          ],
        },
      }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/evidence/suites/${suiteId}/items`,
    (route) => route.fulfill({ json: { total: state.items.length, items: state.items } }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/evidence/suites/${suiteId}/hardcase-candidates`,
    (route) => {
      const limit = new URL(route.request().url()).searchParams.get('max_candidates')
      if (limit === null) throw new Error('Candidate query omitted its limit')
      state.limits.push(limit)
      return route.fulfill({
        json: {
          generated_at: timestamp,
          suite_id: suiteId,
          dataset_id: datasetId,
          enabled: true,
          metrics_path: 'fixture',
          window_minutes: 10080,
          max_bytes: 100000,
          truncated: true,
          feedback_scanned: 1,
          trace_index_size: 1,
          candidates:
            limit === '0' || state.converted
              ? []
              : [
                  {
                    question_hash: questionHash,
                    cluster_size: 1,
                    feedback_ids: [feedbackId],
                    request_ids: ['request-1'],
                    citations_count: 0,
                    retrieval_error_kinds: {},
                    rag_config_template: { template_key: 'policy', version: state.limits.length === 1 ? null : 0 },
                  },
                ],
        },
      })
    },
  )
  await page.route(
    (url) => url.pathname === `/api/v1/evidence/suites/${suiteId}/drift-audit`,
    (route) =>
      route.fulfill({
        json: {
          generated_at: timestamp,
          suite_id: suiteId,
          dataset_id: datasetId,
          total_items: state.items.length,
          total_references: state.converted ? 3 : 2,
          ok_references: state.converted ? 2 : 1,
          drift_references: 1,
          details_truncated: false,
          drifted_references: [
            {
              suite_id: suiteId,
              item_id: itemId,
              item_status: 'reviewed',
              dataset_id: datasetId,
              document_id: documentId,
              chunk_id: chunkId,
              reason: 'chunk_index_mismatch',
              expected: {
                document_id: documentId,
                chunk_id: chunkId,
                chunk_index: 1,
                pipeline_hash: 'current',
                doc_pipeline_key: 'current-key',
              },
              observed: { chunk_index: 0 },
            },
          ],
        },
      }),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/rag/retrieve',
    (route) =>
      route.fulfill({
        json: {
          schema: 'mimirq.evidence.v1',
          query_for_retrieval: '重复引用诊断',
          has_evidence: true,
          abstain_triggered: false,
          citations: [
            {
              document_id: documentId,
              chunk_id: chunkId,
              chunk_index: 0,
              page_number: null,
              document_name: '诊断原文',
              chunk_content: sourceText,
              retrieval_score: 0,
              relevance_score: 0.9,
            },
          ],
          metrics: {},
        },
      }),
  )
  return state
}

async function openWorkbench(page: Page) {
  await page.goto(`/datasets/${datasetId}/evidence`)
  await page.getByRole('button', { name: /诊断核验集/ }).click()
  await expect(page.getByRole('heading', { name: '证据条目', exact: true })).toBeVisible()
}

for (const width of [1440, 390]) {
  test(
    'retains truthful dashboard statistics and their accepted filter at width ' + width,
    async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      const pageErrors: string[] = []
      page.on('pageerror', (error) => pageErrors.push(error.message))
      await installWorkbench(page)
      let attempts = 0
      const initialRead = gate()
      await page.route(
        (url) => url.pathname === `/api/v1/evidence/suites/${suiteId}/dashboard`,
        async (route) => {
          attempts += 1
          if (attempts === 1) await initialRead.promise
          if (attempts === 2) return route.fulfill({ status: 503, json: { detail: '统计刷新失败 503' } })
          return route.fulfill({ json: dashboard() })
        },
      )
      await openWorkbench(page)
      await page.getByRole('button', { name: '证据集操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '统计概览', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Suite Dashboard', exact: true })
      try {
        await expect(dialog.getByRole('status', { name: '正在读取统计', exact: true })).toBeVisible()
      } finally {
        initialRead.release()
      }
      const table = dialog.getByRole('table', { name: '语言与文件类型覆盖', exact: true })
      await expect(table.getByRole('cell', { name: '0', exact: true })).toBeVisible()
      await expect(dialog).toContainText('p50 0s')
      await expect(dialog).toContainText('p50 未提供')
      await dialog.getByRole('checkbox', { name: 'Include archived items', exact: true }).click()
      await expect(dialog.getByRole('alert')).toContainText('统计刷新失败 503')
      await expect(table.getByRole('cell', { name: '0', exact: true })).toBeVisible()
      await expect(dialog).toContainText('当前统计：不含已归档条目')
      await expect(dialog.getByRole('checkbox', { name: 'Include archived items', exact: true })).toBeChecked()
      await page.screenshot({ path: testInfo.outputPath('dashboard-failed-filter.png') })
      await dialog.getByRole('button', { name: '重新读取', exact: true }).focus()
      await page.keyboard.press('Enter')
      await expect(dialog).toContainText('当前统计：包含已归档条目')
      await expect(dialog.getByRole('alert')).toHaveCount(0)
      expect(attempts).toBe(3)
      expect(pageErrors).toEqual([])
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath('dashboard-ready.png') })
    },
  )

  test(
    'keeps candidate drafts and diagnoses duplicate references independently at width ' + width,
    async ({ page, context }, testInfo) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      await context.grantPermissions(['clipboard-read', 'clipboard-write'])
      const pageErrors: string[] = []
      const duplicateKeys: string[] = []
      page.on('pageerror', (error) => pageErrors.push(error.message))
      page.on('console', (message) => {
        if (message.type() === 'error' && /same key/.test(message.text())) duplicateKeys.push(message.text())
      })
      const server = await installWorkbench(page)
      const conversion = gate()
      await page.route(
        (url) => url.pathname === `/api/v1/feedback/messages/${feedbackId}/to-evidence-item`,
        async (route) => {
          server.conversions += 1
          const body = route.request().postDataJSON() as { suite_id: string; tags: string[] }
          server.conversionBodies.push(body)
          if (server.conversions === 1) return route.fulfill({ status: 503, json: { detail: '反馈尚未保存 503' } })
          await conversion.promise
          const created: EvidenceItem = {
            ...server.items[0],
            id: convertedId,
            status: 'draft',
            query: '反馈草稿',
            tags: body.tags,
            reference_sources: [currentReference],
            reviewed_at: null,
          }
          server.items = [created, ...server.items]
          server.converted = true
          return route.fulfill({ json: created })
        },
      )
      await openWorkbench(page)
      await page.getByRole('button', { name: '证据集操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '难例候选', exact: true }).click()
      const candidates = page.getByRole('dialog', { name: 'Hardcase Candidates', exact: true })
      await expect(candidates).toContainText('cites 0')
      await expect(candidates).not.toContainText('version 0')
      const limit = candidates.getByRole('spinbutton', { name: 'max candidates', exact: true })
      await limit.fill('')
      await expect(limit).toHaveValue('')
      await expect(candidates.getByRole('button', { name: 'refresh', exact: true })).toBeDisabled()
      await limit.fill('201')
      await expect(limit).toHaveValue('201')
      await expect(limit).toHaveAttribute('aria-invalid', 'true')
      expect(server.limits).toEqual(['50'])
      await page.screenshot({ path: testInfo.outputPath('candidate-invalid-limit.png') })
      await limit.fill('0')
      await limit.press('Enter')
      await expect(candidates).toContainText('本次候选数量设为 0')
      expect(server.limits).toEqual(['50', '0'])
      await limit.fill('25')
      await limit.press('Enter')
      await expect(candidates).toContainText('version 0')
      expect(server.limits).toEqual(['50', '0', '25'])
      await candidates.getByRole('button', { name: '复制 question_hash', exact: true }).click()
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(questionHash)
      await candidates.getByRole('textbox', { name: 'Convert tags', exact: true }).fill('长'.repeat(65))
      await candidates.getByRole('button', { name: '转为 draft', exact: true }).click()
      expect(server.conversions).toBe(0)
      await expect(candidates.getByRole('textbox', { name: 'Convert tags', exact: true })).toHaveValue('长'.repeat(65))
      await candidates.getByRole('textbox', { name: 'Convert tags', exact: true }).fill('复核标签')
      await candidates.getByRole('textbox', { name: 'Convert tags', exact: true }).press('Enter')
      await candidates.getByRole('button', { name: '转为 draft', exact: true }).click()
      await expect(candidates.getByRole('alert')).toContainText('反馈尚未保存 503')
      await expect(candidates).toContainText('复核标签')
      await page.screenshot({ path: testInfo.outputPath('candidate-failed-conversion.png') })
      await candidates.getByRole('button', { name: '转为 draft', exact: true }).focus()
      await page.keyboard.press('Enter')
      try {
        await expect(candidates.getByRole('button', { name: '转为 draft', exact: true })).toBeDisabled()
      } finally {
        conversion.release()
      }
      await expect(candidates.getByRole('button', { name: '转为 draft', exact: true })).toHaveCount(0)
      expect(server.conversions).toBe(2)
      expect(server.conversionBodies[1]).toMatchObject({ suite_id: suiteId, tags: ['hardcase', '复核标签'] })
      await candidates.getByRole('button', { name: 'Close', exact: true }).click()
      await page.reload()
      await page.getByRole('button', { name: /诊断核验集/ }).click()
      await expect(page.getByRole('button', { name: '反馈草稿', exact: true })).toBeVisible()
      await page.getByRole('button', { name: '重复引用诊断', exact: true }).click()
      await page
        .getByRole('dialog', { name: '证据条目', exact: true })
        .getByRole('button', { name: 'Why missed?', exact: true })
        .click()
      const why = page.getByRole('dialog', { name: 'Why missed?', exact: true })
      await why.getByRole('button', { name: '运行检索', exact: true }).click()
      await expect(why).toContainText('drifted 1')
      await expect(why).toContainText('retrieved 1')
      const references = why
        .getByRole('heading', { name: 'Ground Truth（reference_sources）', exact: true })
        .locator('..')
      await expect(references.locator('article')).toHaveCount(2)
      await expect(references.getByText('已召回', { exact: true })).toHaveCount(1)
      await expect(references.getByText('引用已变化', { exact: true })).toHaveCount(1)
      const downloadEvent = page.waitForEvent('download')
      await why.getByRole('button', { name: '导出 JSON', exact: true }).click()
      const download = await downloadEvent
      const path = testInfo.outputPath('diagnosis.json')
      await download.saveAs(path)
      const report = JSON.parse(await readFile(path, 'utf8'))
      expect(report.report.references.find((row: { label: string }) => row.label === '当前引用').status).toBe(
        'retrieved',
      )
      expect(report.report.references.find((row: { label: string }) => row.label === '历史引用').status).toBe('drifted')
      expect(report.citations[0].chunk_content).toBe(sourceText)
      expect(report.citations[0].retrieval_score).toBe(0)
      await page.screenshot({ path: testInfo.outputPath('independent-reference-diagnosis.png') })
      await why.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(page.getByRole('button', { name: '重复引用诊断', exact: true })).toBeFocused()
      expect(duplicateKeys).toEqual([])
      expect(pageErrors).toEqual([])
    },
  )
}
