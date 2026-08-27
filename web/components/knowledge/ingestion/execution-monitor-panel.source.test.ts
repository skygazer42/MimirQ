import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string) {
  return fs.readFileSync(path.resolve(process.cwd(), relativePath), 'utf8')
}

describe('execution monitor visual contracts', () => {
  it('uses a dedicated compact file-type summary instead of reusing the batch profile chart', () => {
    const src = read('components/knowledge/ingestion/execution-monitor-panel.tsx')
    const profileCharts = src.match(/<EChart option=\{batchProfileBarOption\} \/>/g) ?? []

    expect(src).toContain('data-execution-file-type-summary="true"')
    expect(src).toContain('data-monitor-chart="file-type-donut"')
    expect(src).toContain('<EChart option={fileTypeDonutOption} />')
    expect(profileCharts).toHaveLength(1)
    expect(src).toContain('function CompactEmptyVisual(')
    expect(src).toContain('data-execution-empty-visual="true"')
  })

  it('keeps analytical charts visible without inventing business data', () => {
    const panel = read('components/knowledge/ingestion/execution-monitor-panel.tsx')
    const page = read('app/knowledge/ingestion/page-client.tsx')

    expect(panel).toContain('data-monitor-chart="throughput-line"')
    expect(panel).toContain('data-monitor-chart="cost-radar"')
    expect(panel).toContain('data-monitor-analytics-grid="true"')
    expect(panel.match(/<section className="min-w-0/g) ?? []).toHaveLength(3)
    expect(panel).toContain('<EChart option={predictionOption} />')
    expect(panel).toContain('<EChart option={radarOption} />')
    expect(page).toContain('const hasActualSeries = actualSeries.length > 0')
    expect(page).toContain("data: ['-60m', '-45m', '-30m', '-15m', '现在']")
    expect(panel).not.toContain('Math.random')
  })

  it('keeps monitor actions in the Ocean information hierarchy', () => {
    const hero = read('components/knowledge/ingestion/ingestion-hero-panel.tsx')
    const operation = read('app/knowledge/ingestion/operation-page-client.tsx')
    const switchSource = read('app/knowledge/ingestion/view-switch.tsx')
    const rail = read('components/knowledge/ingestion/desktop-audit-rail.tsx')

    expect(hero).toContain('data-monitor-scope-control="true"')
    expect(hero).toContain('<IngestionViewSwitch compact tone="info" />')
    expect(operation).toContain('<IngestionViewSwitch compact tone="info" />')
    expect(hero).toContain('border-info/25 bg-info/5')
    expect(hero).toContain('text-[11px] text-info')
    expect(switchSource).toContain("tone?: 'default' | 'info'")
    expect(switchSource).toContain("tone === 'info'")
    expect(rail).not.toContain('[writing-mode:vertical-rl]')
    expect(rail).not.toContain('展开运行范围侧栏')
  })

  it('separates run state from quality metrics and collapses an empty batch to one message', () => {
    const panel = read('components/knowledge/ingestion/execution-monitor-panel.tsx')
    const page = read('app/knowledge/ingestion/page-client.tsx')

    expect(panel).toContain('data-monitor-run-strip="true"')
    expect(panel).toContain('data-monitor-quality-kpis="true"')
    expect(panel).toContain('data-monitor-empty-batch="true"')
    expect(page).not.toContain('...executionRunStateCards,')
  })

  it('renders the actual ingestion stages instead of textual runtime context cards', () => {
    const panel = read('components/knowledge/ingestion/execution-monitor-panel.tsx')
    const page = read('app/knowledge/ingestion/page-client.tsx')

    expect(panel).toContain('data-monitor-pipeline-visual="true"')
    expect(panel).toContain('data-monitor-pipeline-stage="true"')
    expect(panel).toContain('executionPipelineCards.map')
    expect(panel).toContain('PIPELINE_STAGE_ICONS')
    expect(panel).not.toContain('executionRunStateCards')
    expect(page).toContain('executionPipelineCards={executionPipelineCards}')
    expect(page).toContain('executionOverallProgress={executionOverallProgress}')
    expect(page).toContain('executionPipelineEstimateLabel={executionPipelineState.estimateLabel}')
    expect(page).not.toContain('executionRunStateCards')
    for (const stage of ["label: '解析'", "label: '切块'", "label: '治理'", "label: '索引'"]) {
      expect(page).toContain(stage)
    }
  })

  it('uses the compact spacing scale for the monitor canvas', () => {
    const panel = read('components/knowledge/ingestion/execution-monitor-panel.tsx')
    const page = read('app/knowledge/ingestion/page-client.tsx')

    expect(panel).toContain('data-monitor-overview-band="true"')
    expect(panel).toContain('grid items-stretch border-y border-foreground/15')
    expect(panel).toContain('border-b border-foreground/15 px-3 py-3')
    expect(page).toContain("'px-2 pb-5 pt-1.5 md:px-3'")
  })

  it('keeps the monitor header in document flow and uses flat ruled surfaces', () => {
    const panel = read('components/knowledge/ingestion/execution-monitor-panel.tsx')
    const page = read('app/knowledge/ingestion/page-client.tsx')

    expect(page).toContain("mode === 'execution-monitor' ? 'relative z-20' : 'sticky top-3 z-30'")
    expect(page).toContain("mode === 'execution-monitor' ? 'bg-info/[0.025] dark:bg-background' : INGESTION_BACKGROUND_CLASS")
    expect(panel).toContain('data-monitor-flat-canvas="true"')
    expect(panel).toContain('data-monitor-boundary-system="ruled"')
    expect(panel).toContain('data-monitor-visual-tone="enterprise"')
    expect(panel).toContain('data-monitor-overview-band="true"')
    expect(panel).toContain('data-monitor-flat-section="quality"')
    expect(panel).not.toContain('overflow-hidden rounded-xl border border-border/55 bg-background/82')
    expect(panel).not.toContain('text-[8px]')
    expect((panel.match(/border-foreground\/15/g) ?? []).length).toBeGreaterThanOrEqual(4)
    expect((panel.match(/border-foreground\/10/g) ?? []).length).toBeGreaterThanOrEqual(4)
    expect(panel).not.toContain('PIPELINE_STAGE_ACCENTS')
    expect(panel).not.toContain('bg-accent/10 text-accent ring-accent/20')
  })

  it('uses theme-neutral chart surfaces and removes hard-coded white radar bands', () => {
    const panel = read('components/knowledge/ingestion/execution-monitor-panel.tsx')
    const page = read('app/knowledge/ingestion/page-client.tsx')

    expect(panel).not.toContain('bg-card/86')
    expect(page).not.toContain("rgba(248,250,252,0.82)")
    expect(page).not.toContain("rgba(241,245,249,0.46)")
  })
})
