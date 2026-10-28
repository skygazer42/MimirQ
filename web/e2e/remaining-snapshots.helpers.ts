import fs from 'node:fs'
import path from 'node:path'
import type { Page } from '@playwright/test'
import { remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

export async function snapshotFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  const base = await remainingFixture(page, theme)
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/remaining-graph-snapshots.json'), 'utf8'))
  const state = { base, data, failCompare: false, failGraph: false, gate: null as Promise<void> | null, graphReads: 0, exports: [] as string[], diffs: [] as unknown[] }
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname.replace(/\/$/, '')
    if (p === '/api/v1/datasets' && req.method() === 'GET') return route.fulfill({ json: { total: 1, items: [{ id: policyDatasetId, name: '产品知识库', permission: 'all_team_members' }] } })
    if (p === `/api/v1/reports/datasets/${policyDatasetId}`) return route.fulfill({ json: { dataset_id: policyDatasetId, pipeline_hash: 'version-b', pipeline_versions: [{ pipeline_hash: 'version-a', documents: 2 }, { pipeline_hash: 'version-b', documents: 2 }], profile: { document_count: 2 } } })
    if (p === '/api/v1/documents') return route.fulfill({ json: { total: 0, items: [] } })
    if (p === '/api/v1/kg/snapshots/export') { state.exports.push(url.search); return route.fulfill({ json: url.searchParams.get('pipeline_hash') === 'version-a' ? data.a : data.b }) }
    if (p === '/api/v1/kg/snapshots/diff') {
      state.diffs.push(req.postDataJSON())
      if (state.gate) await state.gate
      return route.fulfill({ status: state.failCompare ? 503 : 200, json: state.failCompare ? { detail: '快照对比暂不可用' } : data.diff })
    }
    if (p === '/api/v1/kg/snapshots/compare') return route.fulfill({ json: data.diff })
    if (p === '/api/v1/kg/graph') { state.graphReads++; return route.fulfill({ status: state.failGraph ? 503 : 200, json: state.failGraph ? { detail: '预览图谱暂不可用' } : data.graph }) }
    return route.fallback()
  })
  return state
}

export const snapshotRoute = `/graph/snapshots?dataset_id=${policyDatasetId}`
