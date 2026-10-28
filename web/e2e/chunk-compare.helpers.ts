import { expect, type Page, type Route } from '@playwright/test'
import type { ChunkPreviewResponse } from '../types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const sections = [
  '# 设备维护手册\n\n设备维护前应核对设备编号、作业范围和操作人员。关闭电源后再进行检查，保留本次操作的记录。',
  '## 日常检查\n\n作业前检查紧固件、防护装置和电源连接。发现松动、异常声音或管路渗漏时，应暂停运行并安排复核。\n\n| 项目 | 要求 |\n| --- | --- |\n| 电源 | 检查接线 |\n| 防护装置 | 确认完整 |',
  '## 保养记录\n\n完成日常检查后，填写维护日期、设备编号、检查人员及处理意见。记录应与本次检查项目逐项对应，并由复核人员确认。',
]
export const original = sections.join('\n\n')
const second = '# 安全操作规范\n\n进入作业区域前，核对安全要求和作业许可。'

export async function json(route: Route, body: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }) }

export async function fixture(page: Page, options: { empty?: boolean; long?: boolean; gaps?: boolean } = {}) {
  await page.setViewportSize({ width: 1600, height: 1000 })
  const sourceSections = options.long ? Array.from({ length: 14 }, (_, index) => `## 检查项目 ${index + 1}\n\n${'检查前请核对设备编号、作业范围和操作人员，保留本次操作的完整记录。'.repeat(7)}\n\n| 检查项 | 处理要求 |\n| --- | --- |\n| 项目 ${index + 1} | ${'确认设备状态、核对本次维护记录。'.repeat(6)} |\n| 复核要求 | 完成检查后由复核人员确认 |`) : sections
  const sourceText = sourceSections.join('\n\n')
  const documents = options.empty ? [] : [
    { id: 'chunk-document-1', filename: '设备维护手册.md', file_type: 'md', file_size: 2084, status: 'completed', created_at: '2026-10-25T01:00:00Z', updated_at: '2026-10-25T01:00:00Z', error_message: null },
    { id: 'chunk-document-2', filename: '安全操作规范.md', file_type: 'md', file_size: 1024, status: 'completed', created_at: '2026-10-25T01:00:00Z', updated_at: '2026-10-25T01:00:00Z', error_message: null },
  ]
  const state = { documents, failPreview: false, failIngest: false, previewBodies: [] as string[], previewQueries: [] as Record<string,string>[], ingestBodies: [] as Array<{ chunks: Array<{ content: string; metadata: Record<string, unknown> }>; metadata: Record<string, unknown> }>, saved: null as null | Record<string, unknown>, holdPreview: null as Promise<void> | null, previewStarted: 0 }
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: documents })
  await page.addInitScript(() => {
    if (!localStorage.getItem('theme')) localStorage.setItem('theme', 'light')
    if (!localStorage.getItem('mimirq.surfaceTheme')) localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.setItem('mimirq.themeColor', '#20262e')
    document.addEventListener('DOMContentLoaded', () => { const style = document.createElement('style'); style.textContent = 'nextjs-portal{display:none!important}'; document.head.appendChild(style) }, { once: true })
  })
  await page.route('**/api/v1/parsing/documents**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/content')) {
      const id = url.pathname.split('/documents/')[1].split('/')[0]
      const markdown = id.endsWith('-2') ? second : sourceText
      return json(route, { document_id: id, parser_backend: 'markdown', markdown_content: markdown, original_markdown_content: markdown })
    }
    return json(route, { total: state.documents.length, items: state.documents })
  })
  await page.route('**/api/v1/pipeline/capabilities', route => json(route, { default_pdf_backend: 'auto', default_chunk_strategy: 'langchain_recursive', chunk_strategies: ['langchain_recursive','langchain_token','separator'].map(name => ({ name, available: true, requires: [] })), pdf_backends: [{ name: 'markdown', available: true }] }))
  await page.route('**/api/v1/documents/chunk-preview**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const body = request.postDataBuffer()?.toString('utf8') || ''
    state.previewStarted++
    state.previewBodies.push(body)
    state.previewQueries.push(Object.fromEntries(url.searchParams))
    const held = state.holdPreview
    if (held) await held
    if (state.failPreview) return json(route, { detail: '切块服务暂不可用' }, 503)
    const isSecond = body.includes('安全操作规范')
    const text = isSecond ? second : sourceText
    const content = isSecond ? [second] : sourceSections
    const size = Number(url.searchParams.get('chunk_size') || 1000)
    const overlap = Number(url.searchParams.get('chunk_overlap') || 200)
    const strategy = body.match(/name="chunk_strategy"\r\n\r\n([^\r\n]+)/)?.[1] || 'langchain_recursive'
    const chunks = content.map((value,index) => ({ index, content: value, length: value.length, start_index: text.indexOf(value), end_index: text.indexOf(value) + value.length, metadata: { header_path: index === 1 ? '设备维护手册 / 日常检查' : index === 2 ? '设备维护手册 / 保养记录' : isSecond ? '安全操作规范' : '设备维护手册', needs_review: true, semantic_quality: { needs_review: true, reasons: ['incomplete'] } } }))
    const preview: ChunkPreviewResponse = { filename: isSecond ? '安全操作规范.md' : '设备维护手册.md', file_type: 'md', file_size: text.length, parse_cache_hit: false, total_chunks: chunks.length, total_chunks_full: chunks.length, chunks_truncated: false, chunks_max_count: 2000, total_characters: text.length, params: { chunk_size: size, chunk_overlap: overlap, unit: strategy === 'langchain_token' ? 'tokens' : 'chars' }, chunks, original_text: text, original_text_included: true, original_text_truncated: false, original_text_max_chars: 100000, parser_backend: 'markdown', chunk_strategy: strategy, preview_duration_ms: 50 }
    if (options.gaps) {
      preview.stats = { count: chunks.length, avg: Math.round(text.length / chunks.length), p95: Math.max(...chunks.map(chunk => chunk.length)), coverage_ratio: (text.length - 4) / text.length, overlap_waste_ratio: 0, gap_count: 2, largest_gap: 2 }
      preview.review_signals = { basis: 'all', gap_indices: [1, 2], gap_before_by_index: { '1': 2, '2': 2 } }
    }
    return json(route, preview)
  })
  await page.route('**/api/v1/documents/manual', async route => {
    const body = route.request().postDataJSON()
    state.ingestBodies.push(body)
    if (state.failIngest) return json(route, { detail: '入库服务暂不可用' }, 503)
    state.saved = { ...body, id: 'ingested-document', status: 'completed' }
    return json(route, state.saved)
  })
  await page.route('**/api/v1/documents/ingested-document', route => json(route, state.saved || {}, state.saved ? 200 : 404))
  return state
}

export async function open(page: Page, empty = false) {
  await page.goto('/chunk-preview', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '切块预览', exact: true })).toBeVisible({ timeout: 60_000 })
  if (!empty) await expect(page.locator('[data-chunk-card]')).toHaveCount(3)
  await page.evaluate(() => document.fonts.ready)
}
export async function noOverflow(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1) }
