import path from 'node:path'

import { expect, test, type Page, type Route } from '@playwright/test'

import {
  fulfillChatStream,
  installCommonApiMocks,
  installDeterministicRandom,
  type EnterpriseTelemetryMockState,
} from './enterprise-quality-telemetry.helpers'

async function fulfillJson(route: Route, payload: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })
}

async function openAppearance(page: Page) {
  await page.getByRole('button', { name: '工作空间与外观设置', exact: true }).click()
  await page.getByRole('button', { name: '界面外观', exact: true }).click()
}

async function documentHorizontalOverflow(page: Page) {
  return page.evaluate(() => {
    const root = document.documentElement
    const body = document.body
    return Math.max(root.scrollWidth, body.scrollWidth) - window.innerWidth
  })
}

async function scrollContainerMetrics(page: Page, selector: string) {
  return page.locator(selector).evaluate((element) => {
    const target = element as HTMLElement
    const before = target.scrollTop
    target.scrollTop = target.scrollHeight
    return {
      clientHeight: target.clientHeight,
      scrollHeight: target.scrollHeight,
      scrollTop: target.scrollTop,
      scrolled: target.scrollTop > before,
      overflowY: window.getComputedStyle(target).overflowY,
    }
  })
}

async function captureGuideScreenshot(page: Page, filename: string) {
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-delay: 0s !important;
        animation-duration: 0s !important;
        caret-color: transparent !important;
        transition-delay: 0s !important;
        transition-duration: 0s !important;
      }
    `,
  })
  await page.evaluate(async () => {
    await document.fonts.ready
    document.querySelectorAll('nextjs-portal').forEach((portal) => portal.remove())
  })
  await page.screenshot({
    path: path.join(
      process.env.CAPTURE_DOCS_SCREENSHOTS_DIR || path.resolve(__dirname, '../../docs/images/screenshots'),
      filename,
    ),
    fullPage: false,
  })
}

async function expectReadableManagementHeaders(
  page: Page,
  surfaces: ReadonlyArray<{ route: string; heading: string }>,
) {
  for (const surface of surfaces) {
    await page.goto(surface.route, { waitUntil: 'domcontentloaded' })

    const heading = page.getByRole('heading', { name: surface.heading, exact: true }).first()
    await expect(heading, `${surface.route} heading`).toBeVisible({ timeout: 60_000 })
    await expect(heading.locator('xpath=ancestor::header[1]'), `${surface.route} header shell`).toBeVisible()

    expect(await documentHorizontalOverflow(page), `${surface.route} page overflow`).toBeLessThanOrEqual(1)
  }
}

const LEGACY_DARK_SURFACE_CLASS =
  /^(?:text-slate-(?:400|500|600|700|800|900|950)|border-slate-(?:100|200|300)(?:\/\d+)?|bg-(?:white|slate-(?:50|100|200))(?:\/\d+)?)$/

async function visibleLegacyDarkSurfaceClasses(page: Page) {
  return page.evaluate((patternSource) => {
    const pattern = new RegExp(patternSource)
    const matches = new Set<string>()

    for (const element of document.querySelectorAll('body *')) {
      const rect = element.getBoundingClientRect()
      const style = window.getComputedStyle(element)
      const isVisible =
        rect.width > 2 &&
        rect.height > 2 &&
        rect.bottom > 0 &&
        rect.top < window.innerHeight &&
        rect.right > 0 &&
        rect.left < window.innerWidth &&
        style.display !== 'none' &&
        style.visibility !== 'hidden'
      if (!isVisible) continue

      for (const className of element.classList) {
        if (pattern.test(className)) matches.add(className)
      }
    }

    return Array.from(matches).sort()
  }, LEGACY_DARK_SURFACE_CLASS.source)
}

async function textAndSemanticForeground(page: Page, selector: string) {
  return page
    .locator(selector)
    .first()
    .evaluate((element) => {
      const probe = document.createElement('span')
      probe.style.color = 'hsl(var(--foreground))'
      document.body.appendChild(probe)
      const result = {
        actual: window.getComputedStyle(element).color,
        expected: window.getComputedStyle(probe).color,
      }
      probe.remove()
      return result
    })
}

async function installManagementSurfaceMocks(page: Page) {
  const state: EnterpriseTelemetryMockState = { uploaded: false, parsingDocuments: [] }

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    const method = request.method()

    if (method === 'GET') {
      if (pathname.includes('/kg/ontology/predicates')) {
        return fulfillJson(route, { predicates: [] })
      }
      if (pathname.includes('/usage/tenant/quotas')) {
        return fulfillJson(route, { datasets: [] })
      }
      return fulfillJson(route, { items: [], total: 0 })
    }

    if (method === 'DELETE') {
      await route.fulfill({ status: 204, body: '' })
      return
    }

    return fulfillJson(route, { success: true })
  })

  await installDeterministicRandom(page)
  await installCommonApiMocks(page, state)

  await page.route('**/api/v1/rbac/me', (route) =>
    fulfillJson(route, {
      tenant_id: '00000000-0000-0000-0000-000000000000',
      account_id: 'demo',
      role: 'owner',
      permissions: ['settings.read', 'settings.write', 'observability.read', 'usage.read', 'audit.read'],
      navigation_user_visible_modules: [],
      is_active: true,
      is_current: true,
    }),
  )
  await page.route('**/api/v1/settings', (route) =>
    fulfillJson(route, {
      feature_flags: { kg_enabled: false },
      llm: { api_key: '', api_base: '', model: '', temperature: 0.7, timeout: 60 },
      embedding: { provider: 'openai_compatible', model: '', api_key: '', api_base: '' },
      rag: { retrieval_top_k: 5, similarity_threshold: 0.7 },
      navigation: { user_visible_modules: [] },
    }),
  )

  await page.route('**/api/v1/datasets**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          id: 'ds-smoke',
          name: 'Smoke Dataset',
          description: 'management smoke fixture',
          created_at: '2026-04-09T00:00:00Z',
          updated_at: '2026-04-09T00:00:00Z',
        },
      ],
      total: 1,
    })
  })

  await page.route('**/api/v1/datasets/ds-smoke', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      id: 'ds-smoke',
      name: 'Smoke Dataset',
      description: 'management smoke fixture',
      created_at: '2026-04-09T00:00:00Z',
      updated_at: '2026-04-09T00:00:00Z',
    })
  })

  await page.route('**/api/v1/dataset-categories/**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, { items: [] })
  })

  await page.route('**/api/v1/reports/datasets/ds-smoke**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      dataset_id: 'ds-smoke',
      pipeline_versions: [{ pipeline_hash: 'abc12345', created_at: '2026-04-09T00:00:00Z' }],
      connectors: [],
      profile: {
        total_documents: 3,
        total_size_bytes: 2048,
      },
      compliance: {
        quarantined_documents: 0,
        failed_documents: 0,
      },
      governance_metrics: {
        category_coverage_pct: 1,
      },
      governance_audit: {
        heading_ratio_pct_histogram: [],
      },
      folder_tree: {
        name: 'root',
        children: [],
      },
    })
  })

  const evaluationConversationId = '50665a37-631c-4916-86b7-1fe300ebdc2f'
  await page.route('**/api/v1/chat/conversations**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          id: evaluationConversationId,
          title: 'Smoke Conversation',
          message_count: 3,
          created_at: '2026-04-09T00:00:00Z',
          updated_at: '2026-04-09T00:00:00Z',
        },
      ],
      total: 1,
      returned: 1,
      has_more: false,
      next_skip: null,
    })
  })

  const evaluationRun = {
    id: 'fd13b91e-3ca8-42d3-8c40-e9742573056e',
    conversation_id: evaluationConversationId,
    status: 'completed',
    metrics: ['faithfulness', 'response_relevancy'],
    params: {},
    summary: { faithfulness: 0.92 },
    error_message: null,
    created_at: '2026-04-09T00:00:00Z',
    started_at: '2026-04-09T00:00:00Z',
    finished_at: '2026-04-09T00:01:00Z',
  }
  await page.route('**/api/v1/evaluations/ragas/runs**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, { items: [evaluationRun], total: 1 })
  })

  await page.route('**/api/v1/evaluations/ragas/conversation-readiness', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    return fulfillJson(route, {
      total: 1,
      items: [
        {
          conversation_id: evaluationConversationId,
          assistant_turns: 1,
          evaluable_turns: 1,
          is_evaluable: true,
          citations_count: 2,
        },
      ],
    })
  })

  await page.route(`**/api/v1/evaluations/ragas/runs/${evaluationRun.id}**`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, { run: evaluationRun, items: [] })
  })

  await page.route('**/api/v1/usage/chat/tokens/summary**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      window_start: '2026-04-08T00:00:00Z',
      window_end: '2026-04-09T00:00:00Z',
      total_assistant_messages: 4,
      total_assistant_tokens: 128,
      by_dataset: [
        {
          dataset_id: 'ds-smoke',
          assistant_messages: 4,
          assistant_tokens: 128,
        },
      ],
    })
  })

  await page.route('**/api/v1/usage/chat/cost/summary**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      window_start: '2026-04-08T00:00:00Z',
      window_end: '2026-04-09T00:00:00Z',
      total_llm_total_tokens: 256,
      total_llm_prompt_tokens: 160,
      total_llm_completion_tokens: 96,
      total_embedding_query_tokens: 48,
      total_embedding_query_chars: 600,
      total_retrieval_elapsed_sec: 2.4,
      total_rerank_elapsed_sec: 0.8,
      total_assistant_messages: 4,
      by_dataset: [
        {
          dataset_id: 'ds-smoke',
          assistant_messages: 4,
          llm_total_tokens: 256,
          llm_prompt_tokens: 160,
          llm_completion_tokens: 96,
          embedding_query_tokens: 48,
          embedding_query_chars: 600,
          retrieval_elapsed_sec: 2.4,
          rerank_elapsed_sec: 0.8,
        },
      ],
    })
  })

  await page.route('**/api/v1/usage/chat/tokens/quota**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      enabled: true,
      exceeded: false,
      mode: 'block',
      limit: 1000,
      used: 128,
      remaining: 872,
      window_hours: 24,
      window_start: '2026-04-08T00:00:00Z',
      window_end: '2026-04-09T00:00:00Z',
    })
  })

  await page.route('**/api/v1/audit/logs**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          id: '0847a411-1b8b-4031-ba0f-eeb3000d0081',
          tenant_id: '00000000-0000-0000-0000-000000000000',
          action: 'smoke.audit.view',
          actor_id: 'demo',
          resource_type: 'dataset',
          resource_id: 'ds-smoke',
          created_at: '2026-04-09T00:00:00Z',
          request_id: 'req-smoke',
          ip: null,
          user_agent: null,
          details: {},
        },
      ],
      total: 1,
    })
  })

  await page.route('**/api/v1/audit/access-graph/summary**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      group_count: 4,
      group_member_count: 9,
      dataset_count: 3,
      dataset_permission_counts: {
        all_team_members: 1,
        partial_members: 1,
        only_me: 1,
      },
      document_count: 12,
      document_access_mode_counts: {
        inherit: 8,
        partial_members: 2,
        only_me: 1,
        all_team_members: 1,
        unknown: 0,
      },
      dataset_member_allowlist_count: 2,
      dataset_group_allowlist_count: 1,
      document_member_allowlist_count: 3,
      document_group_allowlist_count: 2,
    })
  })

  await page.route('**/api/v1/rbac/members**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          id: 'member-owner',
          tenant_id: 'tenant-smoke',
          user_id: 'avery.long.member.identifier.for.viewport.regression@example.com',
          role: 'owner',
          is_current: true,
          created_at: '2026-04-09T00:00:00Z',
          updated_at: '2026-04-09T00:00:00Z',
        },
        {
          id: 'member-auditor',
          tenant_id: 'tenant-smoke',
          user_id: 'audit.operator@example.com',
          role: 'auditor',
          is_current: false,
          created_at: '2026-04-09T00:00:00Z',
          updated_at: '2026-04-09T00:00:00Z',
        },
      ],
      total: 2,
    })
  })

  await page.route('**/api/v1/evidence/suites/suite-smoke/items**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          id: 'item-smoke',
          suite_id: 'suite-smoke',
          query: 'How does the smoke evidence item behave at laptop widths?',
          expected_answer: 'It should stay readable and selectable.',
          notes: 'Smoke evidence item note',
          status: 'reviewed',
          tags: ['smoke', 'viewport'],
          reference_sources: [
            {
              document_id: 'doc-smoke',
              chunk_id: 'chunk-smoke',
              label: 'Smoke reference label',
              quote: 'Smoke reference quote',
              page_number: 3,
              chunk_index: 1,
            },
          ],
          source_metadata: {
            source: 'smoke',
          },
          updated_at: '2026-04-09T00:00:00Z',
        },
      ],
      total: 1,
    })
  })

  await page.route('**/api/v1/evidence/suites**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    if (new URL(route.request().url()).pathname !== '/api/v1/evidence/suites') {
      return route.fallback()
    }
    return fulfillJson(route, {
      items: [
        {
          id: 'suite-smoke',
          dataset_id: 'ds-smoke',
          name: 'Smoke Evidence Suite',
          description: 'Evidence smoke fixture',
          tags: ['smoke', 'evidence'],
          item_counts: {
            total: 1,
            draft: 0,
            reviewed: 1,
            approved: 0,
            archived: 0,
          },
        },
      ],
      total: 1,
    })
  })
}

test.describe('management surfaces smoke', () => {
  test.beforeEach(async ({ page }) => {
    await installManagementSurfaceMocks(page)
  })

  test('loads prompts page with the managed prompt shell', async ({ page }) => {
    await page.goto('/prompts')
    await expect(page.getByRole('heading', { name: '提示词', exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('header').getByRole('button', { name: '创建模板', exact: true })).toBeVisible()
  })

  test('loads reports page with mocked dataset data', async ({ page }) => {
    await page.goto('/reports')
    await expect(page.getByRole('heading', { name: '数据报告' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('combobox', { name: '数据集' })).toContainText('Smoke Dataset')
  })

  test('loads evaluations page with conversation and run data', async ({ page }) => {
    await page.goto('/evaluations')
    await expect(page.getByRole('heading', { name: 'RAG 评测', exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('tab', { name: '对话评测', exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Golden 评测集', exact: true })).toBeVisible()
    const evaluation = page.getByRole('tabpanel', { name: '对话评测', exact: true })
    await expect(evaluation.getByRole('button', { name: 'Smoke Conversation', exact: true })).toBeVisible()
    await expect(evaluation.getByRole('button', { name: '开始评测', exact: true })).toBeEnabled()
    await evaluation.getByRole('button', { name: '运行记录 1', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '运行记录', exact: true })).toContainText('已完成')
  })

  test('renders the datasets management header contract', async ({ page }) => {
    await page.goto('/datasets')
    const toolbar = page.getByTestId('datasets-page-toolbar')
    await expect(toolbar).toBeVisible({ timeout: 60_000 })
    await expect(toolbar.getByRole('heading', { name: '数据集' })).toBeVisible()
    await expect(page.getByRole('button', { name: '刷新数据集', exact: true })).toBeVisible()
    await expect(toolbar.getByRole('button', { name: '新建数据集' })).toBeVisible()
    expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
  })

  test('renders the knowledge workbench header contract', async ({ page }) => {
    await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
    await page.goto('/knowledge')
    const toolbar = page.getByTestId('knowledge-page-toolbar')
    await expect(toolbar).toBeVisible({ timeout: 60_000 })
    await expect(toolbar.getByRole('heading', { name: '知识库', exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: /^文档/ })).toBeVisible()
    await expect(page.getByRole('tab', { name: '检索测试', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '更多筛选', exact: true })).toBeVisible()
    await expect(toolbar.getByRole('button', { name: '导入文档', exact: true })).toBeVisible()
    expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
  })

  test('uses readable semantic foreground titles on custom management headers', async ({ page }) => {
    for (const surface of [
      { route: '/datasets', heading: '数据集' },
      { route: '/knowledge', heading: '知识库' },
      { route: '/evaluations', heading: 'RAG 评测' },
    ] as const) {
      await page.goto(surface.route, { waitUntil: 'domcontentloaded' })
      const heading = page.getByRole('heading', { name: surface.heading }).first()
      await expect(heading, `${surface.route} heading`).toBeVisible({ timeout: 60_000 })

      const colors = await textAndSemanticForeground(page, `h1:has-text("${surface.heading}")`)
      expect(colors.actual, `${surface.route} title should use semantic foreground ink`).toBe(colors.expected)
      expect(colors.actual, `${surface.route} title should stay opaque`).not.toBe('rgba(0, 0, 0, 0)')
    }
  })

  test('keeps quarantine and feedback headers readable at laptop width', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })

    for (const surface of [
      {
        route: '/knowledge/quarantine',
        heading: '隔离队列',
        action: '同步隔离队列',
      },
      {
        route: '/knowledge/feedback',
        heading: '反馈质检',
        action: '反哺候选',
      },
    ]) {
      await page.goto(surface.route)
      const heading = page.getByRole('heading', { name: surface.heading }).first()
      await expect(heading).toBeVisible({ timeout: 60_000 })
      const header = heading.locator('xpath=ancestor::header[1]')
      await expect(header.getByRole('button', { name: surface.action, exact: true })).toBeVisible()
      expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
    }
  })

  test('keeps core management headers readable without horizontal overflow', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1440, height: 900 })

    await expectReadableManagementHeaders(page, [
      { route: '/evaluations', heading: 'RAG 评测' },
      { route: '/prompts', heading: '提示词' },
      { route: '/diagnostics', heading: '诊断' },
      { route: '/usage', heading: '用量／配额' },
    ])

    await page.setViewportSize({ width: 1280, height: 768 })
    await page.goto('/evaluations', { waitUntil: 'domcontentloaded' })
    const evaluationHeading = page.getByRole('heading', { name: 'RAG 评测', exact: true })
    await expect(evaluationHeading).toBeVisible({ timeout: 15_000 })
    const evaluationHero = evaluationHeading.locator('xpath=ancestor::header[1]')
    const evaluationGeometry = await evaluationHero.evaluate((element) => ({
      height: element.getBoundingClientRect().height,
      pageOverflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth,
    }))
    expect(evaluationGeometry.height).toBeGreaterThan(0)
    expect(evaluationGeometry.pageOverflow).toBeLessThanOrEqual(1)
  })

  test('keeps settings and audit headers readable without horizontal overflow', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1440, height: 900 })

    await expectReadableManagementHeaders(page, [
      { route: '/audit', heading: '审计日志' },
      { route: '/settings/rbac', heading: '成员权限' },
      { route: '/settings/groups', heading: '组管理' },
      { route: '/settings', heading: '系统设置' },
    ])
  })

  test('uses semantic surfaces after switching to dark mode', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.goto('/evaluations', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'RAG 评测', exact: true })).toBeVisible({ timeout: 60_000 })
    await openAppearance(page)
    await page.getByRole('radio', { name: '深色', exact: true }).press('Space')
    await page.keyboard.press('Escape')
    await expect(page.locator('html')).toHaveClass(/dark/)

    for (const surface of [
      { route: '/evaluations', heading: 'RAG 评测' },
      { route: '/evaluations/ablations', heading: '检索调参对比' },
      { route: '/reports', heading: '数据报告' },
      { route: '/datasets', heading: '数据集' },
    ]) {
      await page.goto(surface.route, { waitUntil: 'domcontentloaded' })
      const heading = page.getByRole('heading', { name: surface.heading }).first()
      await expect(heading).toBeVisible({ timeout: 60_000 })

      const legacyClasses = await visibleLegacyDarkSurfaceClasses(page)
      expect(legacyClasses, `${surface.route} still renders light-only utility classes in dark mode`).toEqual([])

      const colors = await textAndSemanticForeground(page, `h1:has-text("${surface.heading}")`)
      expect(colors.actual).toBe(colors.expected)
    }
  })

  test('keeps appearance surfaces and action colors in sync', async ({ page }) => {
    test.setTimeout(180_000)
    await page.goto('/datasets', { waitUntil: 'domcontentloaded' })
    const header = page.getByTestId('datasets-page-toolbar')
    const create = header.getByRole('button', { name: '新建数据集', exact: true })
    await expect(create).toBeVisible({ timeout: 60_000 })

    const colors = async () =>
      page.evaluate(() => {
        const probe = document.createElement('span')
        document.body.appendChild(probe)
        const value = (token: string) => {
          probe.style.backgroundColor = `hsl(var(${token}))`
          return getComputedStyle(probe).backgroundColor
        }
        const result = {
          background: value('--background'),
          sidebar: value('--sidebar-background'),
          primary: value('--primary'),
          accent: value('--accent'),
          accentForeground: value('--accent-foreground'),
        }
        probe.remove()
        return result
      })

    for (const preset of [
      { key: 'ocean', label: '暖石默认' },
      { key: 'neutral', label: '纯白' },
      { key: 'classic', label: '浅灰' },
      { key: 'earth', label: '米白' },
    ]) {
      await openAppearance(page)
      const radio = page.getByRole('radio', { name: preset.label, exact: true })
      await expect(radio).toBeVisible()
      await radio.press('Space')
      await page.keyboard.press('Escape')
      await expect(page.locator('html')).toHaveAttribute('data-surface-theme', preset.key)
      const expected = await colors()
      await expect(page.getByRole('navigation', { name: '主导航', exact: true })).toHaveCSS(
        'background-color',
        expected.sidebar,
      )
      await expect(header).toHaveCSS('background-color', expected.background)
      await expect(create).toHaveCSS('background-color', expected.accent)
      await expect(create).toHaveCSS('color', expected.accentForeground)
    }

    const before = await colors()
    await openAppearance(page)
    await page.getByRole('radio', { name: '靛蓝', exact: true }).press('Space')
    await page.keyboard.press('Escape')
    await expect(page.locator('html')).toHaveAttribute('data-theme-color', '4f46e5')
    await expect(page.locator('html')).toHaveAttribute('data-surface-theme', 'earth')
    const updated = await colors()
    expect(updated.accent).not.toBe(before.accent)
    expect(updated.background).toBe(before.background)
    await expect(create).toHaveCSS('background-color', updated.accent)

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(create).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('html')).toHaveAttribute('data-surface-theme', 'earth')
    await expect(page.locator('html')).toHaveAttribute('data-theme-color', '4f46e5')
    await expect(create).toHaveCSS('background-color', updated.accent)

    await page.goto('/knowledge/ingestion', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: '入库管理', exact: true })).toBeVisible({ timeout: 60_000 })
    await page.locator('[data-ingestion-import-trigger]').click()
    const dialog = page.getByRole('dialog', { name: '导入文档', exact: true })
    await expect(dialog).toBeVisible()
    const settings = dialog.locator('[data-ingestion-context-panel]')
    await expect(settings.getByRole('combobox', { name: '目标数据集', exact: true })).toContainText('Smoke Dataset')
    await dialog.getByLabel('选择待入库文件', { exact: true }).setInputFiles({
      name: 'theme-check.docx',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('UI appearance test only'),
    })
    const submit = dialog.locator('[data-ingestion-submit]')
    await expect(submit).toBeEnabled()
    const expected = await colors()
    await expect(submit).toHaveCSS('background-color', expected.accent)
    await expect(settings.locator('input[value="upload_only"]')).toHaveCSS('accent-color', expected.accent)
  })

  test('synchronizes appearance controls between open pages', async ({ page, context }) => {
    test.setTimeout(180_000)
    await page.goto('/datasets', { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId('datasets-page-toolbar')).toBeVisible({ timeout: 60_000 })
    await openAppearance(page)
    await page.getByRole('radio', { name: '米白', exact: true }).press('Space')

    const other = await context.newPage()
    await installManagementSurfaceMocks(other)
    await other.goto('/datasets', { waitUntil: 'domcontentloaded' })
    await expect(other.getByTestId('datasets-page-toolbar')).toBeVisible({ timeout: 60_000 })
    await openAppearance(other)
    await expect(other.getByRole('radio', { name: '米白', exact: true })).toBeChecked()
    await page.getByRole('radio', { name: '纯白', exact: true }).press('Space')
    await page.getByRole('radio', { name: '靛蓝', exact: true }).press('Space')
    await expect(other.locator('html')).toHaveAttribute('data-surface-theme', 'neutral')
    await expect(other.locator('html')).toHaveAttribute('data-theme-color', '4f46e5')
    await expect(other.getByRole('radio', { name: '纯白', exact: true })).toBeChecked()
    await expect(other.getByRole('radio', { name: '靛蓝', exact: true })).toBeChecked()
    await expect(other.getByRole('radio', { name: '米白', exact: true })).not.toBeChecked()
    await other.close()
  })

  test('keeps similarity workbench readable at laptop width', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1280, height: 720 })

    await page.goto('/knowledge/similarity', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    const similarityTitle = page.getByRole('heading', {
      name: '向量相似度诊断',
      exact: true,
    })
    await expect(similarityTitle).toBeVisible({ timeout: 60_000 })
    await expect(similarityTitle).toBeInViewport({ ratio: 1 })
    expect(
      await similarityTitle.evaluate((heading) => {
        const text = document.createRange()
        text.selectNodeContents(heading)
        return text.getClientRects().length
      }),
    ).toBe(1)
    expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
  })

  test('keeps Golden workspace readable at laptop width', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1280, height: 720 })

    await page.goto('/evaluations?tab=regression', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    const goldenWorkspaceTitle = page.getByRole('tab', { name: 'Golden 评测集', exact: true })
    await expect(goldenWorkspaceTitle).toBeVisible({ timeout: 60_000 })
    await expect(goldenWorkspaceTitle).toHaveAttribute('aria-selected', 'true')
    expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)

    const runHistoryTitle = page.getByText('运行历史', { exact: true })
    const runHistoryCardHeight = await runHistoryTitle.evaluate(
      (element) => element.parentElement?.parentElement?.parentElement?.getBoundingClientRect().height ?? 0,
    )
    expect(runHistoryCardHeight).toBeGreaterThan(100)
  })

  test('keeps the ingestion import dialog scrollable with visible actions at laptop heights', async ({ page }) => {
    test.setTimeout(180_000)
    for (const viewport of [
      { width: 1024, height: 768 },
      { width: 1280, height: 720 },
      { width: 1366, height: 768 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/knowledge/ingestion', { waitUntil: 'domcontentloaded', timeout: 150_000 })
      await expect(page.getByRole('heading', { name: '入库管理', exact: true })).toBeVisible({ timeout: 60_000 })
      await expect(page.locator('[data-ingestion-operation-workspace="true"]')).toBeVisible()
      await expect(page.getByRole('navigation', { name: '文件来源' })).toHaveCount(0)
      const trigger = page.locator('[data-ingestion-import-trigger]')
      await trigger.click()
      const dialog = page.getByRole('dialog', { name: '导入文档', exact: true })
      await expect(dialog).toBeVisible()
      await dialog.locator('[data-ingestion-advanced-settings] summary').click()
      const metrics = await scrollContainerMetrics(page, '[data-ingestion-dialog-body]')
      expect(metrics.clientHeight).toBeGreaterThan(0)
      expect(metrics.overflowY).toBe('auto')
      if (metrics.scrollHeight > metrics.clientHeight + 20) expect(metrics.scrolled).toBe(true)
      const directory = dialog.getByLabel('目标目录', { exact: true })
      await directory.scrollIntoViewIfNeeded()
      await expect(directory).toBeInViewport()
      await expect(dialog.locator('[data-ingestion-submit]')).toBeInViewport({ ratio: 1 })
      await expect(dialog.getByRole('button', { name: '取消', exact: true })).toBeInViewport({ ratio: 1 })
      expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      await expect(trigger).toBeFocused()
    }
  })

  test('keeps quarantine vertically scrollable at laptop heights', async ({ page }) => {
    test.setTimeout(180_000)
    for (const viewport of [
      { width: 1024, height: 768 },
      { width: 1280, height: 720 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/knowledge/quarantine', {
        waitUntil: 'domcontentloaded',
        timeout: 150_000,
      })
      await expect(page.getByRole('heading', { name: '隔离队列', exact: true })).toBeVisible({
        timeout: 60_000,
      })

      const metrics = await scrollContainerMetrics(
        page,
        '[data-quarantine-page-root="true"] [data-page-scroll-container]',
      )
      expect(metrics.clientHeight).toBeGreaterThan(0)
      expect(['auto', 'scroll']).toContain(metrics.overflowY)
      expect(metrics.scrollHeight).toBeGreaterThanOrEqual(metrics.clientHeight)
      if (metrics.scrollHeight > metrics.clientHeight + 20) {
        expect(metrics.scrolled).toBe(true)
      }
    }
  })

  test('keeps chunk preview readable at 1024px width', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1024, height: 768 })

    await page.goto('/chunk-preview', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    await expect(page.getByRole('heading', { name: '预览文档切片', exact: true })).toBeVisible({
      timeout: 60_000,
    })
    await expect(page.getByRole('button', { name: '选择已有文档', exact: true })).toBeInViewport()
    await expect(page.getByRole('button', { name: '上传文件', exact: true })).toBeInViewport()

    expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
  })

  test('keeps retrieval ablations readable at 1024px width', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1024, height: 768 })

    await page.goto('/evaluations/ablations', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    await expect(page.getByRole('heading', { name: '检索调参对比' })).toBeVisible({
      timeout: 60_000,
    })

    expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
  })

  test('keeps evidence workbench usable at 960px, 1024px and 1280px widths', async ({ page }) => {
    test.setTimeout(180_000)
    for (const viewport of [
      { width: 960, height: 768, compact: true },
      { width: 1024, height: 768, compact: false },
      { width: 1280, height: 720, compact: false },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/datasets/ds-smoke/evidence', {
        waitUntil: 'domcontentloaded',
        timeout: 150_000,
      })
      await expect(page.getByRole('heading', { name: '证据库', exact: true })).toBeVisible({ timeout: 60_000 })
      const navigation = page.getByRole('navigation', { name: '工作区视图', exact: true })
      const suiteButton = page.getByRole('button', {
        name: /Smoke Evidence Suite/,
      })
      await expect(suiteButton).toBeVisible({ timeout: 60_000 })
      await suiteButton.click()
      if (viewport.compact) {
        await expect(navigation.getByRole('button', { name: '证据条目', exact: true })).toHaveAttribute(
          'aria-pressed',
          'true',
        )
        await expect(suiteButton).toBeHidden()
      } else {
        await expect(navigation).toBeHidden()
        await expect(suiteButton).toBeVisible()
      }
      await expect(page.getByRole('heading', { name: '证据条目', exact: true })).toBeVisible()
      const evidenceItem = page.getByRole('button', {
        name: 'How does the smoke evidence item behave at laptop widths?',
        exact: true,
      })
      await expect(evidenceItem).toBeVisible({ timeout: 10_000 })
      await evidenceItem.click()
      const detail = page.getByRole('dialog', { name: '证据条目', exact: true })
      await expect(detail).toBeInViewport({ ratio: 1 })
      await expect(detail).toContainText('It should stay readable and selectable.')
      expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
      await page.keyboard.press('Escape')
      await expect(evidenceItem).toBeFocused()
      if (viewport.compact) {
        await navigation.getByRole('button', { name: '证据集', exact: true }).click()
        await expect(suiteButton).toBeInViewport()
      }
    }
  })

  test('keeps knowledge filters in a scrollable drawer at low height', async ({ page }) => {
    test.setTimeout(180_000)
    await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
    await page.setViewportSize({ width: 1280, height: 720 })

    await page.goto('/knowledge', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    await expect(page.getByRole('heading', { name: '知识库', exact: true })).toBeVisible({
      timeout: 60_000,
    })
    await expect(page.getByRole('complementary', { name: '数据集与目录', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '更多筛选', exact: true }).click()
    await expect(page.getByRole('dialog').getByRole('heading', { name: '更多筛选' })).toBeVisible()

    const metrics = await scrollContainerMetrics(page, '[data-knowledge-scope-content]')
    expect(metrics.clientHeight).toBeGreaterThan(0)
    expect(['auto', 'scroll']).toContain(metrics.overflowY)
    expect(metrics.scrollHeight).toBeGreaterThanOrEqual(metrics.clientHeight)
    if (metrics.scrollHeight > metrics.clientHeight + 20) {
      expect(metrics.scrolled).toBe(true)
    }
  })

  test('keeps RBAC controls inside the 1024px viewport', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1024, height: 768 })

    await page.goto('/settings/rbac', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    await expect(page.getByRole('heading', { name: '成员权限' })).toBeVisible({
      timeout: 60_000,
    })

    expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)
  })

  test('does not reopen the compact similarity sidebar across breakpoint changes', async ({ page }) => {
    test.setTimeout(180_000)

    await page.setViewportSize({ width: 1024, height: 768 })
    await page.goto('/knowledge/similarity', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    await expect(page.getByRole('heading', { name: '向量相似度诊断' })).toBeVisible({ timeout: 60_000 })

    const source = page.getByRole('dialog', { name: '数据源与计算', exact: true })
    await expect(source).toBeHidden()
    await page.getByRole('button', { name: '数据源与计算', exact: true }).click()
    await expect(source).toBeInViewport({ ratio: 1 })
    await page.keyboard.press('Escape')
    await expect(source).toBeHidden()

    await page.setViewportSize({ width: 1366, height: 768 })
    await expect(source).toBeHidden()
  })

  test('loads usage page with token and quota summaries', async ({ page }) => {
    await page.goto('/usage')
    await expect(page.getByRole('heading', { name: '用量／配额' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('row', { name: /Smoke Dataset.*128/ })).toBeVisible()
  })

  test('loads audit page with mocked audit events', async ({ page }) => {
    await page.goto('/audit')
    await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('row', { name: /smoke\.audit\.view/ })).toBeVisible()
  })

  test('redirects the retired access-review page to audit logs', async ({ page }) => {
    await page.goto('/access-review')
    await expect(page).toHaveURL(/\/audit/)
    await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible({ timeout: 60_000 })
  })

  test('all major management surface routes are reachable', async ({ page }) => {
    test.setTimeout(600_000)

    await page.route('**/*', async (route) => {
      const headers = route.request().headers()
      if (headers['next-router-prefetch'] === '1' || headers.purpose === 'prefetch') {
        await route.abort()
        return
      }
      await route.fallback()
    })

    const routes = [
      '/',
      '/history',
      '/datasets',
      '/knowledge',
      '/knowledge/quarantine',
      '/knowledge/feedback',
      '/knowledge/ingestion',
      '/parsing',
      '/data-governance',
      '/data-governance/profiles',
      '/chunk-preview',
      '/graph',
      '/evaluations',
      '/reports',
      '/prompts',
      '/diagnostics',
      '/usage',
      '/audit',
      '/settings/rbac',
      '/settings/groups',
      '/settings',
    ]

    for (const route of routes) {
      await test.step(route, async () => {
        const response = await page.request.get(route, { failOnStatusCode: false })
        expect(response.status()).toBeLessThan(400)
        await page.goto(route, { waitUntil: 'domcontentloaded' })
        await expect(page, `${route} redirected to authentication`).not.toHaveURL(/\/auth(?:\?|$)/)
      })
    }

    await page.goto('/access-review')
    await expect(page).toHaveURL(/\/audit/)
  })

  test('renders retrieval results without nested interactive controls', async ({ page }) => {
    const nestedControlErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() !== 'error') return
      const text = message.text()
      if (text.includes('<button> cannot be a descendant of <button>')) {
        nestedControlErrors.push(text)
      }
    })
    await page.route('**/api/v1/documents/stats**', (route) =>
      fulfillJson(route, { total: 1, total_chunks: 1, total_size: 1024, by_status: { completed: 1 } }),
    )
    await page.route('**/api/v1/rag/retrieve', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      return fulfillJson(route, {
        schema: 'mimirq.evidence.v1',
        query_for_retrieval: '发布验收',
        citations: [
          {
            document_id: 'doc-retrieval-a11y',
            document_name: '发布验收规范.pdf',
            chunk_id: 'chunk-retrieval-a11y',
            chunk_content: '发布前应检查权限、检索结果和引用证据。',
            score: 0.94,
          },
        ],
        metrics: {},
        has_evidence: true,
        abstain_triggered: false,
      })
    })

    await page.goto('/knowledge?tab=retrieval&dataset=ds-smoke')
    const searchInput = page.getByRole('textbox', { name: '检索问题', exact: true })
    await expect(searchInput).toBeVisible({ timeout: 60_000 })
    await searchInput.fill('发布验收')
    const search = page.getByRole('button', { name: '检索', exact: true })
    await expect(search).toBeEnabled()
    await search.click()
    const results = page.getByRole('list', { name: '命中片段', exact: true })
    await expect(results.getByText('发布验收规范.pdf', { exact: true })).toBeVisible()
    await expect(results.locator('button button')).toHaveCount(0)
    expect(nestedControlErrors).toEqual([])
  })

  test('captures the documented knowledge-base journey on demand', async ({ page }) => {
    test.skip(
      process.env.CAPTURE_DOCS_SCREENSHOTS !== '1',
      'Set CAPTURE_DOCS_SCREENSHOTS=1 to refresh committed guide screenshots.',
    )
    test.setTimeout(240_000)
    await page.setViewportSize({ width: 1600, height: 1000 })

    await page.route('**/api/v1/documents/stats**', (route) =>
      fulfillJson(route, { total: 1, total_chunks: 2, total_size: 1024, by_status: { completed: 1 } }),
    )
    const evidence = {
      document_id: 'doc-guide-1',
      document_name: '企业知识库操作规范.pdf',
      chunk_id: 'chunk-guide-1',
      chunk_content: '正式发布前应完成数据集权限检查、真实检索验证与引用核对，并保留可回归的 Golden 题集。',
      page_number: 12,
      score: 0.943,
      relevance_score: 0.943,
      retrieval_score: 0.918,
      retrieval_role: 'hierarchy_primary',
      matched_terms: ['权限检查', '检索验证', '引用核对'],
      policy_clause_number: '第十二条',
      policy_path_str: '发布管理 / 上线验收 / 知识库',
      family_hit: true,
      has_image: false,
    }

    await page.route('**/api/v1/rag/retrieve', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      return fulfillJson(route, {
        schema: 'mimirq.evidence.v1',
        query_for_retrieval: '知识库发布前需要完成哪些验收？',
        citations: [
          evidence,
          {
            ...evidence,
            chunk_id: 'chunk-guide-2',
            chunk_content: '上线后应通过 request_id 关联 API、Worker、模型服务和检索 Trace，并持续复测关键问题。',
            page_number: 13,
            score: 0.887,
            relevance_score: 0.887,
            retrieval_role: 'vector_primary',
            policy_clause_number: '第十三条',
            policy_path_str: '发布管理 / 运行观测',
            family_hit: false,
          },
        ],
        metrics: {
          candidate_count: 24,
          returned_count: 2,
          retrieval_mode: 'hybrid',
          reranker: 'enabled',
        },
        has_evidence: true,
        abstain_triggered: false,
      })
    })

    await page.route('**/api/v1/chat/stream', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      return fulfillChatStream(route, {
        contentParts: ['发布前需要完成数据集权限检查、真实检索验证和引用核对，并保存 Golden 题集作为回归基线。'],
        citations: [evidence],
        requestId: 'req-guide-screenshot',
      })
    })

    await page.route('**/api/v1/datasets**', async (route) => {
      const request = route.request()
      const pathname = new URL(request.url()).pathname.replace(/\/$/, '')
      if (request.method() !== 'GET') return route.fallback()
      const dataset = {
        id: 'ds-smoke',
        name: '企业知识库示例',
        description: '用于演示建库、入库、检索与引用闭环的公开样例。',
        created_at: '2026-07-29T00:00:00Z',
        updated_at: '2026-07-29T00:00:00Z',
      }
      if (pathname === '/api/v1/datasets') {
        return fulfillJson(route, { items: [dataset], total: 1 })
      }
      if (pathname === '/api/v1/datasets/ds-smoke') {
        return fulfillJson(route, dataset)
      }
      return route.fallback()
    })

    await page.goto('/datasets')
    await expect(page.getByRole('heading', { name: '数据集' }).first()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('企业知识库示例').first()).toBeVisible()
    await captureGuideScreenshot(page, 'guide-create-dataset.png')

    await page.goto('/knowledge/ingestion?datasetId=ds-smoke')
    await expect(page.getByRole('heading', { name: '入库管理', exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('企业知识库示例').first()).toBeVisible()
    await captureGuideScreenshot(page, 'guide-ingestion.png')

    await page.goto('/knowledge?tab=retrieval&dataset=ds-smoke')
    const retrieval = page.getByRole('tabpanel', { name: '检索测试', exact: true })
    const searchInput = retrieval.getByRole('textbox', { name: '检索问题', exact: true })
    await expect(searchInput).toBeVisible({ timeout: 60_000 })
    await searchInput.fill('知识库发布前需要完成哪些验收？')
    await retrieval.getByRole('button', { name: '检索', exact: true }).click()
    const results = retrieval.getByRole('list', { name: '命中片段', exact: true })
    await expect(results.getByText('企业知识库操作规范.pdf', { exact: true }).first()).toBeVisible()
    await captureGuideScreenshot(page, 'guide-retrieval-test.png')

    await page.goto('/')
    const composer = page.getByRole('textbox', { name: '消息输入框', exact: true })
    await expect(composer).toBeVisible({ timeout: 60_000 })
    const datasetScope = page
      .getByRole('main')
      .locator('button[aria-haspopup="dialog"]:has(svg[data-platform-icon="dataset"])')
    await expect(datasetScope).toBeVisible({ timeout: 60_000 })
    await datasetScope.click()
    await page
      .getByRole('dialog', { name: '数据集', exact: true })
      .getByRole('button', { name: /^企业知识库示例(?:\s|$)/ })
      .click()
    await expect(datasetScope).toHaveAccessibleName('企业知识库示例')
    await composer.fill('知识库发布前需要完成哪些验收？')
    await page.getByRole('button', { name: '发送' }).click()
    await expect(page.getByText('发布前需要完成数据集权限检查')).toBeVisible({ timeout: 60_000 })
    await page.getByText('来源与证据', { exact: true }).last().click()
    const openEvidence = page.locator('details[open]').last()
    await expect(openEvidence.getByText('企业知识库操作规范.pdf')).toBeVisible()
    await openEvidence.scrollIntoViewIfNeeded()
    await captureGuideScreenshot(page, 'guide-source-evidence.png')
  })
})
