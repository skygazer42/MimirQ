import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page, type Route } from '@playwright/test'
import type { DatasetProfileSummary } from '../types'
import { datasetPolicyFixture, policyDatasetId } from './dataset-policy.helpers'
import { precheckSummary } from './precheck-workspace.helpers'
import { installRemainingRuntimeDiagnostics, saveRemainingRuntimeFailure } from './remaining-runtime.helpers'

export const remainingEvidence = path.resolve(__dirname, '../../artifacts/rebrand/remaining-pages-2026-10-27')
export const datasetRoute = (page: string) => `/datasets/${policyDatasetId}/${page}`
export function profileSummary(): DatasetProfileSummary {
  const { total_files, ...summary } = precheckSummary()
  return { ...summary, total_documents: total_files, by_status: { completed: 120, failed: 5, quarantined: 3 } }
}
async function json(route: Route, data: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) }) }
export async function remainingFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await page.route('**/api/v1/**', async route => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return json(route, { detail: '操作服务暂不可用' }, 503)
    return route.fallback()
  })
  await installRemainingRuntimeDiagnostics(page)
  const base = await datasetPolicyFixture(page, theme)
  const state = { base, failProfile: false, failHealth: false, failHistory: false, profile: profileSummary(), writes: [] as string[] }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname.replace(/\/$/, '')
    if (p === `/api/v1/datasets/${policyDatasetId}/profile/summary`) return state.failProfile ? json(route, { detail: '画像读取暂不可用' }, 503) : json(route, state.profile)
    if (p === `/api/v1/datasets/${policyDatasetId}/profile/scan-runs`) return state.failHistory ? json(route, { detail: '扫描历史读取暂不可用' }, 503) : json(route, { total: 0, items: [] })
    if (p === `/api/v1/datasets/${policyDatasetId}/health`) return state.failHealth ? json(route, { detail: '健康概览暂不可用' }, 503) : json(route, { dataset_id: policyDatasetId, generated_at: state.profile.generated_at, profile: state.profile, ingestion: { total_documents: 128, completed: 120, failed: 5, quarantined: 3, by_status: state.profile.by_status } })
    if (p.includes(`/api/v1/datasets/${policyDatasetId}/profile/findings/`)) return json(route, { total: 1, items: [{ id: '56b974c6-26f6-4890-b26f-10752ea61111', filename: 'product-guide.pdf', file_type: 'pdf', file_size: 4096, status: 'completed', created_at: state.profile.generated_at, updated_at: state.profile.generated_at }] })
    if (p === `/api/v1/datasets/${policyDatasetId}/config/export`) return json(route, { version: '1', dataset_id: policyDatasetId, config: { default_parser_backend: 'auto', default_chunk_strategy: 'default', pipeline: {}, ingestion_policy: null, rag_defaults: null } })
    if (p === `/api/v1/datasets/${policyDatasetId}/tables` || p === `/api/v1/datasets/${policyDatasetId}/db-catalog/tables`) return json(route, { total: 0, items: [] })
    if (p === '/api/v1/evidence/suites' || p === '/api/v1/connectors/runs') return json(route, { total: 0, items: [] })
    return route.fallback()
  })
  return state
}
export async function openRemaining(page: Page, url: string, title: string) {
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  try { await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible({ timeout: 60000 }) }
  catch (error) { await saveRemainingRuntimeFailure(page, remainingEvidence); throw error }
}
export async function remainingShot(page: Page, name: string) {
  const root = path.join(remainingEvidence, 'screens'); fs.mkdirSync(root, { recursive: true })
  await page.screenshot({ path: path.join(root, `${name}.png`), animations: 'disabled' })
  fs.writeFileSync(path.join(root, `${name}.html`), (await page.content()).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/\b(href|src)="\/(?!\/)/g, '$1="http://127.0.0.1:3000/'))
}

export async function realDatasetFixture(page: Page) {
  await installRemainingRuntimeDiagnostics(page)
  const state = JSON.parse(fs.readFileSync(path.join(remainingEvidence, 'real-api-state.json'), 'utf8')) as { user_id: string; tenant_id: string; dataset_id: string; name: string; governance_profile_ref: string; governance_profile_key: string }
  await page.addInitScript(() => { sessionStorage.clear(); localStorage.setItem('theme', 'light'); localStorage.setItem('mimirq.surfaceTheme', 'ocean') })
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url())
    const creatingOwnSuite = request.method() === 'POST' && url.pathname === '/api/v1/evidence/suites' && request.postDataJSON().dataset_id === state.dataset_id
    const editingOwnProfile = request.method() === 'PATCH' && url.pathname === `/api/v1/pipeline/governance-profiles/${state.governance_profile_ref}`
    const readingOwnLines = request.method() === 'POST' && url.pathname === '/api/v1/pipeline/learn-common-lines' && request.postDataJSON().dataset_id === state.dataset_id
    const previewingRules = request.method() === 'POST' && url.pathname === '/api/v1/industry-rules/preview-rewrite'
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && !creatingOwnSuite && !editingOwnProfile && !readingOwnLines && !previewingRules && !url.pathname.startsWith(`/api/v1/datasets/${state.dataset_id}/`) && !url.pathname.startsWith('/api/v1/observability/frontend')) throw new Error(`Blocked real verification write outside the dedicated dataset: ${request.method()} ${url.pathname}`)
    const headers = { ...request.headers(), 'x-user-id': state.user_id, 'x-tenant-id': state.tenant_id }
    await route.continue({ headers })
  })
  return state
}
