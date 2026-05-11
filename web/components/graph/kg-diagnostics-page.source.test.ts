import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
  readMessageCatalogSource,
} from '@/lib/source-test-utils'

function expectKeys(src: string, keys: string[]) {
  for (const key of keys) {
    expectSourceToContain(src, `t('${key}')`)
  }
}

describe('KG diagnostics quality report wiring', () => {
  it('wires the aggregate KG quality report controls and API client method', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )
    const apiClientSrc = fs.readFileSync(
      path.resolve(__dirname, '../../lib/api-client.ts'),
      'utf8'
    )
    const evaluationApiSrc = fs.readFileSync(
      path.resolve(__dirname, '../../lib/api/evaluation.ts'),
      'utf8'
    )

    expectSourceToContain(pageSrc, "useTranslations('KGDiagnosticsPage')")
    expectKeys(pageSrc, ['qualityReport.title', 'qualityReport.hint'])
    expectSourceToContain(pageSrc, 'loadQualityReport')
    expectSourceToContain(pageSrc, 'evaluationApi.getKgQualityReport')
    expectSourceToContain(pageSrc, 'qualityPipelineHash')
    expectSourceToContain(
      apiClientSrc,
      "export { evaluationApi } from '@/lib/api/evaluation'"
    )
    expectSourceToContain(evaluationApiSrc, 'getKgQualityReport')
    expectSourceToContain(evaluationApiSrc, "'/evaluations/kg/quality/report'")
  })

  it('moves KG diagnostics page scaffold actions and toast copy into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

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
    expectSourceToContain(pageSrc, "t('toasts.runLoadFailed'")
  })

  it('moves KG diagnostics run config labels and placeholders into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

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
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

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
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

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
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

    expectSourceToContain(pageSrc, 'DiagnosticsHeaderPill')
    expectSourceToContain(pageSrc, 'DiagnosticsRunHeroPanel')
    expectSourceToContain(pageSrc, 'DiagnosticsFailuresPanel')
    expectSourceToContain(pageSrc, 'DiagnosticsRunRecordsPanel')
    expectSourceToContain(
      pageSrc,
      'rounded-[18px] border border-border/70 bg-background/95'
    )
    expectSourceToContain(pageSrc, 'xl:grid-cols-[356px_minmax(0,1fr)]')
    expectSourceToContain(pageSrc, 'xl:grid-cols-6')
  })

  it('keeps the diagnostics run view sized to the supplied 2048px dashboard reference', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

    expectSourceToContain(pageSrc, 'min-h-[160px]')
    expectSourceToContain(pageSrc, 'min-h-[280px]')
    expectSourceToContain(pageSrc, 'px-6 py-5')
    expectSourceToContain(
      pageSrc,
      'gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]'
    )
  })

  it('keeps metric tiles compact and centered inside each card', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

    expectSourceToContain(
      pageSrc,
      'min-h-[112px] flex-col items-center justify-center'
    )
    expectSourceToContain(pageSrc, 'px-3.5 py-3 text-center')
    expectSourceToContain(pageSrc, 'items-center justify-center gap-1.5')
    expectSourceToContain(pageSrc, 'mt-3 text-[17px]')
    expectSourceToContain(pageSrc, 'mt-2 text-[11px] leading-5')
    expectSourceNotToContain(pageSrc, 'mt-auto pt-3 text-[11px] leading-5')
  })

  it('shows a hover and keyboard tooltip for the threshold setting help icon', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

    expectSourceToContain(pageSrc, 'function DiagnosticsInfoTooltip')
    expectSourceToContain(pageSrc, "from '@/components/ui/tooltip'")
    expectSourceToContain(pageSrc, '<TooltipProvider delayDuration={120}>')
    expectSourceToContain(pageSrc, 'label="查看阈值设置说明"')
    expectSourceToContain(pageSrc, 'aria-label={label}')
    expectSourceToContain(pageSrc, 'hover:bg-sky-50 hover:text-sky-700')
    expectSourceToContain(
      pageSrc,
      'focus-visible:ring-2 focus-visible:ring-sky-300'
    )
    expectSourceToContain(pageSrc, '控制本轮最多抽取多少条评测样本')
    expectSourceToContain(pageSrc, '查看失败样本与错误分析说明')
    expectSourceToContain(pageSrc, '展示本轮未命中的评测样本')
    expectSourceToContain(pageSrc, '查看原始结果与运行记录说明')
    expectSourceToContain(pageSrc, '显示最近保存的评测运行记录')
  })

  it('binds diagnostics to an actual dataset option instead of a freeform dataset id input', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

    expectSourceToContain(
      pageSrc,
      'const KG_DIAGNOSTICS_DATASET_LIST_PARAMS = { limit: 200 } as const'
    )
    expectSourceToContain(
      pageSrc,
      'queryKey: queryKeys.datasets.list(KG_DIAGNOSTICS_DATASET_LIST_PARAMS)'
    )
    expectSourceToContain(
      pageSrc,
      'queryFn: () => datasetApi.list(KG_DIAGNOSTICS_DATASET_LIST_PARAMS)'
    )
    expectSourceToContain(pageSrc, 'const datasets = useMemo')
    expectSourceToContain(pageSrc, 'const selectedDataset')
    expectSourceToContain(pageSrc, 'setDatasetId((current)')
    expectSourceToContain(pageSrc, "String(datasets[0]?.id || '').trim()")
    expectSourceToContain(
      pageSrc,
      '<Select value={datasetId} onValueChange={handleDatasetChange}'
    )
    expectSourceToContain(pageSrc, 'dataset.name || id')
    expectSourceToContain(pageSrc, 'dataset_id: ds')
    expectSourceNotToContain(pageSrc, 'datasetId || undefined')
    expectSourceNotToContain(pageSrc, 'placeholder={datasetLabel}')
  })

  it('resets dataset-scoped results when switching the bound dataset', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

    expectSourceToContain(
      pageSrc,
      'function handleDatasetChange(nextDatasetId: string): void'
    )
    expectSourceToContain(pageSrc, 'setDatasetId(nextDatasetId)')
    expectSourceToContain(pageSrc, 'setRunResp(null)')
    expectSourceToContain(pageSrc, 'setQualityReport(null)')
    expectSourceToContain(pageSrc, "setQualityPipelineHash('')")
    expectSourceToContain(pageSrc, 'setRuns([])')
    expectSourceToContain(pageSrc, 'setDetailA(null)')
    expectSourceToContain(pageSrc, 'setDetailB(null)')
    expectSourceToContain(pageSrc, "setActiveView('run')")
  })

  it('keeps KG diagnostics backed by real evaluation APIs instead of local mock data', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

    expectSourceToContain(pageSrc, 'evaluationApi.runKgSearchDiagnostics')
    expectSourceToContain(pageSrc, 'evaluationApi.listKgSearchDiagnosticsRuns')
    expectSourceToContain(pageSrc, 'evaluationApi.getKgSearchDiagnosticsRun')
    expectSourceToContain(pageSrc, 'evaluationApi.getKgQualityReport')
    expect(pageSrc).not.toMatch(/buildDemo|mock[A-Z]|Mock|fake/i)
  })

  it('keeps the diagnostics sidebar typography soft for Chinese form labels', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )

    expectSourceToContain(pageSrc, 'DIAGNOSTICS_SECTION_TITLE_CLASS')
    expectSourceToContain(pageSrc, 'DIAGNOSTICS_FIELD_LABEL_CLASS')
    expectSourceToContain(pageSrc, 'DIAGNOSTICS_FIELD_VALUE_CLASS')
    expectSourceToContain(pageSrc, ' text-foreground/85')
  })

  it('keeps diagnostics actions in Chinese while preserving standard metric acronyms', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'kg-diagnostics-page.tsx'),
      'utf8'
    )
    const messagesSrc = readMessageCatalogSource(path.resolve(__dirname, '../..'))

    expectSourceToContain(pageSrc, '最新结果')
    expectSourceToContain(
      pageSrc,
      'Recall {String(item.recall)} · MRR {String(item.mrr)}'
    )
    expectSourceToContain(pageSrc, '原始结果 / 运行记录')
    expectSourceToContain(pageSrc, '运行 ID')
    expectSourceToContain(pageSrc, 'TOP-K')
    expectSourceToContain(pageSrc, '查看原始数据')
    expectSourceToContain(pageSrc, '展开原始数据')
    expectSourceToContain(pageSrc, 'LLM 生成')
    expectSourceToContain(pageSrc, "low_confidence_relations: '低置信关系数'")
    expectSourceToContain(pageSrc, "documents_sampled: '抽样文档数'")
    expectSourceToContain(pageSrc, 'label="样本"')
    expectSourceToContain(pageSrc, "value={persistRun ? '开启' : '关闭'}")
    expectSourceToContain(pageSrc, 'formatDiagnosticsMetricLabel(key)')
    expectSourceToContain(messagesSrc, "pipelineHash: '流水线版本标识（可选）'")
    expectSourceNotToContain(messagesSrc, '指定 pipeline_hash（可选）')
    expectSourceNotToContain(pageSrc, 'LATEST RESULT')
    expectSourceNotToContain(pageSrc, 'Run ID')
    expectSourceNotToContain(pageSrc, 'PERSIST')
    expectSourceNotToContain(pageSrc, '大模型生成')
  })
})
