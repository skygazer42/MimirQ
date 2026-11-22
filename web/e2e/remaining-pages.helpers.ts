import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import type { DatasetProfileSummary, DatasetProfileScanRunOut } from '../types'
import { datasetPolicyFixture, policyDatasetId } from './dataset-policy.helpers'
import { precheckSummary } from './precheck-workspace.helpers'
import { installRemainingRuntimeDiagnostics, saveRemainingRuntimeFailure } from './remaining-runtime.helpers'

export const remainingEvidence = path.resolve(__dirname, '../../artifacts/rebrand/remaining-pages-2026-10-27')
export const datasetRoute = (page: string) => `/datasets/${policyDatasetId}/${page}`
export function profileSummary(): DatasetProfileSummary {
  const precheck = precheckSummary()
  return {
    dataset_id: precheck.dataset_id,
    generated_at: precheck.generated_at,
    total_documents: precheck.total_files,
    total_size_bytes: precheck.total_size_bytes,
    by_status: { completed: 120, failed: 5, quarantined: 3 },
    by_file_type: precheck.by_file_type,
    by_directory: {},
    by_quality_bucket: {},
    file_size_histogram: precheck.file_size_histogram.map((bin) => ({
      ...bin,
      min: bin.min ?? null,
      max: bin.max ?? null,
    })),
    length_percentiles: precheck.length_percentiles,
    length_histogram: precheck.length_histogram.map((bin) => ({ ...bin, min: bin.min ?? null, max: bin.max ?? null })),
    chunk_count_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    chunk_count_histogram: [],
    avg_chunk_chars_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    avg_chunk_chars_histogram: [],
    chunk_length_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    chunk_length_histogram: [],
    chunk_token_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    chunk_token_histogram: [],
    avg_chunk_tokens_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    avg_chunk_tokens_histogram: [],
    chunk_coverage_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    chunk_coverage_histogram: [],
    chunk_overlap_waste_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    chunk_overlap_waste_histogram: [],
    page_number_histogram: [],
    parse_quality_histogram: [],
    language_mix: {},
    pdf_scan: precheck.pdf_scan,
    parsing_provenance: {
      docs_with_provenance: 0,
      by_resolved_backend: {},
      fallback_docs: 0,
      elapsed_ms_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    },
    pii_hits_total: precheck.pii_hits_total,
    secrets_hits_total: precheck.secrets_hits_total,
    findings: precheck.findings.map((finding) => ({ ...finding, description: finding.description ?? null })),
    recall_risk_hints: [],
    chunk_targets: [],
    latest_scan_run: null,
  }
}
async function json(route: Route, data: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
}
export async function remainingFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await page.route('**/api/v1/**', async (route) => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method()))
      return json(route, { detail: '操作服务暂不可用' }, 503)
    return route.fallback()
  })
  await installRemainingRuntimeDiagnostics(page)
  const base = await datasetPolicyFixture(page, theme)
  const state = {
    base,
    failProfile: false,
    failHealth: false,
    failHistory: false,
    profile: profileSummary(),
    scanRuns: [] as DatasetProfileScanRunOut[],
    writes: [] as string[],
  }
  state.scanRuns = ['profile-scan-new', 'profile-scan-old'].map((id) => ({
    id,
    tenant_id: 'tenant-e2e',
    dataset_id: policyDatasetId,
    kind: 'profile',
    status: 'completed',
    progress: 100,
    requested_by: null,
    created_at: state.profile.generated_at,
    started_at: state.profile.generated_at,
    finished_at: state.profile.generated_at,
    updated_at: state.profile.generated_at,
    error_message: null,
    config: {},
    summary: state.profile,
  }))
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url()),
      p = url.pathname.replace(/\/$/, '')
    if (p === `/api/v1/datasets/${policyDatasetId}/profile/summary`)
      return state.failProfile ? json(route, { detail: '画像读取暂不可用' }, 503) : json(route, state.profile)
    if (p === `/api/v1/datasets/${policyDatasetId}/profile/scan-runs`)
      return state.failHistory
        ? json(route, { detail: '扫描历史读取暂不可用' }, 503)
        : json(route, { total: state.scanRuns.length, items: state.scanRuns })
    if (p === `/api/v1/datasets/${policyDatasetId}/health`)
      return state.failHealth
        ? json(route, { detail: '健康概览暂不可用' }, 503)
        : json(route, {
            dataset_id: policyDatasetId,
            generated_at: state.profile.generated_at,
            profile: state.profile,
            ingestion: {
              total_documents: 128,
              pending: 0,
              processing: 0,
              completed: 120,
              failed: 5,
              quarantined: 3,
              cancelled: 0,
              by_status: state.profile.by_status,
            },
          })
    if (p.includes(`/api/v1/datasets/${policyDatasetId}/profile/findings/`))
      return json(route, {
        total: 1,
        items: [
          {
            id: '56b974c6-26f6-4890-b26f-10752ea61111',
            dataset_id: policyDatasetId,
            filename: 'product-guide.pdf',
            file_type: 'pdf',
            file_size: 4096,
            status: 'completed',
            chunk_count: 0,
            total_characters: 0,
            created_at: state.profile.generated_at,
            updated_at: state.profile.generated_at,
            error_message: null,
            metadata: {},
            preview: null,
            preview_truncated: false,
          },
        ],
      })
    if (p === `/api/v1/datasets/${policyDatasetId}/config/export`)
      return json(route, {
        version: '1',
        dataset_id: policyDatasetId,
        config: {
          default_parser_backend: 'auto',
          default_chunk_strategy: 'default',
          pipeline: {},
          ingestion_policy: null,
          rag_defaults: null,
        },
      })
    if (
      p === `/api/v1/datasets/${policyDatasetId}/tables` ||
      p === `/api/v1/datasets/${policyDatasetId}/db-catalog/tables`
    )
      return json(route, { total: 0, items: [] })
    if (p === '/api/v1/evidence/suites' || p === '/api/v1/connectors/runs') return json(route, { total: 0, items: [] })
    return route.fallback()
  })
  return state
}
export async function openRemaining(page: Page, url: string, title: string) {
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  try {
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible({ timeout: 60000 })
  } catch (error) {
    await saveRemainingRuntimeFailure(page, remainingEvidence)
    throw error
  }
}
export async function remainingShot(page: Page, name: string) {
  const root = path.join(remainingEvidence, 'screens')
  fs.mkdirSync(root, { recursive: true })
  await page.screenshot({ path: path.join(root, `${name}.png`), animations: 'disabled' })
  fs.writeFileSync(
    path.join(root, `${name}.html`),
    (await page.content())
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
      .replace(/\b(href|src)="\/(?!\/)/g, '$1="http://127.0.0.1:3000/'),
  )
}

export async function realDatasetFixture(page: Page) {
  await installRemainingRuntimeDiagnostics(page)
  const baseURL = test.info().project.use.baseURL
  const api = (endpoint: string) => new URL(`/api/v1${endpoint}`, baseURL).href
  const meta = await page.request.get(api('/meta'))
  await expect(meta).toBeOK()
  expect((await meta.json()).features.auth_mode).toBe('header')

  const userId = 'playwright-ragvia'
  const headers = { 'X-User-ID': userId }
  await expect(await page.request.get(api('/datasets/'), { headers })).toBeOK()
  const suffix = randomUUID().slice(0, 8)
  const dataset = await page.request.post(api('/datasets/'), {
    headers,
    data: { name: `ui-redesign-verification-${suffix}` },
  })
  await expect(dataset).toBeOK()
  const { id, tenant_id: tenantId, name } = await dataset.json()
  const profile = await page.request.post(api('/pipeline/governance-profiles'), {
    headers,
    data: { key: `ui-profile-${suffix}`, name: `测试治理配置 ${suffix}`, payload: {} },
  })
  await expect(profile).toBeOK()
  const { id: profileId, key: profileKey } = await profile.json()
  const state = {
    user_id: userId,
    tenant_id: tenantId,
    dataset_id: id,
    name,
    governance_profile_ref: profileId,
    governance_profile_key: profileKey,
  }
  await page.addInitScript(() => {
    sessionStorage.clear()
    localStorage.setItem('theme', 'light')
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
  })
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(),
      url = new URL(request.url())
    const creatingOwnSuite =
      request.method() === 'POST' &&
      url.pathname === '/api/v1/evidence/suites' &&
      request.postDataJSON().dataset_id === state.dataset_id
    const editingOwnProfile =
      request.method() === 'PATCH' &&
      url.pathname === `/api/v1/pipeline/governance-profiles/${state.governance_profile_ref}`
    const readingOwnLines =
      request.method() === 'POST' &&
      url.pathname === '/api/v1/pipeline/learn-common-lines' &&
      request.postDataJSON().dataset_id === state.dataset_id
    const previewingRules = request.method() === 'POST' && url.pathname === '/api/v1/industry-rules/preview-rewrite'
    if (
      !['GET', 'HEAD', 'OPTIONS'].includes(request.method()) &&
      !creatingOwnSuite &&
      !editingOwnProfile &&
      !readingOwnLines &&
      !previewingRules &&
      !url.pathname.startsWith(`/api/v1/datasets/${state.dataset_id}/`) &&
      !url.pathname.startsWith('/api/v1/observability/frontend')
    )
      throw new Error(
        `Blocked real verification write outside the dedicated dataset: ${request.method()} ${url.pathname}`,
      )
    const headers = { ...request.headers(), 'x-user-id': state.user_id, 'x-tenant-id': state.tenant_id }
    await route.continue({ headers })
  })
  return state
}
