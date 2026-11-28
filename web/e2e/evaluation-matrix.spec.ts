import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/evaluation-matrix-v1/tests')
const conversationId = '11111111-1111-4111-8111-111111111111'
const missingConversationId = '22222222-2222-4222-8222-222222222222'
const runAId = '33333333-3333-4333-8333-333333333333'
const runBId = '44444444-4444-4444-8444-444444444444'
const sampleId = (index: number) => `55555555-5555-4555-8555-${String(index).padStart(12, '0')}`
const metricKeys = ['faithfulness', 'response_relevancy', 'context_precision']
const scores = [
  [0.96, 0.94, 0.91],
  [0.91, 0.93, 0.88],
  [0.88, 0.92, 0.87],
  [0.89, 0.9, 0.83],
  [0.42, 0.78, 0.63],
  [0.86, 0.89, 0.81],
  [0.93, 0.95, 0.9],
  [0.78, 0.84, 0.76],
]
const question = '只增加代码生成量，就能达到高级工程师要求吗？'
const questions = [
  '系统架构设计能力包含哪些方面？',
  '初级与高级工程师的架构职责有什么区别？',
  '知识资产化的主要工作是什么？',
  '代码审核需要关注哪些问题？',
  question,
  '如何提升团队的交付质量？',
  '技术债务应该怎样识别和治理？',
  '团队知识库与个人经验有什么关系？',
]
async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}
async function fixture(page: Page, options: { empty?: boolean; theme?: 'light' | 'dark' } = {}) {
  await page.setViewportSize({ width: 1600, height: 1000 })
  await installCommonApiMocks(page, { uploaded: false })
  await page.addInitScript((theme) => {
    localStorage.setItem('theme', theme)
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.setItem('mimirq.themeColor', '#20262e')
  }, options.theme || 'light')
  const runs = [runAId, runBId].map((id, i) => ({
    id,
    conversation_id: conversationId,
    status: 'completed',
    metrics: metricKeys,
    params: { max_turns: 20, skip_empty_contexts: true },
    summary: { faithfulness: 0.83, response_relevancy: 0.89, context_precision: 0.82, items: 8 },
    error_message: null,
    created_at: `2026-10-25T${i ? '09' : '10'}:42:00Z`,
    started_at: '2026-10-25T10:42:00Z',
    finished_at: '2026-10-25T10:42:22Z',
  }))
  const items = scores.map((values, i) => ({
    id: sampleId(i + 1),
    run_id: runAId,
    turn_index: i + 1,
    user_message_id: null,
    assistant_message_id: null,
    user_input: questions[i],
    response: i === 4 ? '高级工程师主要以代码生成量与自动化比例作为衡量标准。' : `回答 ${i + 1}`,
    retrieved_contexts: [`引用 ${i + 1}：能够主导建立跨模块的系统架构规范与复用标准。`],
    citations: [{ content: `引用 ${i + 1}`, document_id: 'source-doc', document_name: '工程能力标准' }],
    scores: Object.fromEntries(metricKeys.map((key, j) => [key, values[j]])),
    created_at: '2026-10-25T10:42:22Z',
  }))
  const state = {
    failStart: false,
    failDetail: false,
    posts: [] as Record<string, unknown>[],
    writes: [] as string[],
    errors: [] as string[],
  }
  page.on('pageerror', (error) => state.errors.push(error.message))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const p = url.pathname
    if (p === '/api/v1/chat/conversations')
      return json(route, {
        total: 2,
        returned: 2,
        has_more: false,
        next_skip: null,
        items: [
          {
            id: conversationId,
            title: '工程能力问答',
            message_count: 16,
            created_at: '2026-10-25T09:00:00Z',
            updated_at: '2026-10-25T09:00:00Z',
          },
          {
            id: missingConversationId,
            title: '缺少引用的对话',
            message_count: 2,
            created_at: '2026-10-24T09:00:00Z',
            updated_at: '2026-10-24T09:00:00Z',
          },
        ],
      })
    if (p.endsWith('/messages'))
      return json(route, {
        conversation_id: p.split('/').at(-2),
        returned: 1,
        has_more: false,
        messages: [
          {
            id: 'assistant',
            role: 'assistant',
            content: '原始回答',
            created_at: '2026-10-25T09:00:00Z',
            citations: p.includes(missingConversationId) ? [] : [{ content: '原始证据' }],
          },
        ],
      })
    if (p.endsWith('/conversation-readiness'))
      return json(route, {
        total: 2,
        items: [
          {
            conversation_id: conversationId,
            assistant_turns: 8,
            evaluable_turns: 8,
            citations_count: 8,
            is_evaluable: true,
          },
          {
            conversation_id: missingConversationId,
            assistant_turns: 1,
            evaluable_turns: 0,
            citations_count: 0,
            is_evaluable: false,
          },
        ],
      })
    if (p === '/api/v1/evaluations/ragas/runs' && request.method() === 'POST') {
      const payload = request.postDataJSON()
      state.posts.push(payload)
      return json(
        route,
        state.failStart
          ? { detail: '评测服务暂不可用' }
          : { ...runs[0], id: '66666666-6666-4666-8666-666666666666', status: 'pending' },
        state.failStart ? 503 : 200,
      )
    }
    if (p === '/api/v1/evaluations/ragas/runs') {
      const visibleRuns = options.empty || url.searchParams.get('conversation_id') === missingConversationId ? [] : runs
      return json(route, { total: visibleRuns.length, items: visibleRuns })
    }
    if (p.startsWith('/api/v1/evaluations/ragas/runs/')) {
      const id = p.split('/').at(-1)!
      if (state.failDetail) return json(route, { detail: '无法读取运行结果' }, 503)
      return json(route, {
        run: { ...(runs.find((run) => run.id === id) || runs[0]), id },
        items:
          id === runBId
            ? [
                {
                  ...items[0],
                  id: sampleId(9),
                  run_id: id,
                  user_input: '另一轮运行的问题',
                  response: '另一轮的回答',
                  retrieved_contexts: ['另一轮的证据'],
                },
              ]
            : items,
      })
    }
    if ((p === '/api/v1/datasets' || p === '/api/v1/datasets/') && request.method() === 'GET')
      return json(route, {
        total: 1,
        items: [{ id: 'dataset-a', name: '工程文档', document_count: 1, created_at: '2026-10-25T09:00:00Z' }],
      })
    if (p.startsWith('/api/v1/evaluations/ragas/regression/')) {
      if (request.method() !== 'GET') state.writes.push(p)
      return json(route, { total: 0, items: [] })
    }
    if (p.startsWith('/api/v1/observability/queryset-health/'))
      return json(route, {
        total: 0,
        items: [],
        timeseries: {
          ts_ms: [],
          hit_at_k: [],
          mrr: [],
          ndcg_at_k: [],
          p95_latency_ms: [],
          miss_rate: [],
          weak_hit_rate: [],
        },
      })
    return route.fallback()
  })
  return state
}
async function open(page: Page, query = '') {
  await page.goto(`/evaluations${query}`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-evaluation-matrix]')).toBeVisible({ timeout: 60000 })
}
test('C reviews actual per-item scores, filters low samples and isolates evidence across runs', async ({ page }) => {
  const state = await fixture(page)
  await open(page)
  const matrix = page.getByRole('table', { name: '逐轮评分矩阵' })
  await expect(matrix.getByRole('button', { name: question, exact: true })).toBeVisible()
  await matrix.getByRole('button', { name: question, exact: true }).click()
  await expect(page.getByRole('region', { name: '样本阅读区' })).toContainText('引用 5：')
  fs.mkdirSync(evidence, { recursive: true })
  await page.screenshot({ path: `${evidence}/desktop-c.png` })
  await page.getByRole('button', { name: /低分.*2/ }).click()
  await expect(matrix.locator('tbody tr[data-sample-row]')).toHaveCount(2)
  await page.getByRole('searchbox', { name: '搜索评测问题' }).fill('不存在的内容')
  await expect(page.getByText('没有匹配的样本', { exact: true })).toBeVisible()
  await page.getByRole('searchbox', { name: '搜索评测问题' }).fill('')
  await page.getByRole('button', { name: /运行记录/ }).click()
  await page
    .getByRole('dialog', { name: '运行记录' })
    .getByRole('button', { name: new RegExp(runBId.slice(0, 8)) })
    .click()
  await expect(page.getByRole('region', { name: '样本阅读区' })).toContainText('另一轮的证据')
  await expect(page.getByRole('region', { name: '样本阅读区' })).not.toContainText('引用 5：')
  await page.screenshot({ path: `${evidence}/run-scope.png` })
  expect(state.posts).toEqual([])
  expect(state.writes).toEqual([])
  expect(state.errors).toEqual([])
})
test('parameters survive failed start, and both additional evaluation tabs remain functional', async ({ page }) => {
  const state = await fixture(page)
  await open(page)
  await page.getByRole('button', { name: '评测参数', exact: true }).click()
  await page.getByRole('spinbutton', { name: '最近轮次' }).fill('35')
  await page.getByRole('button', { name: '完成', exact: true }).click()
  state.failStart = true
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  await expect.poll(() => state.posts.length).toBe(1)
  expect(state.posts[0]).toMatchObject({ conversation_id: conversationId, max_turns: 35 })
  await expect(page.getByText('评测服务暂不可用', { exact: false }).first()).toBeVisible()
  await page.getByRole('tab', { name: 'Golden 评测集', exact: true }).click()
  await expect(page).toHaveURL(/tab=regression/)
  await expect(page.getByText('Golden 评测配置', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Golden 评测配置', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Golden 评测参数' })).toBeVisible()
  await page.getByRole('dialog', { name: 'Golden 评测参数' }).getByRole('button', { name: '完成', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Golden 评测参数' })).toHaveCount(0)
  await expect(page.locator('[data-state="closed"].fixed.inset-0')).toHaveCount(0)
  await page.screenshot({ path: `${evidence}/golden.png` })
  await page.getByRole('tab', { name: '检索集健康度', exact: true }).click()
  await expect(page).toHaveURL(/tab=queryset_health/)
  await expect(page.getByText('差异对比', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${evidence}/health.png` })
  await page.getByRole('tab', { name: '对话评测', exact: true }).click()
  await page.getByRole('button', { name: '评测参数', exact: true }).click()
  await expect(page.getByRole('spinbutton', { name: '最近轮次' })).toHaveValue('35')
  await page.getByRole('button', { name: '完成', exact: true }).click()
  await page
    .getByRole('button', { name: /选择对话|工程能力问答/ })
    .first()
    .click()
  await page
    .getByRole('dialog', { name: '选择对话' })
    .getByRole('button', { name: /缺少引用的对话/ })
    .click()
  await expect(page.getByRole('button', { name: '开始评测', exact: true })).toBeDisabled()
  await expect(page.getByText('这条对话没有引用上下文', { exact: true })).toBeVisible()
  expect(state.writes).toEqual([])
})
test('Golden submits the same cases in both answer modes and identifies the pinned ontology version', async ({
  page,
}, testInfo) => {
  const datasetId = 'dataset-a'
  const caseId = sampleId(1)
  const stamp = '2026-10-25T10:42:22Z'
  const sample = {
    id: caseId,
    tenant_id: 'tenant-1',
    dataset_id: datasetId,
    document_ids: [],
    question,
    expected_answer: '高级工程师还需达到系统设计与交付质量要求。',
    reference_sources: [],
    tags: ['golden'],
    reasoning_hops: [],
    evidence_chain: [],
    extra: {},
    created_by: null,
    created_at: stamp,
    updated_at: stamp,
  }
  const baseRun = {
    id: runAId,
    tenant_id: 'tenant-1',
    account_id: null,
    dataset_id: datasetId,
    status: 'completed',
    metrics: metricKeys,
    params: {},
    summary: { items: 1 },
    error_message: null,
    created_at: stamp,
    started_at: stamp,
    finished_at: stamp,
  }
  const runs = [baseRun]
  const posts: unknown[] = []
  await fixture(page)
  await page.route('**/api/v1/evaluations/ragas/regression/cases?*', (route) =>
    json(route, { total: 1, items: [sample] }),
  )
  await page.route(/\/api\/v1\/evaluations\/ragas\/regression\/runs(?:\?.*)?$/, (route) => {
    if (route.request().method() === 'GET') return json(route, { total: runs.length, items: runs })
    const payload = route.request().postDataJSON()
    posts.push(payload)
    const ontology = payload.answer_mode === 'ontology'
    const run = {
      ...baseRun,
      id: ontology ? runBId : '11111111-1111-4111-8111-333333333333',
      params: ontology
        ? { answer_mode: 'ontology', ontology_version_id: 'pinned-release-7', ontology_version_number: 7 }
        : { answer_mode: 'rag' },
    }
    runs.unshift(run)
    return json(route, run)
  })
  await page.route(/\/api\/v1\/evaluations\/ragas\/regression\/runs\/[^/?]+\?/, (route) => {
    const runId = new URL(route.request().url()).pathname.split('/').at(-1)
    const run = runs.find(({ id }) => id === runId)
    return run === undefined
      ? json(route, { detail: '运行不存在' }, 404)
      : json(route, {
          run,
          items: [
            {
              id: sampleId(2),
              run_id: run.id,
              case_id: sample.id,
              question: sample.question,
              response: run.id === runBId ? '证据不足，无法确认。' : sample.expected_answer,
              retrieved_contexts: null,
              citations: [],
              scores: {},
              meta: {},
              created_at: stamp,
            },
          ],
        })
  })

  await page.goto(`/evaluations?tab=regression&dataset_id=${datasetId}`, { waitUntil: 'domcontentloaded' })
  const configButton = page.getByRole('button', { name: 'Golden 评测配置' })
  const dialog = page.getByRole('dialog', { name: 'Golden 评测参数' })
  const mode = dialog.getByRole('combobox', { name: '问答模式' })
  await configButton.click()
  await expect(mode).toHaveText('普通 RAG')
  await dialog.getByRole('button', { name: '完成' }).click()
  await expect(page.getByRole('button', { name: /运行 33333333.*普通 RAG/ })).toBeVisible()

  const runGolden = page.getByRole('button', { name: '运行 Golden', exact: true })
  await runGolden.click()
  await expect(page.getByRole('button', { name: /运行 11111111.*普通 RAG/ })).toHaveAttribute('aria-pressed', 'true')

  await configButton.click()
  await mode.click()
  await page.getByRole('option', { name: '本体问答' }).click()
  await dialog.getByRole('button', { name: '完成' }).click()
  await runGolden.click()
  await expect(page.getByRole('button', { name: /运行 44444444.*本体问答 · v7/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(page.getByText('本体问答 · v7', { exact: true })).toHaveCount(2)
  await expect(page.getByText('证据不足，无法确认。')).toBeVisible()
  expect(posts).toEqual([
    expect.objectContaining({
      dataset_id: datasetId,
      case_ids: [caseId],
      answer_mode: 'rag',
      skip_empty_contexts: false,
    }),
    expect.objectContaining({
      dataset_id: datasetId,
      case_ids: [caseId],
      answer_mode: 'ontology',
      skip_empty_contexts: false,
    }),
  ])
  await page.screenshot({ path: testInfo.outputPath('golden-ontology-desktop.png') })

  await page.setViewportSize({ width: 390, height: 844 })
  await configButton.click()
  await expect(mode).toHaveText('本体问答')
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('golden-ontology-narrow.png') })
})
test('narrow screen can read a selected sample and return to matrix without horizontal page overflow', async ({
  page,
}) => {
  await fixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await open(page)
  await page.getByRole('table', { name: '逐轮评分矩阵' }).getByRole('button', { name: question, exact: true }).click()
  await expect(page.getByRole('region', { name: '样本阅读区' })).toBeVisible()
  await page.getByRole('button', { name: '返回样本矩阵', exact: true }).click()
  await expect(page.getByRole('table', { name: '逐轮评分矩阵' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
  fs.mkdirSync(evidence, { recursive: true })
  await page.screenshot({ path: `${evidence}/mobile-c.png` })
})
test('light and dark appearance retain the matrix and reader at double pixel density', async ({ browser }) => {
  const backgrounds: string[] = []
  for (const mode of ['light', 'dark'] as const) {
    const context = await browser.newContext({
      viewport: { width: 1600, height: 1000 },
      deviceScaleFactor: 2,
      colorScheme: mode,
    })
    try {
      const page = await context.newPage()
      await fixture(page, { theme: mode })
      await open(page)
      await expect(page.locator('html')).toHaveClass(new RegExp(mode))
      await page
        .getByRole('table', { name: '逐轮评分矩阵' })
        .getByRole('button', { name: question, exact: true })
        .click()
      await expect(page.locator(`[data-evaluation-reader-item="${sampleId(5)}"]`)).toHaveCSS('opacity', '1')
      backgrounds.push(
        await page.locator('[data-evaluation-page]').evaluate((element) => getComputedStyle(element).backgroundColor),
      )
      await page.screenshot({ path: `${evidence}/${mode}-c-2x.png` })
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
    } finally {
      await context.close()
    }
  }
  expect(backgrounds[0]).not.toBe(backgrounds[1])
})
