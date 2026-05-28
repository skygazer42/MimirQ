import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('diagnostics page accessibility labels', () => {
  it('uses section-specific aria-labels for icon-only copy and refresh actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('aria-label="刷新诊断状态"')
    expect(src).toContain('aria-label="复制原始响应 JSON"')
    expect(src).not.toContain('aria-label="复制"')
    expect(src).not.toContain('aria-label="刷新"')
    expect(src).not.toContain('aria-label="复制 Frontend Env JSON"')
    expect(src).not.toContain('前端环境变量')
    expect(src).not.toContain('高级明细探针')
    expect(src).not.toContain('性能快照')
    expect(src).not.toContain('浏览器存储与缓存')
    expect(src).not.toContain('构建包提示')
  })

  it('does not expose backend integration workbench on the operator diagnostics page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain('BackendInterfaceWorkbench')
    expect(src).not.toContain('后端接口闭环工作台')
    expect(src).not.toContain('Dataset Analysis')
    expect(src).not.toContain('Lineage / RTBF')
    expect(src).not.toContain('Clean DOCX')
    expect(src).not.toContain('/docs')
    expect(src).not.toContain('openapi.json')
    expect(src).not.toContain('接口联调')
  })

  it('keeps raw diagnostic material collapsed and removes dead detail entries', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('<RawDiagnosticsDetails')
    expect(src).toContain('<details className=')
    expect(src).toContain('查看原始响应')
    expect(src).toContain('排障摘要')
    expect(src).not.toContain('后端输出')
    expect(src).not.toContain('更多明细')
    expect(src).not.toContain('FooterCollapsible')
  })

  it('maps backend drift snapshot fields into executed result labels', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("'above_threshold.ratio'")
    expect(src).toContain('driftStatusLabel')
    expect(src).toContain('执行结果')
    expect(src).toContain('漂移检查')
  })

  it('explains diagnostics purpose and metric meanings with hover help', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('function DiagnosticUseGuide')
    expect(src).toContain('RAG 预览看召回')
    expect(src).toContain('漂移检查看重嵌入风险')
    expect(src).toContain('function MetricInfoTooltip')
    expect(src).toContain('TooltipContent')
    expect(src).toContain('样本未发现漂移')
    expect(src).toContain('多少条可引用证据')
  })

  it('uses theme tokens for the RAG preview action instead of fixed blue colors', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('data-rag-preview-action="true"')
    expect(src).toContain('bg-primary text-primary-foreground hover:bg-primary/90')
    expect(src).toContain('border-primary/15 bg-primary/10 text-primary')
    expect(src).toContain('text-[10px] font-semibold text-primary')
    expect(src).not.toContain('h-9 flex-1 bg-blue-600 text-[13px] font-semibold hover:bg-blue-700')
    expect(src).not.toContain('rounded-2xl border border-blue-100/70 bg-gradient-to-r from-blue-50/90 via-white to-sky-50/80')
    expect(src).not.toContain('border border-blue-100 bg-blue-50 text-blue-600')
    expect(src).not.toContain('<p className="mt-0.5 text-[10px] font-semibold text-blue-600">')
  })
})
