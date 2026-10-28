import type { Page } from '@playwright/test'
import { remainingFixture } from './remaining-pages.helpers'

export async function similarityFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await remainingFixture(page, theme)
  const state = { fail: true, requests: [] as unknown[] }
  await page.route('**/api/v1/ragviz/similarity/**', async route => {
    if (new URL(route.request().url()).pathname.endsWith('/collections')) return route.fulfill({ json: { collections: [{ id: 'source-a', label: '设备手册', kind: 'document', count: 2 }, { id: 'source-b', label: '维护规范', kind: 'document', count: 2 }] } })
    state.requests.push(route.request().postDataJSON())
    return route.fulfill({ status: state.fail ? 503 : 200, json: state.fail ? { detail: '相似度服务暂不可用' } : { success: true, result: { matrix: [[1, 0.73], [0.73, 1]], x_data: [{ document: '设备型号' }, { document: '维护周期' }], y_data: [{ document: '型号说明' }, { document: '保养规范' }], x_available_fields: ['document'], y_available_fields: ['document'], stats: { total_pairs: 4, avg_similarity: 0.865, min_similarity: 0.73, max_similarity: 1, std_similarity: 0.135, high_similarity_count: 2, medium_similarity_count: 2, low_similarity_count: 0, compute_time: 0.02 }, metadata: {} } } })
  })
  return state
}
