import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion demo report export', () => {
  it('feeds demo sales-audit summary and evidence tables into the local redacted report', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('salesAuditSummary,')
    expect(src).toContain('salesPocCandidates,')
    expect(src).toContain('salesHighRiskFiles,')
    expect(src).toContain('const findingRows = (salesAuditSummary?.findings ?? [])')
    expect(src).toContain('const pocRows = salesPocCandidates')
    expect(src).toContain('const highRiskRows = salesHighRiskFiles')
    expect(src).toContain('报价依据')
    expect(src).toContain('风险分布')
    expect(src).toContain('建议 POC 样本')
    expect(src).toContain('高风险文件')
    expect(src).toContain('report-shell')
    expect(src).toContain('report-header')
    expect(src).toContain('toolbar')
    expect(src).toContain('kpi-card')
    expect(src).toContain('metric-icon')
    expect(src).toContain('section-card')
    expect(src).toContain('split-grid')
    expect(src).toContain('刷新数据')
    expect(src).toContain('导出 JPG')
    expect(src).toContain('renderReportHtmlToJpeg')
    expect(src).toContain('image/jpeg')
    expect(src).toContain('.jpg')
    expect(src).toContain('if (demoMode || !selectedDatasetId || !latestPrecheckRun?.id)')
  })

  it('does not synthesize sales-audit artifacts on the non-demo backend view', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain('function buildFallbackSummary')
    expect(src).not.toContain('summaryQuery.data ?? buildFallbackSummary')
    expect(src).not.toContain('buildSalesAuditFallbackArtifacts')
    expect(src).not.toContain('fallbackSalesAuditArtifacts')
    expect(src).not.toContain('precheckSummaryQuery.data ?? fallbackSalesAuditArtifacts.summary')
    expect(src).not.toContain('precheckSamplesQuery.data ?? fallbackSalesAuditArtifacts.samples')
    expect(src).not.toContain('precheckNearDupQuery.data ?? fallbackSalesAuditArtifacts.nearDup')
  })
})
