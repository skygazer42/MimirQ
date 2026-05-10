import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function expectKeys(src: string, keys: string[]) {
  for (const key of keys) {
    expect(src).toContain(`t('${key}')`)
  }
}

describe('KG diagnostics quality report wiring', () => {
  it('wires the aggregate KG quality report controls and API client method', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')
    const apiClientSrc = fs.readFileSync(path.resolve(__dirname, '../../lib/api-client.ts'), 'utf8')
    const evaluationApiSrc = fs.readFileSync(path.resolve(__dirname, '../../lib/api/evaluation.ts'), 'utf8')

    expect(pageSrc).toContain("useTranslations('KGDiagnosticsPage')")
    expectKeys(pageSrc, ['qualityReport.title', 'qualityReport.hint'])
    expect(pageSrc).toContain('loadQualityReport')
    expect(pageSrc).toContain('evaluationApi.getKgQualityReport')
    expect(pageSrc).toContain('qualityPipelineHash')
    expect(apiClientSrc).toContain("export { evaluationApi } from '@/lib/api/evaluation'")
    expect(evaluationApiSrc).toContain('getKgQualityReport')
    expect(evaluationApiSrc).toContain("'/evaluations/kg/quality/report'")
  })

  it('moves KG diagnostics page scaffold actions and toast copy into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expectKeys(pageSrc, [
      'page.title',
      'page.description',
      'page.actions.refreshRuns',
      'page.actions.run',
      'page.actions.exportRun',
      'toasts.datasetRequired',
      'toasts.runsLoadFailed',
      'toasts.qualityReportLoaded',
      'toasts.qualityReportLoadFailed',
      'toasts.diagnosticsRan',
      'toasts.diagnosticsRunFailed',
      'toasts.runExported',
    ])
    expect(pageSrc).toContain("t('toasts.runLoadFailed'")
  })

  it('moves KG diagnostics run config labels and placeholders into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expectKeys(pageSrc, [
      'runConfig.title',
      'runConfig.datasetId',
      'runConfig.datasetPlaceholder',
      'runConfig.hardcaseMode',
      'runConfig.hardcaseModePlaceholder',
      'runConfig.maxCases',
      'runConfig.k',
      'runConfig.hardcasesPerFailedCase',
      'runConfig.maxFailedCasesForHardcase',
      'runConfig.llmTemperature',
      'runConfig.extractSkills',
      'runConfig.extractRelations',
      'runConfig.extractModePlaceholder',
      'runConfig.autoExtractKg',
      'runConfig.persistRun',
    ])
  })

  it('moves KG diagnostics summary and quality report controls into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expectKeys(pageSrc, [
      'summary.title',
      'summary.baselineHitRate',
      'summary.baselineMrr',
      'summary.baselineRecall',
      'summary.baselineNdcg',
      'summary.baselineMap',
      'summary.hardcasesGenerated',
      'summary.empty',
      'summary.runHint',
      'qualityReport.pull',
      'qualityReport.documentLimit',
      'qualityReport.pipelineHash',
      'qualityReport.pipelineHashPlaceholder',
    ])
  })

  it('moves KG diagnostics runs and compare copy into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expectKeys(pageSrc, [
      'runs.title',
      'runs.refresh',
      'runs.hint',
      'runs.runA',
      'runs.runAPlaceholder',
      'runs.loadA',
      'runs.runB',
      'runs.runBPlaceholder',
      'runs.loadB',
      'compare.title',
      'compare.export',
      'compare.exported',
      'compare.hitFlips',
      'compare.summaryKeys',
      'compare.empty',
      'compare.diffJson',
      'compare.diffHint',
      'compare.changedCases',
      'compare.noQuestion',
    ])
  })

  it('uses a dashboard cockpit layout for the run tab that matches the design reference', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('DiagnosticsHeaderPill')
    expect(pageSrc).toContain('DiagnosticsRunHeroPanel')
    expect(pageSrc).toContain('DiagnosticsFailuresPanel')
    expect(pageSrc).toContain('DiagnosticsRunRecordsPanel')
    expect(pageSrc).toContain('rounded-[18px] border border-border/70 bg-background/95')
    expect(pageSrc).toContain('xl:grid-cols-[356px_minmax(0,1fr)]')
    expect(pageSrc).toContain('xl:grid-cols-6')
  })

  it('keeps the diagnostics run view sized to the supplied 2048px dashboard reference', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('min-h-[160px]')
    expect(pageSrc).toContain('min-h-[280px]')
    expect(pageSrc).toContain('px-6 py-5')
    expect(pageSrc).toContain('gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]')
  })

  it('keeps metric tiles compact and centered inside each card', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('min-h-[112px] flex-col items-center justify-center')
    expect(pageSrc).toContain('px-3.5 py-3 text-center')
    expect(pageSrc).toContain('items-center justify-center gap-1.5')
    expect(pageSrc).toContain("mt-3 text-[17px]")
    expect(pageSrc).toContain("mt-2 text-[11px] leading-5")
    expect(pageSrc).not.toContain("mt-auto pt-3 text-[11px] leading-5")
  })

  it('shows a hover and keyboard tooltip for the threshold setting help icon', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('function DiagnosticsInfoTooltip')
    expect(pageSrc).toContain("from '@/components/ui/tooltip'")
    expect(pageSrc).toContain('<TooltipProvider delayDuration={120}>')
    expect(pageSrc).toContain('label="查看阈值设置说明"')
    expect(pageSrc).toContain('aria-label={label}')
    expect(pageSrc).toContain('hover:bg-sky-50 hover:text-sky-700')
    expect(pageSrc).toContain('focus-visible:ring-2 focus-visible:ring-sky-300')
    expect(pageSrc).toContain('控制本轮最多抽取多少条评测样本')
    expect(pageSrc).toContain('查看失败样本与错误分析说明')
    expect(pageSrc).toContain('展示本轮未命中的评测样本')
    expect(pageSrc).toContain('查看原始结果与运行记录说明')
    expect(pageSrc).toContain('显示最近保存的评测运行记录')
  })

  it('binds diagnostics to an actual dataset option instead of a freeform dataset id input', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('datasetApi.list({ limit: 200 })')
    expect(pageSrc).toContain('const selectedDataset')
    expect(pageSrc).toContain('setDatasets(items)')
    expect(pageSrc).toContain('setDatasetId((current)')
    expect(pageSrc).toContain("String(items[0]?.id || '').trim()")
    expect(pageSrc).toContain('<Select value={datasetId} onValueChange={handleDatasetChange}')
    expect(pageSrc).toContain('dataset.name || id')
    expect(pageSrc).toContain('dataset_id: ds')
    expect(pageSrc).not.toContain('datasetId || undefined')
    expect(pageSrc).not.toContain('placeholder={datasetLabel}')
  })

  it('resets dataset-scoped results when switching the bound dataset', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('function handleDatasetChange(nextDatasetId: string): void')
    expect(pageSrc).toContain('setDatasetId(nextDatasetId)')
    expect(pageSrc).toContain('setRunResp(null)')
    expect(pageSrc).toContain('setQualityReport(null)')
    expect(pageSrc).toContain("setQualityPipelineHash('')")
    expect(pageSrc).toContain('setRuns([])')
    expect(pageSrc).toContain('setDetailA(null)')
    expect(pageSrc).toContain('setDetailB(null)')
    expect(pageSrc).toContain("setActiveView('run')")
  })

  it('keeps KG diagnostics backed by real evaluation APIs instead of local mock data', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('evaluationApi.runKgSearchDiagnostics')
    expect(pageSrc).toContain('evaluationApi.listKgSearchDiagnosticsRuns')
    expect(pageSrc).toContain('evaluationApi.getKgSearchDiagnosticsRun')
    expect(pageSrc).toContain('evaluationApi.getKgQualityReport')
    expect(pageSrc).not.toMatch(/buildDemo|mock[A-Z]|Mock|fake/i)
  })

  it('keeps the diagnostics sidebar typography soft for Chinese form labels', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('DIAGNOSTICS_SECTION_TITLE_CLASS')
    expect(pageSrc).toContain('DIAGNOSTICS_FIELD_LABEL_CLASS')
    expect(pageSrc).toContain('DIAGNOSTICS_FIELD_VALUE_CLASS')
    expect(pageSrc).toContain("tracking-normal text-foreground/85")
  })

  it('keeps diagnostics actions in Chinese while preserving standard metric acronyms', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')
    const messagesSrc = fs.readFileSync(path.resolve(__dirname, '../../i18n/messages/zh-CN.ts'), 'utf8')

    expect(pageSrc).toContain('最新结果')
    expect(pageSrc).toContain('Recall {String(item.recall)} · MRR {String(item.mrr)}')
    expect(pageSrc).toContain('原始结果 / 运行记录')
    expect(pageSrc).toContain('运行 ID')
    expect(pageSrc).toContain('TOP-K')
    expect(pageSrc).toContain('查看原始数据')
    expect(pageSrc).toContain('展开原始数据')
    expect(pageSrc).toContain('LLM 生成')
    expect(pageSrc).toContain("low_confidence_relations: '低置信关系数'")
    expect(pageSrc).toContain("documents_sampled: '抽样文档数'")
    expect(pageSrc).toContain('label="样本"')
    expect(pageSrc).toContain("value={persistRun ? '开启' : '关闭'}")
    expect(pageSrc).toContain('formatDiagnosticsMetricLabel(key)')
    expect(messagesSrc).toContain("pipelineHash: '流水线版本标识（可选）'")
    expect(messagesSrc).not.toContain('指定 pipeline_hash（可选）')
    expect(pageSrc).not.toContain('LATEST RESULT')
    expect(pageSrc).not.toContain('Run ID')
    expect(pageSrc).not.toContain('PERSIST')
    expect(pageSrc).not.toContain('大模型生成')
  })
})
