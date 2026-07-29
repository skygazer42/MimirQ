import path from 'node:path'

import { expect, test, type Page, type Route } from '@playwright/test'

import { installCommonApiMocks, installDeterministicRandom, type EnterpriseTelemetryMockState } from './enterprise-quality-telemetry.helpers'

async function fulfillJson(route: Route, payload: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })
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
    path: path.resolve(__dirname, '../../docs/images/screenshots', filename),
    fullPage: false,
  })
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
  return page.locator(selector).first().evaluate((element) => {
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

  await page.route('**/api/v1/chat/conversations**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          id: 'conv-smoke',
          title: 'Smoke Conversation',
          created_at: '2026-04-09T00:00:00Z',
          updated_at: '2026-04-09T00:00:00Z',
        },
      ],
      total: 1,
    })
  })

  await page.route('**/api/v1/evaluations/ragas/runs**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          id: 'run-smoke',
          conversation_id: 'conv-smoke',
          status: 'completed',
          metrics: ['faithfulness', 'response_relevancy'],
          params: {},
          summary: { faithfulness: 0.92 },
          created_at: '2026-04-09T00:00:00Z',
        },
      ],
      total: 1,
    })
  })

  await page.route('**/api/v1/evaluations/ragas/conversation-readiness', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          conversation_id: 'conv-smoke',
          is_known: true,
          is_evaluable: true,
          citations_count: 2,
        },
      ],
    })
  })

  await page.route('**/api/v1/evaluations/ragas/runs/run-smoke**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      run: {
        id: 'run-smoke',
        conversation_id: 'conv-smoke',
        status: 'completed',
        metrics: ['faithfulness', 'response_relevancy'],
        params: {},
        summary: { faithfulness: 0.92 },
        created_at: '2026-04-09T00:00:00Z',
      },
      items: [],
    })
  })

  await page.route('**/api/v1/usage/chat/tokens/summary**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      total_assistant_tokens: 128,
      by_dataset: [
        {
          dataset_id: 'ds-smoke',
          assistant_tokens: 128,
        },
      ],
    })
  })

  await page.route('**/api/v1/usage/chat/cost/summary**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
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
      used_tokens: 128,
      max_tokens: 1000,
    })
  })

  await page.route('**/api/v1/audit/logs**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return fulfillJson(route, {
      items: [
        {
          id: 'audit-smoke',
          action: 'smoke.audit.view',
          actor_id: 'demo',
          resource_type: 'dataset',
          resource_id: 'ds-smoke',
          created_at: '2026-04-09T00:00:00Z',
          request_id: 'req-smoke',
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
    await expect(page.getByTestId('page-title-shell').getByText('提示词模板')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('创建模板')).toBeVisible()
  })

  test('loads reports page with mocked dataset data', async ({ page }) => {
    await page.goto('/reports')
    await expect(page.getByRole('heading', { name: '数据报告' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('combobox', { name: '数据集' })).toContainText('Smoke Dataset')
  })

  test('loads evaluations page with conversation and run data', async ({ page }) => {
    await page.goto('/evaluations')
    await expect(page.getByText('评测中心')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('combobox').first()).toContainText('Smoke Conversation')
  })

  test('keeps the datasets hero tint restrained', async ({ page }) => {
    await page.goto('/datasets')
    const heading = page.getByRole('heading', { name: '数据集' }).first()
    await expect(heading).toBeVisible({ timeout: 60_000 })

    const hero = heading.locator('xpath=ancestor::div[contains(@class, "overflow-hidden")][1]')
    const className = await hero.getAttribute('class')
    expect(className).toContain('hsl(var(--card)/0.98)')
    expect(className).not.toContain('hsl(var(--info)/0.24)')

    const geometry = await hero.evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        height: element.getBoundingClientRect().height,
        padding: style.padding,
        borderRadius: style.borderRadius,
      }
    })
    expect(geometry.height).toBeLessThanOrEqual(96)
    expect(geometry.padding).toBe('12px 16px')
    expect(geometry.borderRadius).toBe('28px')
  })

  test('keeps the knowledge header surfaces restrained', async ({ page }) => {
    await page.goto('/knowledge')
    const heading = page.getByRole('heading', { name: '知识库管理' }).first()
    await expect(heading).toBeVisible({ timeout: 60_000 })

    const hero = heading.locator('xpath=ancestor::div[contains(@class, "overflow-hidden")][1]')
    const heroClassName = await hero.getAttribute('class')
    expect(heroClassName).toContain('hsl(var(--card)/0.98)')
    expect(heroClassName).not.toContain('hsl(var(--info)/0.24)')

    const summaryStrip = page.locator('div.grid.border-y').first()
    const summaryClassName = await summaryStrip.getAttribute('class')
    expect(summaryClassName).toContain('hsl(var(--card)/0.98)')
    expect(summaryClassName).not.toContain('hsl(var(--info)/0.08)')
  })

  test('uses the shared gradient title treatment on custom management heroes', async ({ page }) => {
    for (const surface of [
      { route: '/datasets', heading: '数据集', occurrence: 'first' },
      { route: '/knowledge', heading: '知识库管理', occurrence: 'first' },
      { route: '/evaluations', heading: '实时会话评分', occurrence: 'last' },
    ] as const) {
      await page.goto(surface.route, { waitUntil: 'domcontentloaded' })
      const headings = page.getByRole('heading', { name: surface.heading })
      const heading = surface.occurrence === 'first' ? headings.first() : headings.last()
      await expect(heading, `${surface.route} heading`).toBeVisible({ timeout: 60_000 })

      const titleInk = heading.locator(':scope > span')
      await expect(titleInk, `${surface.route} gradient title ink`).toHaveClass(/bg-clip-text/)
      await expect(titleInk, `${surface.route} transparent title ink`).toHaveClass(/text-transparent/)

      const titleStyle = await titleInk.evaluate((element) => {
        const style = getComputedStyle(element)
        return {
          backgroundImage: style.backgroundImage,
          backgroundClip: style.backgroundClip,
          color: style.color,
        }
      })
      expect(titleStyle.backgroundImage, `${surface.route} gradient`).toContain('linear-gradient')
      expect(titleStyle.backgroundClip, `${surface.route} clipping`).toBe('text')
      expect(titleStyle.color, `${surface.route} transparent ink`).toBe('rgba(0, 0, 0, 0)')
    }
  })

  test('aligns quarantine and feedback headers with Knowledge Ops', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })

    for (const surface of [
      { route: '/knowledge/quarantine', heading: '隔离审核中心' },
      { route: '/knowledge/feedback', heading: '反馈分析中心' },
    ]) {
      await page.goto(surface.route)
      const heading = page.getByRole('heading', { name: surface.heading }).first()
      await expect(heading).toBeVisible({ timeout: 60_000 })

      const hero = heading.locator('xpath=ancestor::div[contains(@class, "overflow-hidden")][1]')
      const className = await hero.getAttribute('class')
      expect(className).toContain('hsl(var(--card)/0.98)')

      const geometry = await hero.evaluate((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return {
          x: rect.x,
          width: rect.width,
          height: rect.height,
          padding: style.padding,
          borderRadius: style.borderRadius,
        }
      })
      expect(geometry.x).toBe(288)
      expect(geometry.width).toBe(1128)
      expect(geometry.height).toBeLessThanOrEqual(100)
      expect(geometry.padding).toBe('12px 16px')
      expect(geometry.borderRadius).toBe('28px')
    }
  })

  test('aligns management headers with the shared hero grid', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1440, height: 900 })

    for (const surface of [
      { route: '/evaluations', heading: '实时会话评分' },
      { route: '/prompts', heading: '提示词模板' },
      { route: '/diagnostics', heading: '诊断中心' },
      { route: '/usage', heading: '用量/配额' },
      { route: '/audit', heading: '审计日志' },
      { route: '/settings/rbac', heading: '成员权限' },
      { route: '/settings/groups', heading: '组管理' },
      { route: '/settings', heading: '设置与配置' },
    ]) {
      await page.goto(surface.route, { waitUntil: 'domcontentloaded' })
      const heading = page.getByRole('heading', { name: surface.heading }).last()
      await expect(heading, `${surface.route} heading`).toBeVisible({ timeout: 15_000 })
      await page.waitForTimeout(300)

      const hero =
        surface.route === '/evaluations'
          ? heading.locator('xpath=ancestor::section[contains(@class, "overflow-hidden")][1]')
          : page.getByTestId('page-title-shell').first()
      await expect(hero, `${surface.route} shared hero`).toBeVisible({ timeout: 10_000 })
      const className = await hero.getAttribute('class')
      expect(className, `${surface.route} should use the shared hero surface`).toContain(
        'hsl(var(--card)/0.98)'
      )

      const geometry = await hero.evaluate((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return {
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height,
          padding: style.padding,
          borderRadius: style.borderRadius,
        }
      })
      expect(geometry.x, `${surface.route} x`).toBeCloseTo(288, 0)
      expect(Math.abs(geometry.y - 16), `${surface.route} y drift`).toBeLessThanOrEqual(1)
      expect(geometry.width, `${surface.route} width`).toBeCloseTo(1128, 0)
      expect(geometry.height, `${surface.route} height`).toBeGreaterThanOrEqual(94)
      expect(geometry.height, `${surface.route} height`).toBeLessThanOrEqual(100)
      expect(geometry.padding, `${surface.route} padding`).toBe('12px 16px')
      expect(geometry.borderRadius, `${surface.route} radius`).toBe('28px')
    }

    await page.setViewportSize({ width: 1280, height: 768 })
    await page.goto('/evaluations', { waitUntil: 'domcontentloaded' })
    const evaluationHeading = page.getByRole('heading', { name: '实时会话评分' }).last()
    await expect(evaluationHeading).toBeVisible({ timeout: 15_000 })
    const evaluationHero = evaluationHeading.locator(
      'xpath=ancestor::section[contains(@class, "overflow-hidden")][1]'
    )
    const evaluationGeometry = await evaluationHero.evaluate((element) => ({
      height: element.getBoundingClientRect().height,
      pageOverflow:
        Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
        window.innerWidth,
    }))
    expect(evaluationGeometry.height).toBeLessThanOrEqual(100)
    expect(evaluationGeometry.pageOverflow).toBeLessThanOrEqual(1)
  })

  test('uses semantic surfaces after switching to dark mode', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.goto('/evaluations', { waitUntil: 'domcontentloaded' })
    await expect(
      page.getByRole('heading', { name: '实时会话评分' }).first()
    ).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: '切换主题' }).last().click()
    const darkThemeItem = page.getByRole('menuitem', { name: '深色' })
    await expect(darkThemeItem).toBeVisible({ timeout: 10_000 })
    await darkThemeItem.click()
    await expect(page.locator('html')).toHaveClass(/dark/)

    for (const surface of [
      { route: '/evaluations', heading: '实时会话评分' },
      { route: '/evaluations/ablations', heading: '检索调参对比' },
      { route: '/reports', heading: '数据报告' },
      { route: '/datasets', heading: '数据集' },
    ]) {
      await page.goto(surface.route, { waitUntil: 'domcontentloaded' })
      const heading = page.getByRole('heading', { name: surface.heading }).first()
      await expect(heading).toBeVisible({ timeout: 60_000 })

      const legacyClasses = await visibleLegacyDarkSurfaceClasses(page)
      expect(
        legacyClasses,
        `${surface.route} still renders light-only utility classes in dark mode`
      ).toEqual([])

      const colors = await textAndSemanticForeground(
        page,
        `h1:has-text("${surface.heading}")`
      )
      expect(colors.actual).toBe(colors.expected)
    }
  })

  test('keeps similarity workbench readable at laptop width', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1280, height: 720 })

    await page.goto('/knowledge/similarity', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    const similarityTitle = page.getByRole('heading', {
      name: '跨集合相似度热力图',
    })
    await expect(similarityTitle).toBeVisible({ timeout: 60_000 })
    const similarityTitleBox = await similarityTitle.boundingBox()
    expect(similarityTitleBox?.width).toBeGreaterThan(160)
    expect(similarityTitleBox?.height).toBeLessThan(60)
  })

  test('keeps Golden workspace readable at laptop width', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1280, height: 720 })

    await page.goto('/evaluations', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    await page.getByRole('button', { name: 'Golden 评测集' }).click()
    const goldenWorkspaceTitle = page
      .getByText('Golden 评测集', { exact: true })
      .last()
    await expect(goldenWorkspaceTitle).toBeVisible({ timeout: 60_000 })
    const goldenTitleBox = await goldenWorkspaceTitle.boundingBox()
    expect(goldenTitleBox?.width).toBeGreaterThan(90)
    expect(goldenTitleBox?.height).toBeLessThan(40)

    const runHistoryTitle = page.getByText('运行历史', { exact: true })
    const runHistoryCardHeight = await runHistoryTitle.evaluate(
      (element) =>
        element.parentElement?.parentElement?.parentElement?.getBoundingClientRect()
          .height ?? 0
    )
    expect(runHistoryCardHeight).toBeGreaterThan(100)
  })

  test('keeps knowledge ingestion vertically scrollable at laptop heights', async ({ page }) => {
    test.setTimeout(180_000)
    for (const viewport of [
      { width: 1024, height: 768 },
      { width: 1280, height: 720 },
      { width: 1366, height: 768 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/knowledge/ingestion', {
        waitUntil: 'domcontentloaded',
        timeout: 150_000,
      })
      await expect(page.getByRole('heading', { name: '入库管理', exact: true })).toBeVisible({
        timeout: 60_000,
      })

      const metrics = await scrollContainerMetrics(
        page,
        '[data-ingestion-operation-root="true"]'
      )
      expect(metrics.scrollHeight).toBeGreaterThan(metrics.clientHeight + 20)
      expect(metrics.scrolled).toBe(true)
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
      await expect(page.getByText('隔离审核中心', { exact: true })).toBeVisible({
        timeout: 60_000,
      })

      const metrics = await scrollContainerMetrics(
        page,
        '[data-quarantine-page-root="true"]'
      )
      expect(metrics.scrollHeight).toBeGreaterThan(metrics.clientHeight + 20)
      expect(metrics.scrolled).toBe(true)
    }
  })

  test('keeps chunk preview readable at 1024px width', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1024, height: 768 })

    await page.goto('/chunk-preview', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    await expect(page.locator('[data-chunk-empty-intake-panel]')).toBeVisible({
      timeout: 60_000,
    })

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

  test('keeps evidence workbench usable at 1024px and 1280px widths', async ({ page }) => {
    test.setTimeout(180_000)
    for (const viewport of [
      { width: 1024, height: 768, stacked: true },
      { width: 1280, height: 720, stacked: false },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/datasets/ds-smoke/evidence', {
        waitUntil: 'domcontentloaded',
        timeout: 150_000,
      })
      await expect(
        page.getByRole('heading', { name: '证据库（Evidence Workbench）' })
      ).toBeVisible({ timeout: 60_000 })

      const suitePanel = page.getByText('Evidence Suites', { exact: true })
      const itemPanel = page.getByText('Evidence Items', { exact: true })
      const detailPanel = page.getByText('Detail', { exact: true })
      await expect(suitePanel).toBeVisible()
      await expect(itemPanel).toBeVisible()
      const suiteButton = page.getByRole('button', {
        name: /Smoke Evidence Suite/,
      })
      await expect(suiteButton).toBeVisible({ timeout: 60_000 })
      await suiteButton.click()
      await itemPanel.scrollIntoViewIfNeeded()
      await expect(itemPanel).toBeVisible()
      const evidenceItem = page.getByText('How does the smoke evidence item behave at laptop widths?', {
        exact: true,
      })
      await expect(evidenceItem).toBeVisible({ timeout: 10_000 })
      await evidenceItem.click()
      await detailPanel.scrollIntoViewIfNeeded()
      await expect(detailPanel).toBeVisible()
      expect(await documentHorizontalOverflow(page)).toBeLessThanOrEqual(1)

      const suiteBox = await suitePanel.boundingBox()
      const detailBox = await detailPanel.boundingBox()
      if (viewport.stacked) {
        expect(detailBox?.y).toBeGreaterThan((suiteBox?.y ?? 0) + 120)
      }
    }
  })

  test('keeps the knowledge scope panel scrollable at low height', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 1280, height: 720 })

    await page.goto('/knowledge', {
      waitUntil: 'domcontentloaded',
      timeout: 150_000,
    })
    await expect(page.getByText('Scope Navigator', { exact: true })).toBeVisible({
      timeout: 60_000,
    })

    const metrics = await scrollContainerMetrics(page, '[data-knowledge-scope-panel]')
    expect(metrics.scrollHeight).toBeGreaterThan(metrics.clientHeight + 20)
    expect(metrics.scrolled).toBe(true)
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
    await expect(
      page.getByRole('heading', { name: '跨集合相似度热力图' })
    ).toBeVisible({ timeout: 60_000 })

    const dataSourcePanelTitle = page.getByText('数据源配置', { exact: true }).last()
    await expect(dataSourcePanelTitle).not.toBeVisible()

    await page.setViewportSize({ width: 1366, height: 768 })
    await expect(dataSourcePanelTitle).not.toBeVisible()
  })

  test('loads usage page with token and quota summaries', async ({ page }) => {
    await page.goto('/usage')
    await expect(page.getByRole('heading', { name: '用量/配额' })).toBeVisible({ timeout: 60_000 })
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

  test('renders retrieval results without nested interactive controls', async ({ page }) => {
    const nestedControlErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() !== 'error') return
      const text = message.text()
      if (text.includes('<button> cannot be a descendant of <button>')) {
        nestedControlErrors.push(text)
      }
    })
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
        has_evidence: true,
        abstain_triggered: false,
      })
    })

    await page.goto('/knowledge?tab=retrieval&dataset=ds-smoke')
    const searchInput = page.getByPlaceholder(
      '例如：请按第十二条说明例外条件，并指出适用范围与例外条款'
    )
    await expect(searchInput).toBeVisible({ timeout: 60_000 })
    await searchInput.fill('发布验收')
    await page.getByRole('button', { name: '开始检索' }).click()
    await expect(page.getByText('发布验收规范.pdf').first()).toBeVisible()
    await expect(
      page.locator('[aria-label="检索结果排名列表"] button button')
    ).toHaveCount(0)
    expect(nestedControlErrors).toEqual([])
  })

  test('captures the documented knowledge-base journey on demand', async ({ page }) => {
    test.skip(
      process.env.CAPTURE_DOCS_SCREENSHOTS !== '1',
      'Set CAPTURE_DOCS_SCREENSHOTS=1 to refresh committed guide screenshots.'
    )
    test.setTimeout(240_000)
    await page.setViewportSize({ width: 1600, height: 1000 })

    const evidence = {
      document_id: 'doc-guide-1',
      document_name: '企业知识库操作规范.pdf',
      chunk_id: 'chunk-guide-1',
      chunk_content:
        '正式发布前应完成数据集权限检查、真实检索验证与引用核对，并保留可回归的 Golden 题集。',
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
            chunk_content:
              '上线后应通过 request_id 关联 API、Worker、模型服务和检索 Trace，并持续复测关键问题。',
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
      const body = [
        { type: 'citations', data: [evidence] },
        {
          type: 'token',
          data: {
            content:
              '发布前需要完成数据集权限检查、真实检索验证和引用核对，并保存 Golden 题集作为回归基线。',
          },
        },
        {
          type: 'done',
          request_id: 'req-guide-screenshot',
          data: {
            conversation_id: 'conv-guide-screenshot',
            assistant_message_id: 'assistant-guide-screenshot',
            request_id: 'req-guide-screenshot',
          },
        },
      ]
        .map((event) => `data: ${JSON.stringify(event)}\n\n`)
        .join('')
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
          'X-Request-ID': 'req-guide-screenshot',
          'X-Conversation-ID': 'conv-guide-screenshot',
        },
        body,
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
    await expect(page.getByText('语义检索测试', { exact: true }).first()).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: '收起侧栏' }).click()
    await page
      .getByPlaceholder('例如：请按第十二条说明例外条件，并指出适用范围与例外条款')
      .fill('知识库发布前需要完成哪些验收？')
    await page.getByRole('button', { name: '开始检索' }).click()
    await expect(page.getByText('企业知识库操作规范.pdf').first()).toBeVisible()
    await captureGuideScreenshot(page, 'guide-retrieval-test.png')

    await page.goto('/')
    const datasetScope = page.getByRole('button', { name: '选择数据集', exact: true })
    await expect(datasetScope).toBeVisible({ timeout: 60_000 })
    await datasetScope.click()
    await page.getByRole('button', { name: /企业知识库示例/ }).last().click()
    const composer = page.getByPlaceholder('问点什么... (Shift + Enter 换行)')
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
