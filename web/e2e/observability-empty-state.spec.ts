import { expect, test } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

for (const state of [
  { enabled: false, records: 0 },
  { enabled: false, records: 12 },
  { enabled: true, records: 0 },
]) {
  test(`observability keeps one empty state and historical readings (enabled=${state.enabled}, records=${state.records})`, async ({
    page,
  }) => {
    await installCommonApiMocks(page, { uploaded: false })
    await page.route('**/api/v1/observability/rag-metrics/**', (route) => {
      const summary = {
        enabled: state.enabled,
        path: 'metrics.jsonl',
        window_minutes: 60,
        truncated: false,
        record_count: state.records,
        rag_trace_count: state.records,
        timeseries: {},
      }
      return route.fulfill({
        json: route.request().url().includes('/query-analytics')
          ? {
              ...summary,
              unique_query_hashes: state.records,
              zero_hit_count: 0,
              zero_hit_rate: null,
              slow_threshold_sec: 2,
              slow_count: 0,
              slow_rate: null,
              retrieval_p50_elapsed_sec: null,
              retrieval_p95_elapsed_sec: null,
              retrieval_p99_elapsed_sec: null,
              error_kind_counts: {},
              top_zero_hit_queries: [],
              top_slow_queries: [],
            }
          : {
              ...summary,
              reranker_api_count: 0,
              retrieval_avg_elapsed_sec: null,
              retrieval_p95_elapsed_sec: null,
              citations_avg_count: null,
              retrieval_mode_counts: {},
              hit_type_counts: {},
              error_counts: {},
            },
      })
    })
    await page.goto('/observability')
    const inactive = !state.enabled && state.records === 0
    const overview = page.getByRole('tabpanel', { name: '指标总览', exact: true })
    await expect(overview.getByText('检索请求', { exact: true })).toHaveCount(inactive ? 0 : 1)
    await expect(overview.getByRole('heading', { name: '指标记录未开启', exact: true })).toHaveCount(inactive ? 1 : 0)
    await expect(overview.getByRole('heading', { name: '当前时间范围暂无观测记录', exact: true })).toHaveCount(
      state.enabled ? 1 : 0,
    )
    if (inactive)
      await expect(overview.getByRole('link', { name: '前往设置', exact: true })).toHaveAttribute('href', '/settings')
    if (!state.enabled && state.records > 0) await expect(overview.getByRole('status')).toContainText('历史记录')
    await page.getByRole('tab', { name: '查询分析', exact: true }).click()
    const analytics = page.getByRole('tabpanel', { name: '查询分析', exact: true })
    await expect(analytics.getByText('检索请求', { exact: true })).toHaveCount(inactive ? 0 : 1)
    await expect(analytics.getByRole('heading', { name: '查询指标记录未开启', exact: true })).toHaveCount(
      inactive ? 1 : 0,
    )
    await expect(analytics.getByText('当前窗口未返回零命中或慢查询记录', { exact: true })).toHaveCount(inactive ? 0 : 1)
    if (inactive) await expect(analytics.getByRole('link', { name: '前往设置', exact: true })).toBeVisible()
    if (!state.enabled && state.records > 0) await expect(analytics.getByRole('status')).toContainText('历史记录')
  })
}
