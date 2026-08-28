'use client'

import {
  Clock3,
  Database,
  FileSearch,
  ShieldCheck,
} from 'lucide-react'

import { KnowledgeOpsHero } from '@/components/ui/knowledge-ops-hero'

import type {
  DatasetReport,
  DatasetReportDataProvenance,
} from '@/types'

import {
  reportStatusLabel,
  reportStatusTone,
  shortPipelineHash,
} from '../report-format'
import { DataPill } from './report-atoms'

export function ReportsHeaderPills({
  selectedDatasetName,
  datasetId,
  totalDocs,
  isLoadingReport,
  report,
  latestAuditTime,
  dataSourceLabel,
  dataSourceSub,
  dataProvenance,
}: Readonly<{
  selectedDatasetName: string
  datasetId: string
  totalDocs: number
  isLoadingReport: boolean
  report: DatasetReport | null
  latestAuditTime: string
  dataSourceLabel: string
  dataSourceSub: string
  dataProvenance: DatasetReportDataProvenance | null
}>) {
  return (
    <div className="grid min-w-0 gap-px overflow-hidden rounded-xl border border-info/15 bg-info/15 shadow-none sm:grid-cols-2 xl:grid-cols-[1.35fr_0.86fr_0.9fr_0.88fr_1.15fr]">
      <DataPill
        icon={Database}
        label="数据集"
        value={selectedDatasetName}
        sub={datasetId ? `ID ${shortPipelineHash(datasetId)}` : '未选择'}
        tone="blue"
      />
      <DataPill
        icon={FileSearch}
        label="文档"
        value={`${totalDocs} 篇文档`}
        sub="报告画像"
        tone="blue"
      />
      <DataPill
        icon={ShieldCheck}
        label="状态"
        value={reportStatusLabel(isLoadingReport, report)}
        sub={report ? '可导出 / 可审计' : '等待生成报告'}
        tone={reportStatusTone(isLoadingReport, report)}
      />
      <DataPill
        icon={Clock3}
        label="生成"
        value={latestAuditTime}
        sub={report ? '报告快照时间' : '暂无'}
        tone="slate"
      />
      <div className="sm:col-span-2 xl:col-span-1">
        <DataPill
          icon={ShieldCheck}
          label="来源"
          value={dataSourceLabel}
          sub={dataSourceSub}
          tone={dataProvenance?.mocked === false ? 'green' : 'amber'}
        />
      </div>
    </div>
  )
}

export function ReportsPageHero({
  selectedDatasetName,
  datasetId,
  totalDocs,
  isLoadingReport,
  report,
  latestAuditTime,
  dataSourceLabel,
  dataSourceSub,
  dataProvenance,
}: Readonly<{
  selectedDatasetName: string
  datasetId: string
  totalDocs: number
  isLoadingReport: boolean
  report: DatasetReport | null
  latestAuditTime: string
  dataSourceLabel: string
  dataSourceSub: string
  dataProvenance: DatasetReportDataProvenance | null
}>) {
  return (
    <KnowledgeOpsHero
      iconImage="report-export"
      eyebrow="Report Ops"
      badge="审计证据与导出中心"
      title="数据报告"
      description="汇总数据集画像、召回门禁与治理风险，形成可导出的审计快照。"
      className="lg:flex-col lg:items-stretch 2xl:flex-row 2xl:items-start"
      titleClassName="whitespace-nowrap"
      summary={
        <ReportsHeaderPills
          selectedDatasetName={selectedDatasetName}
          datasetId={datasetId}
          totalDocs={totalDocs}
          isLoadingReport={isLoadingReport}
          report={report}
          latestAuditTime={latestAuditTime}
          dataSourceLabel={dataSourceLabel}
          dataSourceSub={dataSourceSub}
          dataProvenance={dataProvenance}
        />
      }
    />
  )
}
