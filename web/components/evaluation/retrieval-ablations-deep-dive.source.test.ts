import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

function readFromWeb(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, '..', '..', relativePath), 'utf8')
}

function readFromRepo(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, '..', '..', '..', relativePath), 'utf8')
}

describe('retrieval ablations deep-dive surface', () => {
  it('wires the P0 ablation analysis panels into the ablations page', () => {
    const src = read('retrieval-ablations-page.tsx')

    expect(src).toContain('AblationGridPanel')
    expect(src).toContain('AblationStatisticsPanel')
    expect(src).toContain('AblationComparisonMatrix')
    expect(src).toContain('AblationCaseDrilldown')
    expect(src).toContain('AblationSliceDiffPanel')
    expect(src).toContain('AblationParetoPanel')
    expect(src).toContain('AblationParameterImpactPanel')
    expect(src).toContain('value="deep-dive"')
    expect(src).toContain('runGridBatch')
    expect(src).toContain('createRegressionAblationBatch')
  })

  it('keeps grid batch execution bounded and explicit', () => {
    const src = read('ablation-grid-panel.tsx')

    expect(src).toContain('MAX_GRID_COMBINATIONS')
    expect(src).toContain('组合数')
    expect(src).toContain('onRunGrid')
    expect(src).toContain('retrieval_mode')
    expect(src).toContain('top_k')
  })

  it('adds statistical rigor, matrix comparison, and case drilldown affordances', () => {
    const statsSrc = read('ablation-statistics-panel.tsx')
    const matrixSrc = read('ablation-comparison-matrix.tsx')
    const caseSrc = read('ablation-case-drilldown.tsx')

    expect(statsSrc).toContain('Bootstrap CI')
    expect(statsSrc).toContain('BH 校正')
    expect(statsSrc).toContain('p-value')

    expect(matrixSrc).toContain('N×M')
    expect(matrixSrc).toContain('Pareto')
    expect(matrixSrc).toContain('latency')

    expect(caseSrc).toContain('getRegressionRun')
    expect(caseSrc).toContain('导出 CSV')
    expect(caseSrc).toContain('case_id')
  })

  it('exposes a typed ablation batch API client', () => {
    const apiSrc = readFromWeb('lib/api/evaluation.ts')
    const typeSrc = readFromWeb('types/evaluation.ts')

    expect(apiSrc).toContain('createRegressionAblationBatch')
    expect(apiSrc).toContain('/evaluations/ragas/regression/ablation/batch')
    expect(typeSrc).toContain('RegressionAblationBatchResponse')
    expect(typeSrc).toContain('RegressionRunMetricSignificance')
  })

  it('keeps only productized P1 decision support from the research plan', () => {
    const sliceSrc = read('ablation-slice-diff-panel.tsx')
    const paretoSrc = read('ablation-pareto-panel.tsx')
    const impactSrc = read('ablation-parameter-impact-panel.tsx')
    const planSrc = readFromRepo('plans/rag-ablation-deep-dive-2026-q2.md')

    expect(sliceSrc).toContain('slice_diffs')
    expect(sliceSrc).toContain('retrieval_recall')
    expect(sliceSrc).toContain('切片')

    expect(paretoSrc).toContain('Pareto 前沿')
    expect(paretoSrc).toContain('latency')
    expect(paretoSrc).toContain('metricKey')

    expect(impactSrc).toContain('参数影响排序')
    expect(impactSrc).toContain('ablation_variant')
    expect(impactSrc).toContain('观测相关')

    expect(planSrc).toContain('Status: PASS')
    expect(planSrc).toContain('暂缓 Optuna')
    expect(planSrc).toContain('不再作为后续执行入口')
  })
})
