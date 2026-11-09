import fs from 'node:fs'
import { expect, test, type Route } from '@playwright/test'

import type { RagasRegressionRunDiffResponse, RegressionRun } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const datasetId = 'ablation-metric-dataset'
const runIds = { base: 'metric-base', target: 'metric-target' }
const runs: RegressionRun[] = [runIds.target, runIds.base].map((id, index) => ({
  id, tenant_id: 'metric-tenant', dataset_id: datasetId, status: 'completed',
  metrics: ['retrieval_recall', 'retrieval_mrr'], params: { top_k: index ? 5 : 10 },
  summary: { retrieval_recall: 0.5, retrieval_mrr: 0.75 },
  created_at: `2026-10-26T0${index + 8}:00:00Z`, finished_at: '2026-10-26T10:00:00Z',
}))

const diff: RagasRegressionRunDiffResponse = {
  base_run_id: runIds.base, target_run_id: runIds.target, generated_at: '2026-10-26T10:00:00Z',
  base_params: { top_k: 5 }, target_params: { top_k: 10 },
  metric_diffs: [{ key: 'retrieval_recall', delta: null }, { key: 'retrieval_mrr', delta: 0 }],
  significance: [
    { key: 'retrieval_recall', compared: 0, delta_mean: null, significant: false },
    { key: 'retrieval_mrr', compared: 2, delta_mean: 0, significant: false },
  ],
  slice_diffs: {
    file_type: { truncated_before: false, truncated_after: false, buckets: [
      { key: 'PDF missing recall', items_before: 2, items_after: 2, metrics: [
        { key: 'retrieval_recall', delta: null }, { key: 'retrieval_mrr', delta: 0.25 },
      ] },
      { key: 'HTML measured recall', items_before: 2, items_after: 2, metrics: [
        { key: 'retrieval_recall', delta: 0.125 }, { key: 'retrieval_mrr', delta: 0.25 },
      ] },
      { key: 'Markdown zero recall', items_before: 2, items_after: 2, metrics: [
        { key: 'retrieval_recall', delta: 0 }, { key: 'retrieval_mrr', delta: 0.25 },
      ] },
    ] },
  },
  case_diffs: [], significance_summary: {},
}

async function json(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

test('deep dive preserves missing metrics, measured zero and preferred measured slice values', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1600, height: 1000 })
  await installCommonApiMocks(page, { uploaded: false })
  await page.addInitScript(() => { localStorage.setItem('theme', 'light') })
  const pageErrors: string[] = []
  const failedApiResponses: string[] = []
  const diffRequests: string[] = []
  const writes: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('response', response => {
    if (response.url().includes('/api/v1/') && response.status() >= 400) failedApiResponses.push(`${response.status()} ${response.url()}`)
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/api/v1/rbac/me') return json(route, { tenant_id: 'metric-tenant', account_id: 'metric-admin', role: 'admin', permissions: [], is_active: true, is_current: true })
    if (/^\/api\/v1\/datasets\/?$/.test(url.pathname)) return json(route, { total: 1, items: [{ id: datasetId, tenant_id: 'metric-tenant', name: '指标回归验证', permission: 'all_team_members' }] })
    if (!url.pathname.startsWith('/api/v1/evaluations/ragas/regression/')) return route.fallback()
    if (request.method() !== 'GET') writes.push(`${request.method()} ${url.pathname}`)
    if (url.pathname.endsWith('/diff')) { diffRequests.push(url.search); return json(route, diff) }
    if (url.pathname.endsWith('/leaderboard')) return json(route, { items: runs.map(run => ({ run_id: run.id, status: run.status, metric_key: 'retrieval_mrr', metric_value: 0.75 })) })
    if (url.pathname.endsWith('/runs')) return json(route, { total: runs.length, items: runs })
    if (url.pathname.endsWith('/cases')) return json(route, { total: 1, items: [{ id: 'metric-case', question: '指标是否有实际测量结果？' }] })
    return route.fallback()
  })

  await page.goto('/evaluations/ablations', { waitUntil: 'domcontentloaded' })
  const generate = page.getByRole('button', { name: '生成对比', exact: true })
  await expect(generate).toBeEnabled({ timeout: 60_000 })
  await generate.click()
  await expect.poll(() => diffRequests.length).toBe(1)
  expect(new URLSearchParams(diffRequests[0]).get('include_significance')).toBe('true')
  await page.getByRole('tab', { name: '深度分析', exact: true }).click()

  const statistics = page.getByText('统计显著性审查', { exact: true }).locator('xpath=ancestor::section[1]')
  const missing = statistics.getByText('retrieval_recall', { exact: true }).locator('..')
  const zero = statistics.getByText('retrieval_mrr', { exact: true }).locator('..')
  await expect(missing).toContainText('等待 metric diff')
  await expect(missing).not.toContainText('0.0000')
  await expect(zero).toContainText('0.0000')
  await expect(zero).toContainText('无明显变化')
  await statistics.scrollIntoViewIfNeeded()
  const statisticsImage = testInfo.outputPath('statistics-missing-and-zero.png')
  await statistics.screenshot({ path: statisticsImage })
  await testInfo.attach('Missing and measured-zero statistics', { path: statisticsImage, contentType: 'image/png' })

  const slices = page.getByText('切片差异', { exact: true }).locator('xpath=ancestor::section[1]')
  for (const [bucket, expected] of [['PDF missing recall', '+0.2500'], ['HTML measured recall', '+0.1250'], ['Markdown zero recall', '+0.0000']]) {
    const header = slices.getByText(bucket, { exact: true }).locator('../..')
    await expect(header.getByText(expected, { exact: true })).toBeVisible()
  }
  await slices.scrollIntoViewIfNeeded()
  const slicesImage = testInfo.outputPath('slices-fallback-preferred-and-zero.png')
  await slices.screenshot({ path: slicesImage })
  await testInfo.attach('Slice fallback and preferred measurements', { path: slicesImage, contentType: 'image/png' })
  await page.screenshot({ path: testInfo.outputPath('deep-dive-workspace.png') })
  fs.writeFileSync(testInfo.outputPath('browser-observations.json'), JSON.stringify({ route: page.url(), diffRequests, pageErrors, failedApiResponses, writes, observed: { missing: await missing.innerText(), measuredZero: await zero.innerText(), slices: await slices.innerText() } }, null, 2))
  expect(pageErrors).toEqual([])
  expect(failedApiResponses).toEqual([])
  expect(writes).toEqual([])
})
