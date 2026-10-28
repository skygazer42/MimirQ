import type { Page, Route } from '@playwright/test'
import { remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

export async function batchTwoFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  const base = await remainingFixture(page, theme)
  const profile = { id: 'ui-profile', key: 'ui-profile', name: '产品内容清洗', is_system: false, payload: { version: '1', input_formats: ['markdown'], pipeline_patch: {}, regex_rules: [], processing_scripts: [] } as Record<string, unknown> }
  const ruleset = { name: '产品服务', glossary: { '单点登录': ['SSO', '统一认证'], '知识图谱': ['KG'] }, patterns: [{ markers: ['无法连接'], followup: '请确认连接目标', enabled: true }], intents: [{ name: '故障排查', keywords: ['失败'], route: 'support' }] }
  const state = { base, profile, ruleset, failSave: false, failLearn: false, failDocuments: false, failRules: false, writes: [] as Array<{ path: string; payload: unknown }>, previewGate: null as Promise<void> | null }
  const documents = Array.from({ length: 24 }, (_, index) => ({ id: `doc-${index}`, dataset_id: policyDatasetId, filename: index === 0 ? '很长名称的产品使用与维护手册及售后服务记录.pdf' : `产品说明-${index + 1}.pdf`, file_type: 'pdf', file_size: 1024 * (index + 1), created_at: '2026-10-27T08:00:00+08:00', updated_at: '2026-10-27T08:02:00+08:00', status: index % 4 === 0 ? 'failed' : index % 4 === 1 ? 'processing' : index % 4 === 2 ? 'pending' : 'completed', current_stage: 'parsing', processing_progress: index % 4 === 3 ? 100 : index % 4 === 2 ? 0 : 40 }))
  const json = (route: Route, value: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) })
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), p = new URL(req.url()).pathname.replace(/\/$/, ''), method = req.method()
    if (p === '/api/v1/datasets' && method === 'GET') return json(route, { total: 1, items: [{ id: policyDatasetId, name: '产品知识库', permission: 'all_team_members' }] })
    if (p === '/api/v1/documents' && method === 'GET') return state.failDocuments ? json(route, { detail: '任务目录暂不可用' }, 503) : json(route, { total: documents.length, items: documents })
    if (p === '/api/v1/observability/ingestion/summary') return json(route, { by_status: { completed: 6, processing: 6, pending: 6, failed: 6 }, bucket_minutes: 20, timeseries: [] })
    if (p === '/api/v1/observability/task-queue/snapshot') return json(route, { enabled: false, broker_up: false, recent_job_outcomes: [] })
    if (p === '/api/v1/pipeline/governance-profiles' && method === 'GET') return json(route, { total: 1, items: [profile] })
    if (p === '/api/v1/pipeline/governance-processing-scripts/builtins') return json(route, { items: [] })
    if (p === '/api/v1/pipeline/governance-profiles/ui-profile') {
      if (method === 'PATCH') { const payload = req.postDataJSON(); state.writes.push({ path: p, payload }); if (state.failSave) return json(route, { detail: '配置保存失败，请重试' }, 422); profile.payload = payload.payload }
      return json(route, profile)
    }
    if (p === '/api/v1/pipeline/learn-common-lines') {
      state.writes.push({ path: p, payload: req.postDataJSON() })
      return state.failLearn ? json(route, { detail: '正文扫描暂不可用' }, 503) : json(route, { dataset_id: policyDatasetId, used_documents: 20, total_documents: 24, candidates: [{ signature: 'copyright', sample: '版权所有，未经许可不得转载', docs: 18, ratio: 0.9 }, { signature: 'phone', sample: '售后服务热线 400-000-0000', docs: 14, ratio: 0.7 }] })
    }
    if (p === '/api/v1/industry-rules/rulesets') return json(route, { rulesets: [{ name: ruleset.name, glossary_count: Object.keys(ruleset.glossary).length, pattern_count: 1, intent_count: 1 }] })
    if (p.startsWith('/api/v1/industry-rules/rulesets/')) {
      if (method === 'PUT') {
        const payload = req.postDataJSON(); state.writes.push({ path: p, payload })
        if (state.failSave) return json(route, { detail: '规则保存失败，请重试' }, 422)
        Object.assign(ruleset, payload)
        return json(route, { updated_count: 3 })
      }
      return state.failRules ? json(route, { detail: '规则读取暂不可用' }, 503) : json(route, { ruleset })
    }
    if (p === '/api/v1/industry-rules/preview-rewrite') {
      const payload = req.postDataJSON()
      if (payload.query === '旧问题' && state.previewGate) await state.previewGate
      return json(route, { original_query: payload.query, expanded_query: `已补全：${payload.query}`, changed: true })
    }
    if (p.endsWith('/analysis/rule-suggestions')) return json(route, { glossary_suggestions: [{ token: '知识治理', count: 6, source: '产品说明.pdf' }] })
    return route.fallback()
  })
  return state
}
