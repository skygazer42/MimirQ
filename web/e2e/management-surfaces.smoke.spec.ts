import { expect, test, type Page, type Route } from '@playwright/test'

import { installCommonApiMocks, installDeterministicRandom, type EnterpriseTelemetryMockState } from './enterprise-quality-telemetry.helpers'

async function fulfillJson(route: Route, payload: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })
}

async function installManagementSurfaceMocks(page: Page) {
  const state: EnterpriseTelemetryMockState = { uploaded: false, parsingDocuments: [] }
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
}

test.describe('management surfaces smoke', () => {
  test.beforeEach(async ({ page }) => {
    await installManagementSurfaceMocks(page)
  })

  test('loads prompts page with the managed prompt shell', async ({ page }) => {
    await page.goto('/prompts')
    await expect(page.getByText('提示词模板')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('提示词中心 · 管理工作台')).toBeVisible()
  })

  test('loads reports page with mocked dataset data', async ({ page }) => {
    await page.goto('/reports')
    await expect(page.getByText('报告中心')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Smoke Dataset')).toBeVisible()
  })

  test('loads evaluations page with conversation and run data', async ({ page }) => {
    await page.goto('/evaluations')
    await expect(page.getByText('评测中心')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Smoke Conversation')).toBeVisible()
  })

  test('loads usage page with token and quota summaries', async ({ page }) => {
    await page.goto('/usage')
    await expect(page.getByText('用量/配额')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Smoke Dataset')).toBeVisible()
  })

  test('loads audit page with mocked audit events', async ({ page }) => {
    await page.goto('/audit')
    await expect(page.getByText('审计日志')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('smoke.audit.view')).toBeVisible()
  })

  test('loads access-review page with mocked access graph metrics', async ({ page }) => {
    await page.goto('/access-review')
    await expect(page.getByText('访问审查')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('4')).toBeVisible()
  })
})
