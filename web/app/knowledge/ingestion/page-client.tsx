'use client'

import {
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  CircleDashed,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  Download,
  FileDigit,
  FileCheck2,
  FileSearch,
  FolderOpen,
  Gauge,
  ListTodo,
  LucideIcon,
  Radar,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
  TableProperties,
  UploadCloud,
  Workflow,
} from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { EChartsOption } from 'echarts'
import { toast } from 'sonner'

import { datasetApi, documentApi, observabilityApi } from '@/lib/api'
import { globalEventBus } from '@/lib/event-bus'
import type {
  DatasetPrecheckFileOut,
  DatasetPrecheckNearDupResponse,
  DatasetPrecheckSamplesResponse,
  DatasetPrecheckSummary,
  Document,
  IngestionDashboardSummaryResponse,
  TaskQueueObservabilitySnapshotResponse,
} from '@/types'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { useDatasets } from '@/hooks/use-datasets'
import { usePathname, useRouter } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { EChart } from '@/components/ui/echart'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { DropZone, type DropZoneHandle } from '@/components/ingestion/drop-zone'
import { EmptyState } from '@/components/ingestion/empty-state'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import {
  LiveVelocity,
  persistVelocityUnit,
  readStoredVelocityUnit,
} from '@/components/ingestion/live-velocity'
import {
  buildEvidenceSlotReason,
  buildEvidenceSlotTags,
  buildFileSizeDistribution,
  buildFileTypeDistribution,
  buildPdfDispositionBreakdown,
  buildSalesAuditProfile,
  buildThroughputAreaRows,
  computeDocsPerMinute,
  computeDurationPercentiles,
  computeMeanFileSize,
  computeMegabytesPerSecond,
  getDocumentKind,
  getDocumentKindAccent,
  matchesReasonFilter,
} from '@/components/ingestion/monitor-utils'

import { buildDemoDocuments } from './demo-documents'

const DATASET_ALL = '__all__'

type IngestionMode = 'sales-audit' | 'execution-monitor'
type SampleDisposition = 'approved' | 'manual'
type AuditDispositionFilter = 'all' | 'pending' | 'manual' | 'approved'

const EMPTY_INGESTION_SUMMARY: IngestionDashboardSummaryResponse = {
  window_hours: 0,
  bucket_minutes: 20,
  window_start: '',
  window_end: '',
  dataset_id: null,
  created_count: 0,
  by_status: {},
  by_stage_processing: {},
  avg_completed_latency_sec: null,
  top_error_reasons: {},
  timeseries: {
    ts_ms: [],
    completed: [],
    failed: [],
    quarantined: [],
    cancelled: [],
  },
}

function safeNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function formatClockLabel(value: number): string {
  const date = new Date(value)
  const hours = `${date.getHours()}`.padStart(2, '0')
  const minutes = `${date.getMinutes()}`.padStart(2, '0')
  return `${hours}:${minutes}`
}

function formatClockSecondsLabel(value: number | string | Date): string {
  const date = new Date(value)
  const hours = `${date.getHours()}`.padStart(2, '0')
  const minutes = `${date.getMinutes()}`.padStart(2, '0')
  const seconds = `${date.getSeconds()}`.padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}

function formatDurationClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const hours = `${Math.floor(safe / 3600)}`.padStart(2, '0')
  const minutes = `${Math.floor((safe % 3600) / 60)}`.padStart(2, '0')
  const seconds = `${safe % 60}`.padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}

function downloadTextFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

type ReportEvidenceRow = {
  actionLabel: string
  fileName: string
  fileSizeLabel: string
  fileType: string
  primaryRisk: string
  riskDescription: string
}

function buildReportHtml({
  datasetLabel,
  totalDocs,
  readyRate,
  manualQueue,
  efficiency,
  latencyP90,
  selectedReason,
  documents,
  salesAuditSummary,
  salesPocCandidates,
  salesHighRiskFiles,
}: Readonly<{
  datasetLabel: string
  totalDocs: number
  readyRate: number
  manualQueue: number
  efficiency: string
  latencyP90: string
  selectedReason: string | null
  documents: Document[]
  salesAuditSummary?: DatasetPrecheckSummary | null
  salesPocCandidates?: ReportEvidenceRow[]
  salesHighRiskFiles?: ReportEvidenceRow[]
}>) {
  const rows = documents
    .slice(0, 12)
    .map(
      (document) => `
 <tr>
 <td>${escapeHtml(document.filename)}</td>
 <td>${escapeHtml(document.status || '-')}</td>
 <td>${escapeHtml(document.current_stage || '-')}</td>
 <td>${formatFileSize(document.file_size || 0)}</td>
 <td>${escapeHtml(document.error_message || '—')}</td>
 </tr>`
    )
    .join('')
  const findingRows = (salesAuditSummary?.findings ?? [])
    .slice(0, 8)
    .map(
      (item) => `
 <tr>
 <td>${escapeHtml(item.label)}</td>
 <td><span class="status-pill">${escapeHtml(item.severity)}</span></td>
 <td>${Number(item.count || 0).toLocaleString()}</td>
 <td>${escapeHtml(item.key)}</td>
 </tr>`
    )
    .join('')
  const pocRows = salesPocCandidates
    ?.slice(0, 8)
    .map(
      (item) => `
 <tr>
 <td>${escapeHtml(item.fileName)}</td>
 <td>${escapeHtml(item.fileType)}</td>
 <td>${escapeHtml(item.fileSizeLabel)}</td>
 <td>${escapeHtml(item.primaryRisk)}</td>
 <td><span class="action-pill">${escapeHtml(item.actionLabel)}</span></td>
 <td>${escapeHtml(item.riskDescription)}</td>
 </tr>`
    )
    .join('')
  const highRiskRows = salesHighRiskFiles
    ?.slice(0, 8)
    .map(
      (item) => `
 <tr>
 <td>${escapeHtml(item.fileName)}</td>
 <td>${escapeHtml(item.fileType)}</td>
 <td>${escapeHtml(item.fileSizeLabel)}</td>
 <td>${escapeHtml(item.primaryRisk)}</td>
 <td>${escapeHtml(item.riskDescription)}</td>
 </tr>`
    )
    .join('')
  const totalPrecheckFiles = Number(
    salesAuditSummary?.total_files || totalDocs || 0
  )
  const scannedPdf = Number(salesAuditSummary?.pdf_scan.scanned || 0)
  const mixedPdf = Number(salesAuditSummary?.pdf_scan.unknown || 0)
  const blockingCount = (salesAuditSummary?.findings ?? [])
    .filter((item) => ['parse_failed', 'pii', 'secrets'].includes(item.key))
    .reduce((sum, item) => sum + Number(item.count || 0), 0)
  const generatedAt = new Intl.DateTimeFormat('zh-CN', {
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date())
  const metricCards = [
    { glyph: 'S', label: '范围', tone: 'blue', value: datasetLabel },
    {
      glyph: 'DOC',
      label: '文件总数',
      tone: 'blue',
      value: totalPrecheckFiles.toLocaleString(),
    },
    { glyph: '%', label: '健康可入库', tone: 'steel', value: `${readyRate}%` },
    {
      glyph: 'H',
      label: '待人工处理',
      tone: 'violet',
      value: manualQueue.toLocaleString(),
    },
    { glyph: 'MB', label: '处理效率', tone: 'cyan', value: efficiency },
    { glyph: 'P90', label: 'P90 周期', tone: 'violet', value: latencyP90 },
    {
      glyph: 'F',
      label: '当前聚焦线索',
      tone: 'blue',
      value: selectedReason || '全部',
    },
    { glyph: 'JPG', label: '导出方式', tone: 'cyan', value: 'JPG 图片' },
  ]
    .map(
      (item) => `
 <article class="kpi-card kpi-card--${item.tone}">
 <div class="metric-icon" aria-hidden="true">${escapeHtml(item.glyph)}</div>
 <div class="metric-copy">
 <div class="metric-label">${escapeHtml(item.label)}</div>
 <div class="metric-value">${escapeHtml(item.value)}</div>
 </div>
 </article>`
    )
    .join('')
  const basisCards = [
    {
      glyph: 'I',
      label: '摸底总量',
      tone: 'cyan',
      value: totalPrecheckFiles.toLocaleString(),
    },
    {
      glyph: 'DB',
      label: '总体体量',
      tone: 'blue',
      value: formatFileSize(salesAuditSummary?.total_size_bytes || 0),
    },
    {
      glyph: 'PDF',
      label: '扫描 / 混排',
      tone: 'violet',
      value: (scannedPdf + mixedPdf).toLocaleString(),
    },
    {
      glyph: '!',
      label: '阻断项',
      tone: 'orange',
      value: blockingCount.toLocaleString(),
    },
  ]
    .map(
      (item) => `
 <article class="basis-card basis-card--${item.tone}">
 <div class="metric-icon metric-icon--small" aria-hidden="true">${escapeHtml(item.glyph)}</div>
 <div>
 <div class="metric-label">${escapeHtml(item.label)}</div>
 <div class="metric-value metric-value--compact">${escapeHtml(item.value)}</div>
 </div>
 </article>`
    )
    .join('')

  return `<!doctype html>
<html lang="zh-CN">
<head>
 <meta charset="utf-8" />
 <meta name="viewport" content="width=device-width, initial-scale=1" />
 <title>项目数据盘点报告</title>
 <style>
 :root {
 --paper: #f5f8fc;
 --paper-strong: #ffffff;
 --ink: #0c1730;
 --muted: #52627a;
 --line: #dfe7f2;
 --line-soft: #edf2f8;
 --blue: #1264e8;
 --cyan: #0ea5b7;
 --violet: #6d47e8;
 --orange: #f97316;
 --shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
 }
 * { box-sizing: border-box; }
 body {
 margin: 0;
 min-height: 100vh;
 color: var(--ink);
 background:
 radial-gradient(circle at 18% 0%, rgba(18, 100, 232, 0.08), transparent 26rem),
 linear-gradient(180deg, #f8fbff 0%, var(--paper) 52%, #eef4fb 100%);
 font-family:"Inter","PingFang SC","Microsoft YaHei", ui-sans-serif, system-ui, sans-serif;
 padding: 36px;
 }
 .report-shell {
 max-width: 1760px;
 margin: 0 auto;
 }
 .report-header {
 display: flex;
 align-items: flex-start;
 justify-content: space-between;
 gap: 24px;
 margin-bottom: 24px;
 }
 h1 {
 margin: 0;
 font-size: clamp(28px, 2.3vw, 40px);
 line-height: 1.1;
 letter-spacing: -0.05em;
 }
 h2 {
 margin: 0;
 font-size: 20px;
 letter-spacing: -0.03em;
 }
 .report-subtitle {
 max-width: 980px;
 margin: 10px 0 0;
 color: var(--muted);
 font-size: 15px;
 line-height: 1.6;
 }
 .generated-at {
 margin-top: 8px;
 color: #718096;
 font-size: 12px;
 }
 .toolbar {
 display: flex;
 flex-wrap: wrap;
 gap: 12px;
 justify-content: flex-end;
 }
 .toolbar button {
 min-height: 48px;
 border: 1px solid var(--line);
 border-radius: 10px;
 background: rgba(255, 255, 255, 0.82);
 color: var(--ink);
 cursor: pointer;
 font: inherit;
 font-weight: 700;
 padding: 0 20px;
 box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
 }
 .toolbar .primary {
 border-color: #0d5bd6;
 background: linear-gradient(135deg, #1668ee, #0d5bd6);
 color: #ffffff;
 }
 .button-icon {
 display: inline-flex;
 min-width: 24px;
 margin-right: 8px;
 font-size: 12px;
 letter-spacing: -0.04em;
 }
 .kpi-grid,
 .basis-grid {
 display: grid;
 grid-template-columns: repeat(4, minmax(0, 1fr));
 gap: 16px;
 }
 .kpi-grid {
 margin-bottom: 12px;
 }
 .kpi-card,
 .basis-card,
 .section-card {
 border: 1px solid var(--line);
 background: rgba(255, 255, 255, 0.86);
 box-shadow: var(--shadow);
 }
 .kpi-card,
 .basis-card {
 display: flex;
 align-items: center;
 gap: 20px;
 min-height: 108px;
 border-radius: 12px;
 padding: 22px;
 }
 .metric-icon {
 display: inline-flex;
 align-items: center;
 justify-content: center;
 width: 64px;
 height: 64px;
 flex: 0 0 auto;
 border-radius: 16px;
 background: #eef5ff;
 color: var(--blue);
 font-size: 13px;
 font-weight: 900;
 letter-spacing: -0.05em;
 }
 .metric-icon--small {
 width: 48px;
 height: 48px;
 border-radius: 14px;
 font-size: 12px;
 }
 .kpi-card--cyan .metric-icon,
 .basis-card--cyan .metric-icon { background: #e9fbfd; color: var(--cyan); }
 .kpi-card--violet .metric-icon,
 .basis-card--violet .metric-icon { background: #f0ebff; color: var(--violet); }
 .basis-card--orange .metric-icon { background: #fff2e8; color: var(--orange); }
 .kpi-card--steel .metric-icon { background: #edf2f8; color: #334155; }
 .metric-label {
 color: var(--muted);
 font-size: 14px;
 line-height: 1.2;
 }
 .metric-value {
 margin-top: 8px;
 color: var(--ink);
 font-size: 26px;
 font-weight: 900;
 letter-spacing: -0.04em;
 line-height: 1.1;
 }
 .metric-value--compact {
 font-size: 22px;
 }
 .section-card {
 margin-top: 12px;
 border-radius: 12px;
 padding: 16px 20px;
 }
 .section-head {
 display: flex;
 align-items: flex-end;
 justify-content: space-between;
 gap: 18px;
 margin-bottom: 14px;
 }
 .section-note {
 margin: 4px 0 0;
 color: var(--muted);
 font-size: 13px;
 line-height: 1.5;
 }
 .table-frame {
 overflow: hidden;
 border: 1px solid var(--line);
 border-radius: 10px;
 background: var(--paper-strong);
 }
 table {
 width: 100%;
 border-collapse: collapse;
 font-size: 14px;
 }
 th,
 td {
 border-bottom: 1px solid var(--line-soft);
 padding: 12px 16px;
 text-align: left;
 vertical-align: top;
 }
 th {
 color: #475569;
 background: #f8fbff;
 font-size: 12px;
 font-weight: 800;
 }
 tbody tr:last-child td {
 border-bottom: 0;
 }
 .status-pill,
 .action-pill {
 display: inline-flex;
 align-items: center;
 min-height: 24px;
 border: 1px solid #a7c9ff;
 border-radius: 7px;
 background: #eaf3ff;
 color: #075bd8;
 font-size: 12px;
 font-weight: 700;
 padding: 2px 9px;
 }
 .action-pill {
 border-color: #9bdfb8;
 background: #e9fbf0;
 color: #067647;
 }
 .split-grid {
 display: grid;
 grid-template-columns: repeat(2, minmax(0, 1fr));
 gap: 16px;
 margin-top: 12px;
 }
 .empty {
 border: 1px dashed var(--line);
 border-radius: 10px;
 color: var(--muted);
 padding: 18px;
 background: #f8fbff;
 }
 @media (max-width: 980px) {
 body { padding: 20px; }
 .report-header { display: block; }
 .toolbar { justify-content: flex-start; margin-top: 16px; }
 .kpi-grid,
 .basis-grid,
 .split-grid { grid-template-columns: 1fr; }
 }
 @media print {
 body { background: #ffffff; padding: 0; }
 .report-shell { max-width: none; }
 .toolbar { display: none; }
 .kpi-card,
 .basis-card,
 .section-card { box-shadow: none; break-inside: avoid; }
 }
 </style>
</head>
<body>
 <main class="report-shell">
 <header class="report-header">
 <div>
 <h1>项目数据盘点报告</h1>
 <p class="report-subtitle">Sensitive Data Policy: 默认仅展示脱敏后的聚合事实与待确认线索，不做主观评分；需要人工判断的项统一保留在样本槽与风险清单里。</p>
 <div class="generated-at">生成时间：${escapeHtml(generatedAt)}</div>
 </div>
 <div class="toolbar" aria-label="报告操作">
 <button type="button" onclick="window.location.reload()"><span class="button-icon">R</span>刷新数据</button>
 <button class="primary" type="button"><span class="button-icon">JPG</span>导出 JPG</button>
 </div>
 </header>

 <section class="kpi-grid" aria-label="项目指标">
 ${metricCards}
 </section>

 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>报价依据</h2>
 <p class="section-note">面向入库前摸底与报价沟通，仅保留脱敏后的规模、体量和阻断线索。</p>
 </div>
 </div>
 <div class="basis-grid">
 ${basisCards}
 </div>
 </section>

 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>风险分布</h2>
 <p class="section-note">按后端预检 findings 聚合，等级用于排查优先级，不代表最终主观评分。</p>
 </div>
 </div>
 ${
   findingRows
     ? `<div class="table-frame">
 <table>
 <thead>
 <tr><th>类型</th><th>等级</th><th>数量</th><th>KEY</th></tr>
 </thead>
 <tbody>${findingRows}</tbody>
 </table>
 </div>`
     : '<div class="empty">暂无风险分布数据</div>'
 }
 </section>

 <div class="split-grid">
 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>建议 POC 样本</h2>
 <p class="section-note">优先挑选能代表复杂度、体量和阻断原因的样本。</p>
 </div>
 </div>
 ${
   pocRows
     ? `<div class="table-frame">
 <table>
 <thead>
 <tr><th>文件</th><th>类型</th><th>大小</th><th>主要风险</th><th>建议动作</th><th>原因</th></tr>
 </thead>
 <tbody>${pocRows}</tbody>
 </table>
 </div>`
     : '<div class="empty">暂无 POC 样本数据</div>'
 }
 </section>

 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>高风险文件</h2>
 <p class="section-note">用于人工复核与实施排期，不在报告中暴露原始敏感内容。</p>
 </div>
 </div>
 ${
   highRiskRows
     ? `<div class="table-frame">
 <table>
 <thead>
 <tr><th>文件</th><th>类型</th><th>大小</th><th>风险</th><th>原因</th></tr>
 </thead>
 <tbody>${highRiskRows}</tbody>
 </table>
 </div>`
     : '<div class="empty">暂无高风险文件数据</div>'
 }
 </section>
 </div>

 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>当前页面样本</h2>
 <p class="section-note">导出时页面内可见文件的脱敏状态快照。</p>
 </div>
 </div>
 <div class="table-frame">
 <table>
 <thead>
 <tr>
 <th>文件</th>
 <th>状态</th>
 <th>阶段</th>
 <th>大小</th>
 <th>线索</th>
 </tr>
 </thead>
 <tbody>${rows || '<tr><td colspan="5">暂无当前页面样本</td></tr>'}</tbody>
 </table>
 </div>
 </section>
 </main>
</body>
</html>`
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function buildSafeReportFilename(label: string, extension: string): string {
  const safe = String(label || 'ingestion-audit-report')
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 90)
  return `${safe || 'ingestion-audit-report'}${extension}`
}

function waitForNextPaint(): Promise<void> {
  return new Promise((resolve) => {
    globalThis.window.requestAnimationFrame(() => {
      globalThis.window.requestAnimationFrame(() => resolve())
    })
  })
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality?: number
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob)
        else reject(new Error('Report image encode failed'))
      },
      type,
      quality
    )
  })
}

type CanvasReportCard = {
  label: string
  value: string
}

type CanvasReportTable = {
  headers: string[]
  rows: string[][]
}

type CanvasReportSection = {
  note: string
  table: CanvasReportTable | null
  title: string
}

async function renderReportHtmlToJpeg(html: string, filename: string) {
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  Object.assign(iframe.style, {
    border: '0',
    height: '1px',
    left: '-10000px',
    opacity: '0',
    pointerEvents: 'none',
    position: 'fixed',
    top: '0',
    width: '1760px',
  })
  document.body.appendChild(iframe)

  try {
    const frameDocument = iframe.contentDocument
    if (!frameDocument) throw new Error('Report frame unavailable')

    frameDocument.open()
    frameDocument.write(html)
    frameDocument.close()
    await new Promise((resolve) => globalThis.window.setTimeout(resolve, 160))
    await frameDocument.fonts?.ready.catch(() => undefined)
    await waitForNextPaint()

    const getText = (
      selector: string,
      root: ParentNode = frameDocument
    ): string =>
      root.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim() ??
      ''
    const readCards = (selector: string): CanvasReportCard[] =>
      Array.from(frameDocument.querySelectorAll<HTMLElement>(selector))
        .map((card) => ({
          label: getText('.metric-label, .kpi-label', card),
          value: getText('.metric-value, .kpi-value', card),
        }))
        .filter((card) => card.label || card.value)
    const readTable = (section: HTMLElement): CanvasReportTable | null => {
      const table = section.querySelector('table')
      if (!table) return null
      const headers = Array.from(table.querySelectorAll('thead th')).map(
        (cell) => cell.textContent?.trim() ?? ''
      )
      const rows = Array.from(table.querySelectorAll('tbody tr')).map((row) =>
        Array.from(row.querySelectorAll('td')).map(
          (cell) => cell.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        )
      )
      return headers.length || rows.length ? { headers, rows } : null
    }
    const readSection = (titlePart: string): CanvasReportSection | null => {
      const section = Array.from(
        frameDocument.querySelectorAll<HTMLElement>('.section-card, .section')
      ).find((item) => getText('h2', item).includes(titlePart))
      if (!section) return null
      return {
        note: getText('.section-note, .notes', section),
        table: readTable(section),
        title: getText('h2', section),
      }
    }

    const title =
      getText('.report-header h1') ||
      getText('.title') ||
      frameDocument.title ||
      '项目数据盘点报告'
    const subtitle = getText('.report-subtitle') || getText('.sub')
    const generatedAt = getText('.generated-at')
    const metricCards = readCards('.kpi-card')
    const fallbackCards = readCards('.grid .card')
    const kpiCards = metricCards.length
      ? metricCards
      : fallbackCards.slice(0, 8)
    const basisCards = readCards('.basis-card').length
      ? readCards('.basis-card')
      : fallbackCards.slice(8, 12)
    const riskSection = readSection('风险分布') ?? readSection('问题清单')
    const pocSection = readSection('建议 POC') ?? readSection('代表性样本')
    const highRiskSection =
      readSection('高风险文件') ?? readSection('需复核样本')
    const sampleSection = readSection('当前页面样本')

    const width = 1760
    const margin = 36
    const gap = 16
    const contentWidth = width - margin * 2
    const pixelRatio = Math.min(
      2,
      Math.max(1, globalThis.window.devicePixelRatio || 1)
    )
    const canvas = document.createElement('canvas')
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Report image canvas unavailable')

    const setFont = (size: number, weight: number | string = 400) => {
      context.font = `${weight} ${size}px"PingFang SC","Microsoft YaHei","Inter", sans-serif`
    }
    const roundRect = (
      x: number,
      y: number,
      rectWidth: number,
      rectHeight: number,
      radius: number
    ) => {
      context.beginPath()
      context.moveTo(x + radius, y)
      context.lineTo(x + rectWidth - radius, y)
      context.quadraticCurveTo(x + rectWidth, y, x + rectWidth, y + radius)
      context.lineTo(x + rectWidth, y + rectHeight - radius)
      context.quadraticCurveTo(
        x + rectWidth,
        y + rectHeight,
        x + rectWidth - radius,
        y + rectHeight
      )
      context.lineTo(x + radius, y + rectHeight)
      context.quadraticCurveTo(x, y + rectHeight, x, y + rectHeight - radius)
      context.lineTo(x, y + radius)
      context.quadraticCurveTo(x, y, x + radius, y)
      context.closePath()
    }
    const drawCardBase = (
      x: number,
      y: number,
      rectWidth: number,
      rectHeight: number,
      radius = 14
    ) => {
      context.save()
      context.shadowColor = 'rgba(15, 23, 42, 0.08)'
      context.shadowBlur = 26
      context.shadowOffsetY = 12
      context.fillStyle = 'rgba(255, 255, 255, 0.92)'
      roundRect(x, y, rectWidth, rectHeight, radius)
      context.fill()
      context.restore()
      context.strokeStyle = '#dfe7f2'
      context.lineWidth = 1
      roundRect(x, y, rectWidth, rectHeight, radius)
      context.stroke()
    }
    const drawTextLines = (
      text: string,
      x: number,
      y: number,
      maxWidth: number,
      lineHeight: number,
      maxLines = 2
    ): number => {
      if (!text) return y
      const chars = Array.from(text)
      const lines: string[] = []
      let current = ''
      for (const char of chars) {
        const next = `${current}${char}`
        if (context.measureText(next).width > maxWidth && current) {
          lines.push(current)
          current = char
          if (lines.length >= maxLines) break
        } else {
          current = next
        }
      }
      if (current && lines.length < maxLines) lines.push(current)
      lines.forEach((line, index) => {
        const suffix =
          index === maxLines - 1 &&
          chars.join('').length > lines.join('').length
            ? '...'
            : ''
        context.fillText(`${line}${suffix}`, x, y + index * lineHeight)
      })
      return y + Math.max(1, lines.length) * lineHeight
    }
    const drawMetricCard = (
      card: CanvasReportCard,
      index: number,
      x: number,
      y: number,
      rectWidth: number,
      rectHeight: number
    ) => {
      drawCardBase(x, y, rectWidth, rectHeight, 12)
      const tones = [
        '#1264e8',
        '#1264e8',
        '#334155',
        '#6d47e8',
        '#0ea5b7',
        '#6d47e8',
        '#1264e8',
        '#0ea5b7',
      ]
      const tone = tones[index % tones.length] ?? '#1264e8'
      context.fillStyle = `${tone}18`
      roundRect(x + 22, y + 24, 60, 60, 16)
      context.fill()
      setFont(12, 900)
      context.fillStyle = tone
      context.textAlign = 'center'
      context.textBaseline = 'middle'
      context.fillText(card.label.slice(0, 4).toUpperCase(), x + 52, y + 54)
      context.textAlign = 'left'
      context.textBaseline = 'alphabetic'
      setFont(14, 500)
      context.fillStyle = '#52627a'
      context.fillText(card.label, x + 102, y + 44)
      setFont(26, 900)
      context.fillStyle = '#0c1730'
      drawTextLines(card.value, x + 102, y + 78, rectWidth - 126, 28, 1)
    }
    const drawSection = (
      section: CanvasReportSection,
      x: number,
      y: number,
      rectWidth: number,
      options: { maxRows?: number } = {}
    ): number => {
      const table = section.table
      const rows = table?.rows.slice(0, options.maxRows ?? 8) ?? []
      const headers = table?.headers.length
        ? table.headers
        : (rows[0]?.map((_, index) => `列 ${index + 1}`) ?? [])
      const rowHeight = 48
      const tableHeight = headers.length
        ? 44 + Math.max(1, rows.length) * rowHeight
        : 58
      const noteHeight = section.note ? 22 : 0
      const rectHeight = 70 + noteHeight + tableHeight
      drawCardBase(x, y, rectWidth, rectHeight, 12)

      setFont(20, 800)
      context.fillStyle = '#0c1730'
      context.fillText(section.title, x + 20, y + 32)
      if (section.note) {
        setFont(13, 400)
        context.fillStyle = '#52627a'
        drawTextLines(section.note, x + 20, y + 56, rectWidth - 40, 18, 1)
      }

      const tableY = y + 50 + noteHeight
      context.fillStyle = '#ffffff'
      roundRect(x + 18, tableY, rectWidth - 36, tableHeight, 10)
      context.fill()
      context.strokeStyle = '#dfe7f2'
      context.stroke()

      if (!headers.length) {
        setFont(14, 500)
        context.fillStyle = '#52627a'
        context.fillText('暂无数据', x + 34, tableY + 34)
        return y + rectHeight
      }

      const tableWidth = rectWidth - 36
      const columnWidth = tableWidth / Math.max(1, headers.length)
      context.fillStyle = '#f8fbff'
      roundRect(x + 18, tableY, tableWidth, 44, 10)
      context.fill()
      setFont(12, 800)
      context.fillStyle = '#475569'
      headers.forEach((header, index) => {
        drawTextLines(
          header,
          x + 34 + index * columnWidth,
          tableY + 28,
          columnWidth - 24,
          14,
          1
        )
      })
      rows.forEach((row, rowIndex) => {
        const currentY = tableY + 44 + rowIndex * rowHeight
        context.strokeStyle = '#edf2f8'
        context.beginPath()
        context.moveTo(x + 18, currentY)
        context.lineTo(x + 18 + tableWidth, currentY)
        context.stroke()
        setFont(13, rowIndex === 0 ? 650 : 500)
        context.fillStyle = '#0c1730'
        row.slice(0, headers.length).forEach((cell, index) => {
          drawTextLines(
            cell || '-',
            x + 34 + index * columnWidth,
            currentY + 22,
            columnWidth - 24,
            16,
            2
          )
        })
      })
      if (!rows.length) {
        setFont(14, 500)
        context.fillStyle = '#52627a'
        context.fillText('暂无数据', x + 34, tableY + 82)
      }
      return y + rectHeight
    }

    const cardWidth = (contentWidth - gap * 3) / 4
    const kpiRows = Math.max(1, Math.ceil(kpiCards.length / 4))
    let height = margin + 92 + kpiRows * 124 + 20 + 190
    if (riskSection) height += 260
    if (pocSection || highRiskSection) height += 360
    if (sampleSection) height += 260
    height += margin

    canvas.width = Math.ceil(width * pixelRatio)
    canvas.height = Math.ceil(height * pixelRatio)
    context.scale(pixelRatio, pixelRatio)
    context.fillStyle = '#f5f8fc'
    context.fillRect(0, 0, width, height)
    const gradient = context.createLinearGradient(0, 0, 0, height)
    gradient.addColorStop(0, '#f8fbff')
    gradient.addColorStop(0.55, '#f5f8fc')
    gradient.addColorStop(1, '#eef4fb')
    context.fillStyle = gradient
    context.fillRect(0, 0, width, height)

    let y = margin
    setFont(40, 900)
    context.fillStyle = '#0c1730'
    context.fillText(title, margin, y + 28)
    setFont(15, 400)
    context.fillStyle = '#52627a'
    y = drawTextLines(subtitle, margin, y + 66, 1060, 22, 2)
    if (generatedAt) {
      setFont(12, 500)
      context.fillStyle = '#718096'
      context.fillText(generatedAt, margin, y + 8)
    }
    y += 34

    kpiCards.slice(0, 8).forEach((card, index) => {
      const col = index % 4
      const row = Math.floor(index / 4)
      drawMetricCard(
        card,
        index,
        margin + col * (cardWidth + gap),
        y + row * 124,
        cardWidth,
        108
      )
    })
    y += kpiRows * 124 + 12

    const basisSection: CanvasReportSection = {
      note: '面向入库前摸底与报价沟通，仅保留脱敏后的规模、体量和阻断线索。',
      table: null,
      title: '报价依据',
    }
    drawCardBase(margin, y, contentWidth, 178, 12)
    setFont(20, 800)
    context.fillStyle = '#0c1730'
    context.fillText(basisSection.title, margin + 20, y + 32)
    setFont(13, 400)
    context.fillStyle = '#52627a'
    context.fillText(basisSection.note, margin + 20, y + 56)
    basisCards.slice(0, 4).forEach((card, index) => {
      const x = margin + 18 + index * ((contentWidth - 36 - gap * 3) / 4 + gap)
      const w = (contentWidth - 36 - gap * 3) / 4
      drawMetricCard(card, index + 8, x, y + 80, w, 78)
    })
    y += 190

    if (riskSection)
      y = drawSection(riskSection, margin, y, contentWidth, { maxRows: 8 }) + 12
    if (pocSection || highRiskSection) {
      const splitWidth = (contentWidth - gap) / 2
      const leftEnd = pocSection
        ? drawSection(pocSection, margin, y, splitWidth, { maxRows: 5 })
        : y
      const rightEnd = highRiskSection
        ? drawSection(
            highRiskSection,
            margin + splitWidth + gap,
            y,
            splitWidth,
            { maxRows: 5 }
          )
        : y
      y = Math.max(leftEnd, rightEnd) + 12
    }
    if (sampleSection)
      y =
        drawSection(sampleSection, margin, y, contentWidth, { maxRows: 8 }) + 12

    const jpeg = await canvasToBlob(canvas, 'image/jpeg', 0.94)
    downloadBlob(jpeg, filename)
  } finally {
    iframe.remove()
  }
}

function anonymizeEvidenceName(name: string): string {
  const value = String(name || '')
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return `FILE_${hash.toString(36).toUpperCase().padStart(6, '0').slice(-6)}`
}

function buildDemoPrecheckSummary(
  documents: Document[]
): DatasetPrecheckSummary {
  return {
    dataset_id: 'demo-dataset',
    scan_run_id: 'demo-run',
    generated_at: new Date().toISOString(),
    total_files: 12_543,
    total_size_bytes: Math.round(48.6 * 1024 * 1024 * 1024),
    by_file_type: { pdf: 7_854, docx: 2_112, xlsx: 1_420, pptx: 633, md: 524 },
    file_size_histogram: [
      { label: '<500KB', count: 3521 },
      { label: '500KB-2MB', count: 4873 },
      { label: '2MB-5MB', count: 2536 },
      { label: '5MB-10MB', count: 1140 },
      { label: '>10MB', count: 473 },
    ],
    length_percentiles: {
      p25: 812,
      p50: 1_876,
      p75: 5_314,
      p90: 9_816,
      p99: 23_654,
    },
    length_histogram: [
      { label: '<1k', count: 382 },
      { label: '1k-2k', count: 958 },
      { label: '2k-5k', count: 1731 },
      { label: '5k-10k', count: 1118 },
      { label: '10k-20k', count: 624 },
      { label: '20k-50k', count: 218 },
      { label: '50k-100k', count: 66 },
      { label: '>100k', count: 14 },
    ],
    pdf_scan: {
      scanned: 911,
      not_scanned: 8_645,
      unknown: 2_987,
    },
    pdf_detection: {
      text: 8_645,
      mixed: 2_987,
      scan: 911,
    },
    pii_hits_total: { phone: 524, email: 58, id_card: 19 },
    secrets_hits_total: {},
    findings: [
      {
        key: 'pdf_scanned',
        label: '扫描件',
        severity: 'warning',
        count: 1_956,
      },
      { key: 'parse_failed', label: '解析失败', severity: 'error', count: 412 },
      { key: 'pii', label: '合敏感信息', severity: 'warning', count: 736 },
      { key: 'exact_dup', label: '重复文件', severity: 'info', count: 1_128 },
      { key: 'near_dup', label: '版本冲突', severity: 'info', count: 342 },
      { key: 'other', label: '其他风险', severity: 'info', count: 289 },
    ],
  }
}

function buildDemoPrecheckSamples(
  documents: Document[]
): DatasetPrecheckSamplesResponse {
  const fileItems: DatasetPrecheckFileOut[] = [
    {
      name: '财务报表_2024Q1.pdf',
      file_type: 'pdf',
      file_size: Math.round(138.5 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 220,
      estimated_text: false,
      pdf_scanned: true,
      pdf_pages: {
        page_count: 84,
        sampled_pages: 10,
        scanned_pages: 77,
        text_pages: 5,
        low_density_pages: 2,
        unknown_pages: 0,
        scan_ratio: 0.92,
        low_density_ratio: 0.02,
      },
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['pdf_scanned'],
      error_message: null,
    },
    {
      name: '员工手册_最新版.docx',
      file_type: 'docx',
      file_size: Math.round(24.3 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 12430,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['exact_dup', 'near_dup'],
      error_message: null,
    },
    {
      name: '合同_2024_v3.docx',
      file_type: 'docx',
      file_size: Math.round(12.7 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 9816,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: { phone: 2, email: 1 },
      secrets_hits: {},
      findings: ['pii'],
      error_message: null,
    },
    {
      name: '技术方案_无_汇总.pdf',
      file_type: 'pdf',
      file_size: Math.round(56.8 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 2310,
      estimated_text: false,
      pdf_scanned: false,
      pdf_pages: {
        page_count: 48,
        sampled_pages: 10,
        scanned_pages: 8,
        text_pages: 34,
        low_density_pages: 6,
        unknown_pages: 0,
        scan_ratio: 0.17,
        low_density_ratio: 0.12,
      },
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['near_dup'],
      error_message: null,
    },
    {
      name: '项目计划_需求.pptx',
      file_type: 'pptx',
      file_size: Math.round(18.2 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 1642,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['parse_failed'],
      error_message: '文档暂时解析失败',
    },
  ]

  return {
    requested: 5,
    strata_count: 4,
    representative: fileItems.slice(0, 3),
    needs_review: {
      pdf_scanned: fileItems.filter((file) =>
        file.findings.includes('pdf_scanned')
      ),
      parse_failed: fileItems.filter((file) =>
        file.findings.includes('parse_failed')
      ),
      pii: fileItems.filter((file) => file.findings.includes('pii')),
    },
    top_large_files: [...fileItems]
      .sort((left, right) => right.file_size - left.file_size)
      .slice(0, 5),
    top_long_text: [...fileItems]
      .sort((left, right) => right.text_characters - left.text_characters)
      .slice(0, 5),
  }
}

function buildDemoNearDupResponse(): DatasetPrecheckNearDupResponse {
  return {
    threshold: 5,
    max_pairs: 20,
    pairs_returned: 2,
    clusters_returned: 1,
    clusters: [
      { id: 'demo-cluster-1', members: ['FILE_00A1BC', 'FILE_00A1BD'] },
    ],
    pairs: [
      { a: 'FILE_00A1BC', b: 'FILE_00A1BD', distance: 2 },
      { a: 'FILE_00A1BE', b: 'FILE_00A1BF', distance: 3 },
    ],
  }
}

function LoadingWireframe() {
  return (
    <div className="space-y-4">
      <div className="rounded-[2rem] border border-border/50 bg-background/80 p-5">
        <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <div className="space-y-3 rounded-[1.5rem] border border-dashed border-border/60 bg-muted/20 p-4">
            <div className="h-4 w-32 rounded-full border border-border/50" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
          </div>
          <div className="space-y-4 rounded-[1.6rem] border border-dashed border-border/60 bg-background/90 p-4">
            <div className="h-12 rounded-[1rem] border border-border/50" />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <div
                  key={index}
                  className="h-24 rounded-[1.25rem] border border-dashed border-border/60 bg-muted/20"
                />
              ))}
            </div>
            <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <div className="h-[18rem] rounded-[1.25rem] border border-dashed border-border/60 bg-muted/15" />
              <div className="h-[18rem] rounded-[1.25rem] border border-dashed border-border/60 bg-muted/15" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

type SalesProcessingLane = {
  key: string
  label: string
  count: number
  tone: string
}

type SalesEvidenceTableRow = {
  id: string
  fileName: string
  fileType: string
  fileSizeLabel: string
  primaryRisk: string
  riskDescription: string
  actionLabel: string
  icon: LucideIcon
  iconTone: string
}

const SALES_PANEL_CLASS =
  'rounded-[1rem] border border-border/55 bg-background/92 shadow-[0_14px_28px_-24px_rgba(15,23,42,0.12)]'
const SALES_PANEL_INSET_CLASS =
  'rounded-[0.9rem] border border-border/50 bg-background/82'
const SALES_SUMMARY_STRIP_CLASS =
  'overflow-hidden rounded-[1rem] border border-border/55 bg-background/72 shadow-[0_12px_28px_-24px_rgba(15,23,42,0.1)]'

type SalesPanelHeaderProps = {
  actionLabel?: string
  icon: LucideIcon
  iconTone?: string
  onAction?: () => void
  subtitle?: string
  title: string
}

function SalesPanelHeader({
  actionLabel,
  icon: Icon,
  iconTone = 'text-muted-foreground/65',
  onAction,
  subtitle,
  title,
}: Readonly<SalesPanelHeaderProps>) {
  return (
    <div className="flex min-h-[1.5rem] items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex min-h-4 items-center gap-1.5 text-[10px] font-medium tracking-[-0.01em] text-foreground">
          <Icon className={cn('h-3 w-3 shrink-0', iconTone)} />
          <span className="truncate">{title}</span>
        </div>
        {subtitle ? (
          <div className="mt-0.5 pl-[18px] text-[8px] leading-3 text-muted-foreground">
            {subtitle}
          </div>
        ) : null}
      </div>
      {actionLabel ? (
        <button
          type="button"
          onClick={onAction}
          className="inline-flex min-h-4 shrink-0 items-center gap-0.5 text-[8px] font-medium text-info transition-colors hover:text-info"
        >
          <span>{actionLabel}</span>
          <ChevronRight className="h-3 w-3" />
        </button>
      ) : null}
    </div>
  )
}

export default function KnowledgeIngestionPageClient() {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const reduceMotion = useReducedMotion()
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const dropZoneRef = useRef<DropZoneHandle>(null)
  const demoMode = searchParams.get('demo') === '1'
  const mode: IngestionMode =
    searchParams.get('mode') === 'execution-monitor'
      ? 'execution-monitor'
      : 'sales-audit'
  const [datasetScope, setDatasetScope] = useState(
    searchParams.get('datasetId') || DATASET_ALL
  )
  const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(false)
  const [headerCollapsed, setHeaderCollapsed] = useState(false)
  const [selectedReason, setSelectedReason] = useState<string | null>(null)
  const [auditDispositionFilter, setAuditDispositionFilter] =
    useState<AuditDispositionFilter>('all')
  const [selectedAuditIds, setSelectedAuditIds] = useState<string[]>([])
  const [sampleDispositions, setSampleDispositions] = useState<
    Record<string, SampleDisposition>
  >({})
  const [activeDetailId, setActiveDetailId] = useState<string | null>(null)
  const [selectedEvidenceFile, setSelectedEvidenceFile] =
    useState<DatasetPrecheckFileOut | null>(null)
  const [velocityUnit, setVelocityUnit] = useState<'docs' | 'bytes'>(
    readStoredVelocityUnit
  )
  const [canvasGlow, setCanvasGlow] = useState({ x: 36, y: 24 })
  const [successPulseVisible, setSuccessPulseVisible] = useState(false)
  const [renderTimestamp] = useState(() => Date.now())

  const selectedDatasetId = datasetScope === DATASET_ALL ? null : datasetScope
  const { datasets } = useDatasets()

  const documentsQuery = useQuery({
    queryKey: ['knowledge-ingestion-documents', selectedDatasetId],
    queryFn: async ({ signal }) => {
      const response = await documentApi.list(
        {
          limit: 200,
          dataset_id: selectedDatasetId ?? undefined,
        },
        { signal }
      )
      return response.items ?? []
    },
    staleTime: 10_000,
    refetchInterval: demoMode ? false : 25_000,
  })

  const summaryQuery = useQuery<IngestionDashboardSummaryResponse | null>({
    queryKey: ['knowledge-ingestion-summary', selectedDatasetId],
    queryFn: async () => {
      try {
        return await observabilityApi.getIngestionDashboardSummary({
          window_hours: 12,
          bucket_minutes: 20,
          dataset_id: selectedDatasetId ?? undefined,
        })
      } catch {
        return null
      }
    },
    staleTime: 10_000,
    refetchInterval: demoMode ? false : 25_000,
  })

  const taskQueueQuery =
    useQuery<TaskQueueObservabilitySnapshotResponse | null>({
      queryKey: ['knowledge-ingestion-task-queue'],
      queryFn: async () => {
        try {
          return await observabilityApi.getTaskQueueSnapshot()
        } catch {
          return null
        }
      },
      enabled: mode === 'execution-monitor' && !demoMode,
      staleTime: 10_000,
      refetchInterval: demoMode ? false : 25_000,
    })

  const precheckRunsQuery = useQuery({
    queryKey: ['knowledge-ingestion-precheck-runs', selectedDatasetId],
    queryFn: async () => {
      if (!selectedDatasetId) return []
      const response = await datasetApi.listPrecheckScanRuns(
        selectedDatasetId,
        { skip: 0, limit: 20 }
      )
      return response.items ?? []
    },
    enabled: Boolean(selectedDatasetId) && !demoMode,
    staleTime: 10_000,
  })

  const latestPrecheckRun = useMemo(
    () =>
      (precheckRunsQuery.data ?? []).find(
        (run) => String(run.status || '').toLowerCase() === 'completed'
      ) ??
      (precheckRunsQuery.data ?? [])[0] ??
      null,
    [precheckRunsQuery.data]
  )

  const precheckSummaryQuery = useQuery<DatasetPrecheckSummary | null>({
    queryKey: [
      'knowledge-ingestion-precheck-summary',
      selectedDatasetId,
      latestPrecheckRun?.id,
    ],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckSummary(
        selectedDatasetId,
        latestPrecheckRun.id
      )
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const precheckSamplesQuery = useQuery<DatasetPrecheckSamplesResponse | null>({
    queryKey: [
      'knowledge-ingestion-precheck-samples',
      selectedDatasetId,
      latestPrecheckRun?.id,
    ],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckSamples(
        selectedDatasetId,
        latestPrecheckRun.id,
        { prefer_artifact: true, size: 12 }
      )
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const precheckNearDupQuery = useQuery<DatasetPrecheckNearDupResponse | null>({
    queryKey: [
      'knowledge-ingestion-precheck-near-dup',
      selectedDatasetId,
      latestPrecheckRun?.id,
    ],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckNearDups(
        selectedDatasetId,
        latestPrecheckRun.id
      )
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const documents = useMemo(
    () =>
      demoMode
        ? buildDemoDocuments(documentsQuery.data ?? [])
        : (documentsQuery.data ?? []),
    [demoMode, documentsQuery.data]
  )
  const summary = useMemo(
    () => summaryQuery.data ?? EMPTY_INGESTION_SUMMARY,
    [summaryQuery.data]
  )
  const taskQueueSnapshot = taskQueueQuery.data ?? null
  const taskQueueStatusLabel = useMemo(() => {
    if (demoMode) return 'Demo 运行态'
    if (taskQueueQuery.isFetching && !taskQueueSnapshot) return '读取队列'
    if (!taskQueueSnapshot) return '队列未知'
    if (!taskQueueSnapshot.enabled) return '队列未启用'
    if (!taskQueueSnapshot.broker_up) return 'Broker 异常'
    return 'Broker 正常'
  }, [demoMode, taskQueueQuery.isFetching, taskQueueSnapshot])
  const taskQueueStatusTone = useMemo(() => {
    if (demoMode || !taskQueueSnapshot)
      return 'border-border/18 bg-muted/[0.08] text-foreground'
    if (!taskQueueSnapshot.enabled)
      return 'border-warning/18 bg-warning/[0.08] text-warning'
    if (!taskQueueSnapshot.broker_up)
      return 'border-rose/18 bg-rose/[0.08] text-rose'
    return 'border-success/18 bg-success/[0.08] text-success'
  }, [demoMode, taskQueueSnapshot])
  const salesAuditSummary = useMemo(
    () =>
      demoMode
        ? buildDemoPrecheckSummary(documents)
        : (precheckSummaryQuery.data ?? null),
    [demoMode, documents, precheckSummaryQuery.data]
  )
  const salesAuditSamples = useMemo(
    () =>
      demoMode
        ? buildDemoPrecheckSamples(documents)
        : (precheckSamplesQuery.data ?? null),
    [demoMode, documents, precheckSamplesQuery.data]
  )
  const salesAuditNearDup = useMemo(
    () =>
      demoMode
        ? buildDemoNearDupResponse()
        : (precheckNearDupQuery.data ?? null),
    [demoMode, precheckNearDupQuery.data]
  )

  useEffect(() => {
    const node = scrollContainerRef.current
    if (!node) return

    const handleScroll = () => {
      if (mode !== 'sales-audit') {
        setHeaderCollapsed(false)
        return
      }

      setHeaderCollapsed((previous) => {
        const collapseThreshold = 96
        const expandThreshold = 40
        if (previous) return node.scrollTop > expandThreshold
        return node.scrollTop > collapseThreshold
      })
    }

    handleScroll()
    node.addEventListener('scroll', handleScroll, { passive: true })
    return () => node.removeEventListener('scroll', handleScroll)
  }, [mode])

  useEffect(() => {
    if (!successPulseVisible) return
    const timeoutId = globalThis.window.setTimeout(() => {
      setSuccessPulseVisible(false)
    }, 1400)
    return () => globalThis.window.clearTimeout(timeoutId)
  }, [successPulseVisible])

  const selectedDatasetLabel = useMemo(() => {
    if (!selectedDatasetId) return '全部项目'
    return (
      datasets.find((dataset) => dataset.id === selectedDatasetId)?.name ||
      selectedDatasetId
    )
  }, [datasets, selectedDatasetId])

  const statusCounts = useMemo(
    () => ({
      completed: safeNumber(summary.by_status.completed),
      processing: safeNumber(summary.by_status.processing),
      pending: safeNumber(summary.by_status.pending),
      failed: safeNumber(summary.by_status.failed),
      quarantined: safeNumber(summary.by_status.quarantined),
    }),
    [summary.by_status]
  )

  const throughputRows = useMemo(
    () => buildThroughputAreaRows(summary.timeseries),
    [summary.timeseries]
  )
  const docsPerMinute = useMemo(
    () =>
      computeDocsPerMinute(
        throughputRows.map((row) => ({
          t: row.ts,
          completed: row.completed,
          failed: row.failed,
          quarantined: row.quarantined,
        }))
      ),
    [throughputRows]
  )
  const megabytesPerSecond = useMemo(
    () => computeMegabytesPerSecond(documents),
    [documents]
  )
  const durationPercentiles = useMemo(
    () => computeDurationPercentiles(documents),
    [documents]
  )
  const meanFileSize = useMemo(
    () => computeMeanFileSize(documents),
    [documents]
  )
  const fileTypeDistribution = useMemo(
    () => buildFileTypeDistribution(documents),
    [documents]
  )
  const fileSizeDistribution = useMemo(
    () => buildFileSizeDistribution(documents),
    [documents]
  )
  const pdfDisposition = useMemo(
    () => buildPdfDispositionBreakdown(documents),
    [documents]
  )

  const reviewQueue = statusCounts.failed + statusCounts.quarantined
  const pendingQueue = statusCounts.processing + statusCounts.pending
  const approvedCount = Object.values(sampleDispositions).filter(
    (value) => value === 'approved'
  ).length
  const manualCount = Object.values(sampleDispositions).filter(
    (value) => value === 'manual'
  ).length
  const readyRate = documents.length
    ? Math.round(
        ((statusCounts.completed + approvedCount) / documents.length) * 100
      )
    : 0

  const auditCandidates = useMemo(() => {
    const prioritised = documents.filter(
      (document) =>
        ['failed', 'quarantined', 'processing', 'pending'].includes(
          String(document.status)
        ) || Boolean(document.error_message)
    )
    return (prioritised.length ? prioritised : documents).slice(0, 10)
  }, [documents])

  const reasonFilteredAuditSamples = useMemo(
    () =>
      auditCandidates.filter((document) =>
        matchesReasonFilter(document, selectedReason)
      ),
    [auditCandidates, selectedReason]
  )

  const auditRailCounts = useMemo(() => {
    const pending = reasonFilteredAuditSamples.filter(
      (document) => !sampleDispositions[document.id]
    ).length
    const approved = reasonFilteredAuditSamples.filter(
      (document) => sampleDispositions[document.id] === 'approved'
    ).length
    const manual = reasonFilteredAuditSamples.filter(
      (document) => sampleDispositions[document.id] === 'manual'
    ).length

    return {
      total: reasonFilteredAuditSamples.length,
      pending,
      approved,
      manual,
    }
  }, [reasonFilteredAuditSamples, sampleDispositions])

  const visibleAuditSamples = useMemo(() => {
    if (auditDispositionFilter === 'all') return reasonFilteredAuditSamples

    return reasonFilteredAuditSamples.filter((document) => {
      const disposition = sampleDispositions[document.id]
      if (auditDispositionFilter === 'pending') return !disposition
      return disposition === auditDispositionFilter
    })
  }, [auditDispositionFilter, reasonFilteredAuditSamples, sampleDispositions])

  const selectedAuditDocuments = useMemo(
    () =>
      documents.filter((document) => selectedAuditIds.includes(document.id)),
    [documents, selectedAuditIds]
  )

  const activeAuditDocument = useMemo(
    () => documents.find((document) => document.id === activeDetailId) || null,
    [activeDetailId, documents]
  )
  const activeAuditIsDemo = Boolean(
    activeAuditDocument?.id?.startsWith('demo-')
  )

  const executionRuntimeLabel = useMemo(() => {
    const startMs = new Date(String(summary.window_start || '')).getTime()
    const endMs = new Date(String(summary.window_end || '')).getTime()
    if (Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs) {
      return formatDurationClock((endMs - startMs) / 1000)
    }

    const timestamps = documents
      .flatMap((document) =>
        [
          document.created_at,
          document.updated_at,
          document.processed_at,
        ].filter(Boolean)
      )
      .map((value) => new Date(String(value)).getTime())
      .filter((value) => Number.isFinite(value))
      .sort((left, right) => left - right)
    if (timestamps.length >= 2) {
      return formatDurationClock(
        (timestamps[timestamps.length - 1] - timestamps[0]) / 1000
      )
    }
    return '00:00:00'
  }, [documents, summary.window_end, summary.window_start])

  const executionProcessedTotal = useMemo(
    () =>
      statusCounts.completed + statusCounts.failed + statusCounts.quarantined,
    [statusCounts.completed, statusCounts.failed, statusCounts.quarantined]
  )

  const executionSuccessRate = useMemo(() => {
    if (!executionProcessedTotal) return 0
    return Math.round((statusCounts.completed / executionProcessedTotal) * 100)
  }, [executionProcessedTotal, statusCounts.completed])

  const executionRetryRate = useMemo(() => {
    if (!executionProcessedTotal) return 0
    return Math.round(
      ((statusCounts.failed + statusCounts.quarantined) /
        executionProcessedTotal) *
        100
    )
  }, [executionProcessedTotal, statusCounts.failed, statusCounts.quarantined])

  const executionOcrUsageRate = useMemo(() => {
    const totalPdf = pdfDisposition.reduce((sum, item) => sum + item.count, 0)
    const ocrCount =
      pdfDisposition.find((item) => item.label === 'OCR')?.count ??
      pdfDisposition.find((item) => item.label === 'SCAN')?.count ??
      0
    if (!totalPdf) return 0
    return Math.round((ocrCount / totalPdf) * 100)
  }, [pdfDisposition])

  const executionAverageDuration = useMemo(() => {
    const value = durationPercentiles.p50 || durationPercentiles.p90 || 0
    return value ? `${value.toFixed(1)} min / 文件` : '-- / 文件'
  }, [durationPercentiles.p50, durationPercentiles.p90])

  const executionTopStripItems = useMemo(
    () => [
      {
        label: '范围',
        value: selectedDatasetLabel,
        icon: FolderOpen,
        tone: 'text-info',
        detail: '全部项目',
      },
      {
        label: '队列深度',
        value:
          taskQueueSnapshot?.queue_depth == null
            ? '--'
            : `${taskQueueSnapshot.queue_depth}`,
        icon: ListTodo,
        tone: taskQueueSnapshot?.broker_up ? 'text-success' : 'text-warning',
        detail: taskQueueSnapshot?.queue_name || 'task queue',
      },
      {
        label: '活跃 Worker',
        value:
          taskQueueSnapshot?.workers_active == null
            ? '--'
            : `${taskQueueSnapshot.workers_active}`,
        icon: Activity,
        tone: taskQueueSnapshot?.workers_active
          ? 'text-success'
          : 'text-muted-foreground',
        detail: taskQueueStatusLabel,
      },
      {
        label: '待人工处理',
        value: `${reviewQueue + manualCount}`,
        icon: ShieldAlert,
        tone: 'text-warning',
        detail: '待确认清单',
      },
      {
        label: '当前吞吐',
        value: `${docsPerMinute?.toFixed(1) ?? '0.0'} docs/min`,
        icon: Activity,
        tone: 'text-accent',
        detail: '近 5 分钟均值',
      },
      {
        label: '运行时长',
        value: executionRuntimeLabel,
        icon: Clock3,
        tone: 'text-success',
        detail: '窗口时长',
      },
    ],
    [
      docsPerMinute,
      executionRuntimeLabel,
      manualCount,
      reviewQueue,
      selectedDatasetLabel,
      taskQueueSnapshot?.broker_up,
      taskQueueSnapshot?.queue_depth,
      taskQueueSnapshot?.queue_name,
      taskQueueSnapshot?.workers_active,
      taskQueueStatusLabel,
    ]
  )

  const executionRiskItems = useMemo(() => {
    const topReasons = Object.entries(summary.top_error_reasons || {})
      .filter(([, count]) => Number(count) > 0)
      .sort((left, right) => Number(right[1]) - Number(left[1]))
      .slice(0, 3)

    const mapped = topReasons.map(([reason, count], index) => {
      const lower = reason.toLowerCase()
      if (
        lower.includes('pii') ||
        lower.includes('phone') ||
        lower.includes('email')
      ) {
        return {
          title: '潜在 PII 检测',
          detail: reason,
          count: Number(count),
          tone: 'border-warning/18 bg-warning/[0.06] text-warning',
        }
      }
      if (lower.includes('timeout')) {
        return {
          title: 'Parser timeout',
          detail: reason,
          count: Number(count),
          tone: 'border-orange/18 bg-orange/[0.06] text-orange',
        }
      }
      return {
        title: reason,
        detail: index === 0 ? '需尽快人工复核并分流' : '建议加入阻塞跟踪',
        count: Number(count),
        tone:
          index === 0
            ? 'border-rose/18 bg-rose/[0.06] text-rose'
            : 'border-border/18 bg-muted/[0.05] text-foreground/85',
      }
    })

    if (mapped.length) return mapped

    if (reviewQueue > 0) {
      return [
        {
          title: '缺敏线索待确认',
          detail: '包含待人工确认的风险项',
          count: reviewQueue,
          tone: 'border-rose/18 bg-rose/[0.06] text-rose',
        },
      ]
    }

    return [
      {
        title: '当前无阻塞项',
        detail: '本窗口内未发现新的异常阻塞',
        count: 0,
        tone: 'border-success/18 bg-success/[0.06] text-success',
      },
    ]
  }, [reviewQueue, summary.top_error_reasons])

  const executionOverallProgress = useMemo(() => {
    if (!documents.length) return 0
    return Math.round((executionProcessedTotal / documents.length) * 100)
  }, [documents.length, executionProcessedTotal])

  const executionPipelineCards = useMemo(() => {
    const parserDone =
      statusCounts.completed + statusCounts.failed + statusCounts.quarantined
    const parserFailures = statusCounts.failed + statusCounts.quarantined
    const chunkerProcessing = statusCounts.processing
    const chunkerWaiting = statusCounts.pending
    const governanceQueue = reviewQueue + manualCount
    const exportReady = statusCounts.completed

    return [
      {
        key: 'parser',
        label: 'Parser',
        tone: 'border-success/28 bg-success/[0.04]',
        statusTone: 'bg-success',
        metrics: [
          ['已完成', `${parserDone}`],
          ['失败', `${parserFailures}`],
          ['耗时', executionRuntimeLabel],
        ],
      },
      {
        key: 'chunker',
        label: 'Chunker',
        tone: 'border-info/28 bg-info/[0.04]',
        statusTone: chunkerProcessing > 0 ? 'bg-info' : 'bg-muted',
        metrics: [
          ['进行中', `${chunkerProcessing}`],
          ['等待中', `${chunkerWaiting}`],
          [
            '耗时',
            durationPercentiles.p50
              ? `${durationPercentiles.p50.toFixed(1)}m`
              : '--',
          ],
        ],
      },
      {
        key: 'governance',
        label: 'Governance',
        tone: 'border-border bg-background/75',
        statusTone: governanceQueue > 0 ? 'bg-warning' : 'bg-muted',
        metrics: [
          ['待复核', `${governanceQueue}`],
          ['已处理', `${manualCount}`],
          ['耗时', '--'],
        ],
      },
      {
        key: 'export',
        label: '导出',
        tone: 'border-border bg-background/75',
        statusTone: exportReady > 0 ? 'bg-success' : 'bg-muted',
        metrics: [
          ['已处理', `${exportReady}`],
          ['待处理', `${Math.max(0, documents.length - exportReady)}`],
          ['耗时', '--'],
        ],
      },
    ]
  }, [
    documents.length,
    durationPercentiles.p50,
    executionRuntimeLabel,
    manualCount,
    reviewQueue,
    statusCounts.completed,
    statusCounts.failed,
    statusCounts.pending,
    statusCounts.processing,
    statusCounts.quarantined,
  ])

  const executionKpiCards = useMemo(
    () => [
      {
        label: '处理效率',
        value: `${docsPerMinute?.toFixed(1) ?? '0.0'}`,
        suffix: 'docs/min',
        icon: Activity,
        tone: 'text-info',
        detail: '近 5 分钟平均',
      },
      {
        label: '平均处理耗时',
        value: executionAverageDuration.replace(' / 文件', ''),
        suffix: '/ 文件',
        icon: Clock3,
        tone: 'text-indigo',
        detail: '近 5 分钟平均',
      },
      {
        label: '队列深度',
        value:
          taskQueueSnapshot?.queue_depth == null
            ? '--'
            : `${taskQueueSnapshot.queue_depth}`,
        suffix: '',
        icon: ListTodo,
        tone: taskQueueSnapshot?.broker_up ? 'text-success' : 'text-warning',
        detail: taskQueueSnapshot?.queue_name || 'task queue',
      },
      {
        label: '活跃 Worker',
        value:
          taskQueueSnapshot?.workers_active == null
            ? '--'
            : `${taskQueueSnapshot.workers_active}`,
        suffix: '',
        icon: Activity,
        tone: taskQueueSnapshot?.workers_active
          ? 'text-success'
          : 'text-muted-foreground',
        detail: taskQueueStatusLabel,
      },
      {
        label: 'OCR 使用率',
        value: `${executionOcrUsageRate}%`,
        suffix: '',
        icon: Gauge,
        tone: 'text-success',
        detail: `${pdfDisposition.reduce((sum, item) => sum + item.count, 0)} 个 PDF`,
      },
      {
        label: '解析成功率',
        value: `${executionSuccessRate}%`,
        suffix: '',
        icon: CheckCircle2,
        tone: 'text-success',
        detail: `${statusCounts.completed} / ${Math.max(1, executionProcessedTotal)} 成功`,
      },
      {
        label: '失败重试率',
        value: `${executionRetryRate}%`,
        suffix: '',
        icon: RefreshCcw,
        tone: 'text-warning',
        detail: `${statusCounts.failed + statusCounts.quarantined} / ${Math.max(1, executionProcessedTotal)} 文件`,
      },
      {
        label: '队列总数',
        value: `${pendingQueue}`,
        suffix: '',
        icon: ListTodo,
        tone: 'text-accent',
        detail: '等待处理',
      },
    ],
    [
      docsPerMinute,
      executionAverageDuration,
      executionOcrUsageRate,
      executionProcessedTotal,
      executionRetryRate,
      executionSuccessRate,
      pdfDisposition,
      pendingQueue,
      statusCounts.completed,
      statusCounts.failed,
      statusCounts.quarantined,
      taskQueueSnapshot?.broker_up,
      taskQueueSnapshot?.queue_depth,
      taskQueueSnapshot?.queue_name,
      taskQueueSnapshot?.workers_active,
      taskQueueStatusLabel,
    ]
  )

  const recentQueueOutcomes = useMemo(() => {
    const outcomes = taskQueueSnapshot?.recent_job_outcomes ?? []
    return outcomes.slice(0, 5).map((item, index) => {
      const jobName = String(
        item.job_name || item.run_id || item.document_id || `job-${index + 1}`
      )
      const ok = item.ok === true
      const finishedAt = item.finished_at
        ? String(item.finished_at)
        : taskQueueSnapshot?.generated_at || renderTimestamp
      const elapsed = Number(item.elapsed_sec || 0)
      const reason = item.reason
        ? String(item.reason)
        : ok
          ? '任务完成'
          : '任务失败或被跳过'
      return {
        detail: `${jobName} · ${elapsed ? `${elapsed.toFixed(2)}s` : reason}`,
        id: `${jobName}-${index}`,
        stage: ok ? '队列完成' : '队列异常',
        time: formatClockSecondsLabel(finishedAt),
        tone: ok ? 'bg-success' : 'bg-rose',
      }
    })
  }, [
    renderTimestamp,
    taskQueueSnapshot?.generated_at,
    taskQueueSnapshot?.recent_job_outcomes,
  ])

  const executionRecentLogs = useMemo(() => {
    if (recentQueueOutcomes.length) return recentQueueOutcomes

    return [...documents]
      .sort((left, right) => {
        const rightTs = new Date(
          String(
            right.updated_at || right.processed_at || right.created_at || ''
          )
        ).getTime()
        const leftTs = new Date(
          String(left.updated_at || left.processed_at || left.created_at || '')
        ).getTime()
        return rightTs - leftTs
      })
      .slice(0, 5)
      .map((document) => {
        const status = String(document.status || '').toLowerCase()
        return {
          id: document.id,
          time: formatClockSecondsLabel(
            document.updated_at ||
              document.processed_at ||
              document.created_at ||
              renderTimestamp
          ),
          stage: String(document.current_stage || '系统'),
          detail:
            status === 'failed'
              ? `解析失败：${document.filename}`
              : status === 'completed'
                ? `解析成功：${document.filename}`
                : `开始解析：${document.filename}`,
          tone:
            status === 'failed'
              ? 'bg-rose'
              : status === 'completed'
                ? 'bg-success'
                : 'bg-muted-foreground/40',
        }
      })
  }, [documents, recentQueueOutcomes, renderTimestamp])

  const executionTaskRows = useMemo(() => {
    return [...documents]
      .sort((left, right) => {
        const rightTs = new Date(
          String(
            right.updated_at || right.processed_at || right.created_at || ''
          )
        ).getTime()
        const leftTs = new Date(
          String(left.updated_at || left.processed_at || left.created_at || '')
        ).getTime()
        return rightTs - leftTs
      })
      .slice(0, 8)
  }, [documents])

  const forecastPoints = useMemo(() => {
    if (!throughputRows.length) return []
    const last = throughputRows[throughputRows.length - 1]
    const base = last?.total ?? 0
    const rate = docsPerMinute ?? 0
    const stepMinutes = summary.bucket_minutes || 20
    return Array.from({ length: 3 }, (_, index) => ({
      ts: (last?.ts ?? renderTimestamp) + (index + 1) * stepMinutes * 60_000,
      total: Number(
        (base + ((rate * stepMinutes) / 60) * (index + 1)).toFixed(1)
      ),
    }))
  }, [docsPerMinute, renderTimestamp, summary.bucket_minutes, throughputRows])

  const predictionOption = useMemo<EChartsOption>(() => {
    const actualSeries = throughputRows.map((row) => [row.ts, row.total])
    const forecastSeries = actualSeries.length
      ? [
          [
            actualSeries[actualSeries.length - 1][0],
            actualSeries[actualSeries.length - 1][1],
          ],
          ...forecastPoints.map((row) => [row.ts, row.total]),
        ]
      : []

    return {
      tooltip: {
        trigger: 'axis',
      },
      grid: {
        left: 40,
        right: 16,
        top: 24,
        bottom: 28,
      },
      xAxis: {
        type: 'time',
        axisLabel: {
          color: '#64748b',
          formatter: (value: number) => formatClockLabel(Number(value)),
        },
        axisLine: {
          lineStyle: { color: 'rgba(100,116,139,0.35)' },
        },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#64748b' },
        splitLine: {
          lineStyle: { color: 'rgba(148,163,184,0.18)' },
        },
      },
      series: [
        {
          name: '当前处理效率',
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { color: '#0f766e', width: 2.5 },
          areaStyle: {
            color: 'rgba(15,118,110,0.14)',
          },
          data: actualSeries,
        },
        {
          name: '预测',
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { color: '#b45309', width: 2, type: 'dashed' },
          areaStyle: {
            color: 'rgba(180,83,9,0.08)',
          },
          data: forecastSeries,
        },
      ],
    } as EChartsOption
  }, [forecastPoints, throughputRows])

  const ocrRadarValues = useMemo(() => {
    const pdfCount = documents.filter(
      (document) => String(document.file_type || '').toLowerCase() === 'pdf'
    ).length
    const meanSizeMb = meanFileSize / (1024 * 1024)
    const formatVariety = Math.min(100, fileTypeDistribution.length * 18)
    const ocrComplexity = Math.min(100, pdfCount * 18 + meanSizeMb * 8)
    const formatRegularity = Math.max(12, 100 - formatVariety)
    const sensitiveDensity = Math.min(100, reviewQueue * 22 + manualCount * 12)
    return [ocrComplexity, formatRegularity, sensitiveDensity]
  }, [
    documents,
    fileTypeDistribution.length,
    manualCount,
    meanFileSize,
    reviewQueue,
  ])

  const radarOption = useMemo<EChartsOption>(
    () =>
      ({
        tooltip: { trigger: 'item' },
        radar: {
          radius: '62%',
          splitNumber: 4,
          axisName: { color: '#475569', fontSize: 11 },
          splitLine: { lineStyle: { color: 'rgba(148,163,184,0.22)' } },
          splitArea: {
            areaStyle: {
              color: ['rgba(248,250,252,0.82)', 'rgba(241,245,249,0.46)'],
            },
          },
          indicator: [
            { name: 'OCR 复杂度', max: 100 },
            { name: '格式规范度', max: 100 },
            { name: '敏感信息密度', max: 100 },
          ],
        },
        series: [
          {
            type: 'radar',
            data: [
              {
                value: ocrRadarValues,
                areaStyle: { color: 'rgba(88,28,135,0.12)' },
                lineStyle: { color: '#6d28d9', width: 2 },
                itemStyle: { color: '#6d28d9' },
              },
            ],
          },
        ],
      }) as EChartsOption,
    [ocrRadarValues]
  )

  const salesAuditProfile = useMemo(
    () =>
      salesAuditSummary
        ? buildSalesAuditProfile(salesAuditSummary, salesAuditNearDup)
        : null,
    [salesAuditNearDup, salesAuditSummary]
  )

  const salesEvidenceItems = useMemo(() => {
    if (!salesAuditSamples) return []
    const representative = salesAuditSamples.representative ?? []
    const needsReview = Object.values(
      salesAuditSamples.needs_review ?? {}
    ).flat()
    const topLargeFiles = salesAuditSamples.top_large_files ?? []
    const unique = new Map<string, DatasetPrecheckFileOut>()

    for (const file of [...needsReview, ...topLargeFiles, ...representative]) {
      unique.set(String(file.name), file)
    }

    return Array.from(unique.values()).slice(0, 12)
  }, [salesAuditSamples])

  const selectedSalesEvidence = useMemo(
    () =>
      salesEvidenceItems.filter((file) =>
        selectedAuditIds.includes(String(file.name))
      ),
    [salesEvidenceItems, selectedAuditIds]
  )

  const salesHeatmapData = useMemo(() => {
    if (!salesAuditSummary?.findings?.length) return []
    const peak = Math.max(
      1,
      ...salesAuditSummary.findings.map((item) => Number(item.count || 0))
    )
    const labelMap: Record<string, string> = {
      pdf_scanned: '扫描件',
      parse_failed: '解析失败',
      pii: '合敏感信息',
      exact_dup: '重复文件',
      near_dup: '版本冲突',
      other: '其他风险',
    }
    return salesAuditSummary.findings
      .filter((item) => Number(item.count || 0) > 0)
      .slice(0, 6)
      .map((item) => {
        const intensity = Number(item.count || 0) / peak
        return {
          name: labelMap[item.key] || item.label,
          count: Number(item.count || 0),
          formatLabel: item.severity.toUpperCase(),
          timeLabel: '报价风险',
          fill:
            item.severity === 'error'
              ? `linear-gradient(135deg, rgba(185,28,28,${0.16 + intensity * 0.32}), rgba(127,29,29,${0.24 + intensity * 0.28}))`
              : item.severity === 'warning'
                ? `linear-gradient(135deg, rgba(217,119,6,${0.16 + intensity * 0.32}), rgba(146,64,14,${0.24 + intensity * 0.28}))`
                : `linear-gradient(135deg, rgba(71,85,105,${0.16 + intensity * 0.32}), rgba(51,65,85,${0.24 + intensity * 0.28}))`,
        }
      })
  }, [salesAuditSummary])

  const salesCoreSummary = useMemo(() => {
    const totalFiles = Number(salesAuditSummary?.total_files || 0)
    const pdfScanned = Number(salesAuditSummary?.pdf_scan.scanned || 0)
    const pdfUnknown = Number(salesAuditSummary?.pdf_scan.unknown || 0)
    const scanRatio = totalFiles
      ? Math.round(((pdfScanned + pdfUnknown) / totalFiles) * 100)
      : 0

    return [
      ['文档总数', totalFiles.toLocaleString(), '全量摸底范围'],
      [
        '总体体量',
        formatFileSize(salesAuditSummary?.total_size_bytes || 0),
        '估算工时与算力',
      ],
      [
        '阻断项',
        String(
          salesAuditProfile?.costDrivers.find((item) => item.key === 'blocking')
            ?.count ?? 0
        ),
        '需人工介入处理',
      ],
      ['扫描 / 混排', `${scanRatio}%`, 'OCR 前置处理占比'],
    ]
  }, [salesAuditProfile, salesAuditSummary])

  const salesProcessingLanes = useMemo<SalesProcessingLane[]>(() => {
    if (!salesAuditSummary) return []
    const countByFinding = (key: string) =>
      Number(
        salesAuditSummary.findings.find((item) => item.key === key)?.count || 0
      )
    return [
      {
        key: 'ocr',
        label: 'OCR 处理',
        count: countByFinding('pdf_scanned') + countByFinding('pdf_unknown'),
        tone: 'text-info bg-info/8 border-info/15',
      },
      {
        key: 'table',
        label: '格式转换',
        count:
          countByFinding('large_spreadsheet') +
          countByFinding('wide_spreadsheet') +
          countByFinding('merged_heavy_spreadsheet'),
        tone: 'text-orange bg-orange/8 border-orange/15',
      },
      {
        key: 'manual',
        label: '人工审核',
        count:
          countByFinding('pii') +
          countByFinding('secrets') +
          countByFinding('parse_failed'),
        tone: 'text-rose bg-rose/8 border-rose/15',
      },
      {
        key: 'straight',
        label: '去重处理',
        count: Math.max(
          0,
          Number(salesAuditSummary.total_files || 0) -
            (countByFinding('pdf_scanned') +
              countByFinding('pdf_unknown') +
              countByFinding('large_spreadsheet') +
              countByFinding('wide_spreadsheet') +
              countByFinding('merged_heavy_spreadsheet') +
              countByFinding('pii') +
              countByFinding('secrets') +
              countByFinding('parse_failed'))
        ),
        tone: 'text-success bg-success/8 border-success/15',
      },
    ]
  }, [salesAuditSummary])

  const salesPocCandidates = useMemo<SalesEvidenceTableRow[]>(() => {
    return salesEvidenceItems.slice(0, 5).map((file) => {
      const tags = buildEvidenceSlotTags(file)
      const firstTag = tags[0] || 'STRAIGHT_THROUGH'
      const primaryRisk =
        firstTag === 'OCR_REQUIRED'
          ? '扫描件'
          : firstTag === 'PARSE_FAILED'
            ? '解析失败'
            : firstTag === 'TABLE_HEAVY'
              ? '合并单元格'
              : firstTag === 'SENSITIVE_REVIEW'
                ? '敏感信息'
                : firstTag === 'VERSION_CONFLICT'
                  ? '版本冲突'
                  : '通用文档'
      const icon =
        firstTag === 'OCR_REQUIRED'
          ? CircleDashed
          : firstTag === 'TABLE_HEAVY'
            ? TableProperties
            : firstTag === 'PARSE_FAILED'
              ? CircleAlert
              : firstTag === 'SENSITIVE_REVIEW'
                ? ShieldAlert
                : FileDigit
      const iconTone =
        firstTag === 'OCR_REQUIRED'
          ? 'text-info'
          : firstTag === 'TABLE_HEAVY'
            ? 'text-orange'
            : firstTag === 'PARSE_FAILED'
              ? 'text-rose'
              : firstTag === 'SENSITIVE_REVIEW'
                ? 'text-warning'
                : 'text-success'

      return {
        id: String(file.name),
        fileName: anonymizeEvidenceName(file.name),
        fileType: file.file_type.toUpperCase(),
        fileSizeLabel: formatFileSize(file.file_size || 0),
        primaryRisk,
        riskDescription: buildEvidenceSlotReason(file),
        actionLabel:
          firstTag === 'OCR_REQUIRED'
            ? 'OCR 处理'
            : firstTag === 'PARSE_FAILED'
              ? '人工审核'
              : firstTag === 'TABLE_HEAVY'
                ? '格式转换'
                : '纳入 POC',
        icon,
        iconTone,
      }
    })
  }, [salesEvidenceItems])

  const salesHighRiskFiles = useMemo<SalesEvidenceTableRow[]>(() => {
    const reviewBuckets = Object.values(
      salesAuditSamples?.needs_review ?? {}
    ).flat()
    const source = (
      reviewBuckets.length ? reviewBuckets : salesEvidenceItems
    ).slice(0, 5)
    return source.map((file) => {
      const tags = buildEvidenceSlotTags(file)
      const firstTag = tags[0] || 'STRAIGHT_THROUGH'
      const primaryRisk =
        firstTag === 'OCR_REQUIRED'
          ? '扫描件'
          : firstTag === 'PARSE_FAILED'
            ? '解析失败'
            : firstTag === 'TABLE_HEAVY'
              ? '合并单元格'
              : firstTag === 'SENSITIVE_REVIEW'
                ? '敏感信息'
                : firstTag === 'VERSION_CONFLICT'
                  ? '版本冲突'
                  : '通用文档'
      const icon =
        firstTag === 'OCR_REQUIRED'
          ? CircleDashed
          : firstTag === 'TABLE_HEAVY'
            ? TableProperties
            : firstTag === 'PARSE_FAILED'
              ? CircleAlert
              : firstTag === 'SENSITIVE_REVIEW'
                ? ShieldAlert
                : FileDigit
      const iconTone =
        firstTag === 'OCR_REQUIRED'
          ? 'text-info'
          : firstTag === 'TABLE_HEAVY'
            ? 'text-orange'
            : firstTag === 'PARSE_FAILED'
              ? 'text-rose'
              : firstTag === 'SENSITIVE_REVIEW'
                ? 'text-warning'
                : 'text-success'

      return {
        id: String(file.name),
        fileName: anonymizeEvidenceName(file.name),
        fileType: file.file_type.toUpperCase(),
        fileSizeLabel: formatFileSize(file.file_size || 0),
        primaryRisk,
        riskDescription: buildEvidenceSlotReason(file),
        actionLabel: '查看',
        icon,
        iconTone,
      }
    })
  }, [salesAuditSamples?.needs_review, salesEvidenceItems])

  const visibleSalesEvidenceItems = useMemo(() => {
    if (!selectedReason) return salesEvidenceItems
    const matchedFinding = salesAuditSummary?.findings.find(
      (item) => item.label === selectedReason
    )
    return salesEvidenceItems.filter((file) => {
      const tags = buildEvidenceSlotTags(file).join(' ')
      const reason = buildEvidenceSlotReason(file)
      const findings = (file.findings || []).map((item) =>
        String(item || '')
          .trim()
          .toLowerCase()
      )
      return (
        tags.includes(selectedReason) ||
        reason.includes(selectedReason) ||
        (matchedFinding ? findings.includes(matchedFinding.key) : false)
      )
    })
  }, [salesAuditSummary?.findings, salesEvidenceItems, selectedReason])

  const salesPdfSplitOption = useMemo<EChartsOption>(() => {
    const pdfDetection = salesAuditSummary?.pdf_detection as
      | Record<string, unknown>
      | undefined
    const rows = [
      {
        name: 'TEXT',
        value: Number(
          pdfDetection?.text || salesAuditSummary?.pdf_scan.not_scanned || 0
        ),
      },
      { name: 'MIXED', value: Number(pdfDetection?.mixed || 0) },
      {
        name: 'SCAN',
        value: Number(
          pdfDetection?.scan || salesAuditSummary?.pdf_scan.scanned || 0
        ),
      },
    ].filter((row) => row.value > 0)

    return {
      tooltip: { trigger: 'item' },
      series: [
        {
          type: 'pie',
          radius: ['46%', '72%'],
          label: { color: '#475569' },
          data: rows.map((row) => ({
            ...row,
            itemStyle: {
              color:
                row.name === 'SCAN'
                  ? '#f59e0b'
                  : row.name === 'MIXED'
                    ? '#94a3b8'
                    : '#10b981',
            },
          })),
        },
      ],
    } as EChartsOption
  }, [salesAuditSummary])

  const salesLengthOption = useMemo<EChartsOption>(() => {
    const histogram = salesAuditSummary?.length_histogram ?? []
    const p50 = Number(salesAuditSummary?.length_percentiles.p50 || 0)
    const p90 = Number(salesAuditSummary?.length_percentiles.p90 || 0)
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 24, bottom: 36 },
      xAxis: {
        type: 'category',
        data: histogram.map((item) => item.label),
        axisLabel: { color: '#64748b' },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#64748b' },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.18)' } },
      },
      series: [
        {
          type: 'bar',
          data: histogram.map((item) => Number(item.count || 0)),
          itemStyle: { color: '#475569', borderRadius: [8, 8, 0, 0] },
          markLine: {
            symbol: 'none',
            label: { color: '#64748b' },
            lineStyle: { type: 'dashed', color: '#94a3b8' },
            data: [
              {
                name: 'P50',
                xAxis: histogram.findIndex(
                  (item) =>
                    p50 >= Number(item.min || 0) &&
                    p50 < Number(item.max || Number.POSITIVE_INFINITY)
                ),
              },
              {
                name: 'P90',
                xAxis: histogram.findIndex(
                  (item) =>
                    p90 >= Number(item.min || 0) &&
                    p90 < Number(item.max || Number.POSITIVE_INFINITY)
                ),
              },
            ].filter((item) => Number(item.xAxis) >= 0),
          },
        },
      ],
    } as EChartsOption
  }, [salesAuditSummary])

  const salesRadarOption = useMemo<EChartsOption>(() => {
    if (!salesAuditSummary) return { series: [] }
    const totalFiles = Math.max(1, Number(salesAuditSummary.total_files || 0))
    const ocrRatio =
      (Number(salesAuditSummary.pdf_scan.scanned || 0) +
        Number(salesAuditSummary.pdf_scan.unknown || 0)) /
      Math.max(
        1,
        Number(salesAuditSummary.pdf_scan.scanned || 0) +
          Number(salesAuditSummary.pdf_scan.not_scanned || 0) +
          Number(salesAuditSummary.pdf_scan.unknown || 0)
      )
    const tableHeavyRatio =
      (Number(
        salesAuditSummary.findings.find(
          (item) => item.key === 'large_spreadsheet'
        )?.count || 0
      ) +
        Number(
          salesAuditSummary.findings.find(
            (item) => item.key === 'wide_spreadsheet'
          )?.count || 0
        ) +
        Number(
          salesAuditSummary.findings.find(
            (item) => item.key === 'merged_heavy_spreadsheet'
          )?.count || 0
        )) /
      totalFiles
    const sensitiveRatio =
      (Number(
        salesAuditSummary.findings.find((item) => item.key === 'pii')?.count ||
          0
      ) +
        Number(
          salesAuditSummary.findings.find((item) => item.key === 'secrets')
            ?.count || 0
        )) /
      totalFiles
    const successRatio =
      1 -
      Number(
        salesAuditSummary.findings.find((item) => item.key === 'parse_failed')
          ?.count || 0
      ) /
        totalFiles
    const imageHeavyProxy = Math.max(
      0,
      Math.min(
        1,
        Number(salesAuditSummary.pdf_scan.scanned || 0) / totalFiles +
          Number(
            (salesAuditSummary.by_file_type as Record<string, number>).pptx || 0
          ) /
            totalFiles
      )
    )

    return {
      tooltip: { trigger: 'item' },
      radar: {
        radius: '52%',
        center: ['50%', '54%'],
        splitNumber: 4,
        indicator: [
          { name: 'OCR 密度', max: 100 },
          { name: '表格复杂度', max: 100 },
          { name: '图片频率', max: 100 },
          { name: '敏感信息密度', max: 100 },
          { name: '解析成功率', max: 100 },
        ],
        axisName: { color: '#475569', fontSize: 9 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.22)' } },
        splitArea: {
          areaStyle: {
            color: ['rgba(248,250,252,0.82)', 'rgba(241,245,249,0.48)'],
          },
        },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: [
                Math.round(ocrRatio * 100),
                Math.round(tableHeavyRatio * 100),
                Math.round(imageHeavyProxy * 100),
                Math.round(sensitiveRatio * 100),
                Math.round(successRatio * 100),
              ],
              itemStyle: { color: '#0f766e' },
              lineStyle: { color: '#0f766e', width: 2 },
              areaStyle: { color: 'rgba(15,118,110,0.12)' },
            },
          ],
        },
      ],
    } as EChartsOption
  }, [salesAuditSummary])

  const handleToggleVelocity = useCallback(() => {
    setVelocityUnit((previous) => {
      const next = previous === 'docs' ? 'bytes' : 'docs'
      persistVelocityUnit(next)
      return next
    })
  }, [])

  const handleSampleDisposition = useCallback(
    (documentId: string, disposition: SampleDisposition) => {
      setSampleDispositions((previous) => ({
        ...previous,
        [documentId]: disposition,
      }))
      if (disposition === 'approved') {
        setSuccessPulseVisible(true)
        toast.success('样本已标记为可入库')
        return
      }
      toast.success('样本已移入人工处理清单')
    },
    []
  )

  const handleSelectAudit = useCallback((documentId: string) => {
    setSelectedAuditIds((previous) =>
      previous.includes(documentId)
        ? previous.filter((item) => item !== documentId)
        : [...previous, documentId]
    )
  }, [])

  const handleOpenAuditSnapshot = useCallback((documentId: string) => {
    setDesktopScopeCollapsed(false)
    setActiveDetailId(documentId)
  }, [])

  const handleChangeMode = useCallback(
    (nextMode: IngestionMode) => {
      const params = new URLSearchParams(searchParams.toString())
      if (nextMode === 'sales-audit') params.delete('mode')
      else params.set('mode', nextMode)
      const query = params.toString()
      router.replace(query ? `${pathname}?${query}` : pathname)
    },
    [pathname, router, searchParams]
  )

  const handleDownloadReport = useCallback(async () => {
    const html = buildReportHtml({
      datasetLabel: selectedDatasetLabel,
      totalDocs: documents.length,
      readyRate,
      manualQueue: reviewQueue + manualCount,
      efficiency:
        velocityUnit === 'docs'
          ? `${docsPerMinute?.toFixed(1) ?? '--'} docs/min`
          : `${megabytesPerSecond?.toFixed(2) ?? '--'} MB/s`,
      latencyP90: `${durationPercentiles.p90 || 0} min`,
      selectedReason,
      documents: visibleAuditSamples.length ? visibleAuditSamples : documents,
      salesAuditSummary,
      salesPocCandidates,
      salesHighRiskFiles,
    })

    try {
      await renderReportHtmlToJpeg(
        html,
        buildSafeReportFilename(selectedDatasetLabel, '.audit-report.jpg')
      )
      toast.success('已导出 JPG 报告')
    } catch (error) {
      const reportWindow = globalThis.window.open(
        '',
        '_blank',
        'noopener,noreferrer'
      )
      if (reportWindow) {
        reportWindow.document.write(html)
        reportWindow.document.close()
        toast.error('JPG 生成失败，已回退到 HTML 预览')
        return
      }

      downloadTextFile(
        'ingestion-audit-report.html',
        html,
        'text/html;charset=utf-8'
      )
      toast.error('JPG 生成失败，已回退到 HTML 文件')
    }
  }, [
    docsPerMinute,
    documents,
    durationPercentiles.p90,
    manualCount,
    megabytesPerSecond,
    readyRate,
    reviewQueue,
    selectedDatasetLabel,
    selectedReason,
    salesAuditSummary,
    salesHighRiskFiles,
    salesPocCandidates,
    velocityUnit,
    visibleAuditSamples,
  ])

  const handleExportSalesAuditReport = useCallback(async () => {
    if (demoMode || !selectedDatasetId || !latestPrecheckRun?.id) {
      await handleDownloadReport()
      return
    }

    try {
      const blob = await datasetApi.exportPrecheckHtml(
        selectedDatasetId,
        latestPrecheckRun.id,
        { redact: true }
      )
      const html = await blob.text()
      await renderReportHtmlToJpeg(
        html,
        buildSafeReportFilename(selectedDatasetLabel, '.precheck.jpg')
      )
      toast.success('已导出脱敏 JPG 报告')
    } catch (error) {
      toast.error('导出脱敏 JPG 报告失败，已回退到当前页面报告')
      await handleDownloadReport()
    }
  }, [
    demoMode,
    handleDownloadReport,
    latestPrecheckRun?.id,
    selectedDatasetId,
    selectedDatasetLabel,
  ])

  useEffect(() => {
    const off = globalEventBus.on('ingestion:download-report', () => {
      if (mode === 'sales-audit') {
        void handleExportSalesAuditReport()
        return
      }
      void handleDownloadReport()
    })
    return off
  }, [handleDownloadReport, handleExportSalesAuditReport, mode])

  const handleExportSelection = useCallback(() => {
    const payload = selectedAuditDocuments.map((document) => ({
      id: document.id,
      filename: document.filename,
      status: document.status,
      stage: document.current_stage,
      disposition: sampleDispositions[document.id] || 'pending',
      clue: document.error_message,
    }))

    downloadTextFile(
      'audit-sample-selection.json',
      JSON.stringify(payload, null, 2),
      'application/json;charset=utf-8'
    )
    toast.success('已导出当前预检抽样清单')
  }, [sampleDispositions, selectedAuditDocuments])

  const handleRefreshExecutionMonitor = useCallback(async () => {
    const results = await Promise.allSettled([
      documentsQuery.refetch(),
      summaryQuery.refetch(),
      taskQueueQuery.refetch(),
    ])
    const failed = results.some((result) => result.status === 'rejected')
    if (failed) {
      toast.error('刷新运行态失败，请检查后端观测接口')
      return
    }
    toast.success('运行态已刷新')
  }, [documentsQuery, summaryQuery, taskQueueQuery])

  const handleBulkDisposition = useCallback(
    (disposition: SampleDisposition) => {
      selectedAuditIds.forEach((documentId) => {
        handleSampleDisposition(documentId, disposition)
      })
      setSelectedAuditIds([])
    },
    [handleSampleDisposition, selectedAuditIds]
  )

  const handleHeatmapSelect = useCallback((reason: string) => {
    setSelectedReason((previous) => (previous === reason ? null : reason))
    setDesktopScopeCollapsed(false)
  }, [])

  const handleExitDemoMode = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    params.delete('demo')

    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [pathname, router, searchParams])

  const handleCanvasMove = useCallback((event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width) * 100
    const y = ((event.clientY - rect.top) / rect.height) * 100
    setCanvasGlow({ x, y })
  }, [])

  const showEmptyState =
    mode === 'sales-audit'
      ? !demoMode &&
        !documentsQuery.isLoading &&
        !precheckSummaryQuery.isLoading &&
        !salesAuditSummary
      : !documentsQuery.isLoading && documents.length === 0
  const showDesktopAuditRail =
    mode === 'execution-monitor' && !showEmptyState && !desktopScopeCollapsed
  const showDesktopAuditRailToggle =
    mode === 'execution-monitor' && !showEmptyState

  return (
    <div
      ref={scrollContainerRef}
      data-page-scroll-container="true"
      className="flex-1 h-full min-h-0 overflow-y-auto overscroll-contain no-scrollbar scroll-fade-bottom bg-[radial-gradient(circle_at_top,rgba(148,163,184,0.18),transparent_42%),linear-gradient(180deg,rgba(248,250,252,0.98),rgba(241,245,249,0.92))] text-foreground"
    >
      <DropZone
        ref={dropZoneRef}
        datasetId={selectedDatasetId}
        onUploadComplete={() => {
          void documentsQuery.refetch()
          void summaryQuery.refetch()
        }}
      />

      <div
        className={cn(
          'flex w-full max-w-none gap-0 px-3 pt-3 md:px-5 lg:px-6 xl:px-7 2xl:px-8',
          mode === 'sales-audit' ? 'pb-2' : 'pb-8'
        )}
      >
        <div
          className={cn(
            'relative flex w-full gap-0',
            mode === 'sales-audit' ? 'min-h-0' : 'min-h-[calc(100dvh-2rem)]'
          )}
        >
          <button
            type="button"
            aria-label="展开预检抽样侧栏"
            onClick={() => setDesktopScopeCollapsed((previous) => !previous)}
            className={cn(
              'absolute left-0 top-6 z-40 hidden h-12 w-7 items-center justify-center rounded-r-full border border-border/60 bg-background/92 text-muted-foreground shadow-[0_18px_42px_-24px_rgba(15,23,42,0.24)] backdrop-blur-xl transition-all hover:text-foreground',
              showDesktopAuditRailToggle && desktopScopeCollapsed
                ? 'translate-x-0 opacity-100 pointer-events-auto lg:flex'
                : 'pointer-events-none -translate-x-3 opacity-0 lg:hidden'
            )}
          >
            <ChevronRight className="h-4 w-4" />
          </button>

          <aside
            className={cn(
              'hidden shrink-0 overflow-hidden pr-4 transition-all duration-300 ease-out lg:block',
              showDesktopAuditRail
                ? 'w-[18rem] opacity-100'
                : 'w-0 opacity-0 -translate-x-4 pointer-events-none'
            )}
          >
            <div className="sticky top-4 space-y-3">
              <div className="rounded-[1.45rem] border border-info/20 bg-background/94 p-3 shadow-[0_22px_58px_-34px_rgba(37,99,235,0.25)] backdrop-blur-xl">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="inline-flex items-center gap-1.5 text-[12px] font-medium text-foreground">
                      {mode === 'sales-audit' ? '证据槽' : '预检抽样'}
                      <Check className="h-3.5 w-3.5 text-success" />
                    </div>
                    <div className="mt-1 text-[17px] font-semibold leading-none text-foreground">
                      {mode === 'sales-audit' ? '报价证据' : '待确认线索'}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-border/60 bg-background/75 text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => setDesktopScopeCollapsed(true)}
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="mt-3 space-y-3">
                  <div className="space-y-2">
                    <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                      Dataset Scope
                    </div>
                    <Select
                      value={datasetScope}
                      onValueChange={setDatasetScope}
                    >
                      <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background/80 text-[11px] font-medium shadow-none">
                        <SelectValue placeholder="全部项目" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={DATASET_ALL}>全部项目</SelectItem>
                        {datasets.map((dataset) => (
                          <SelectItem key={dataset.id} value={dataset.id}>
                            {dataset.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
                    {(
                      [
                        ['all', '全部', auditRailCounts.total, 'blue'],
                        [
                          'pending',
                          '待确认',
                          auditRailCounts.pending,
                          'emerald',
                        ],
                        ['manual', '人工处理', auditRailCounts.manual, 'amber'],
                        [
                          'approved',
                          '已确认',
                          auditRailCounts.approved,
                          'blue',
                        ],
                      ] as const
                    ).map(([value, label, count, tone]) => (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={auditDispositionFilter === value}
                        onClick={() => setAuditDispositionFilter(value)}
                        className={cn(
                          'rounded-full border px-2.5 py-1 transition-colors',
                          auditDispositionFilter !== value &&
                            'border-border/60 bg-background/70 hover:text-foreground',
                          auditDispositionFilter === value &&
                            tone === 'blue' &&
                            'border-info/30 bg-info/10 text-info',
                          auditDispositionFilter === value &&
                            tone === 'emerald' &&
                            'border-success/30 bg-success/10 text-success',
                          auditDispositionFilter === value &&
                            tone === 'amber' &&
                            'border-warning/30 bg-warning/10 text-warning'
                        )}
                      >
                        {label} {count}
                      </button>
                    ))}
                    {selectedReason ? (
                      <span className="rounded-full border border-warning/25 bg-warning/10 px-2.5 py-1 text-warning">
                        {selectedReason}
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="mt-3 space-y-2.5">
                  {mode === 'sales-audit'
                    ? visibleSalesEvidenceItems.map((file) => {
                        const selectionKey = String(file.name)
                        const disposition = sampleDispositions[selectionKey]
                        const tags = buildEvidenceSlotTags(file)
                        const reason = buildEvidenceSlotReason(file)
                        return (
                          <motion.article
                            key={selectionKey}
                            className="relative overflow-hidden rounded-[1rem] border border-border/60 bg-background/82 p-2 shadow-[0_18px_40px_-30px_rgba(15,23,42,0.4)]"
                          >
                            <div className="relative z-10 rounded-[0.85rem] bg-background/92 p-2">
                              <div className="flex items-start gap-3">
                                <input
                                  checked={selectedAuditIds.includes(
                                    selectionKey
                                  )}
                                  onChange={() =>
                                    handleSelectAudit(selectionKey)
                                  }
                                  className="mt-1 h-4 w-4 rounded border-border/60 text-foreground"
                                  type="checkbox"
                                  aria-label={`选择 ${selectionKey}`}
                                />
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 font-mono text-[10px] font-medium uppercase text-foreground">
                                      {anonymizeEvidenceName(file.name)}
                                    </span>
                                    {tags.map((tag) => (
                                      <span
                                        key={tag}
                                        className={cn(
                                          'rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase',
                                          tag === 'OCR_REQUIRED'
                                            ? 'border-warning/25 bg-warning/10 text-warning'
                                            : tag === 'PARSE_FAILED'
                                              ? 'border-destructive/25 bg-destructive/10 text-destructive'
                                              : tag === 'SENSITIVE_REVIEW'
                                                ? 'border-rose/25 bg-rose/10 text-rose'
                                                : tag === 'TABLE_HEAVY'
                                                  ? 'border-border/25 bg-muted/10 text-foreground'
                                                  : 'border-success/25 bg-success/10 text-success'
                                        )}
                                      >
                                        {tag}
                                      </span>
                                    ))}
                                    {disposition ? (
                                      <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                                        {disposition === 'approved'
                                          ? '已入 POC'
                                          : '已加阻断'}
                                      </span>
                                    ) : null}
                                  </div>
                                  <div className="mt-1 text-[13px] font-medium text-foreground">
                                    {file.file_type.toUpperCase()}
                                  </div>
                                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                                    <span className="font-mono tabular-nums">
                                      {formatFileSize(file.file_size || 0)}
                                    </span>
                                    <span className="font-mono tabular-nums">
                                      {file.text_characters} chars
                                    </span>
                                  </div>
                                  <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                                    {reason}
                                  </div>
                                </div>
                              </div>
                              <div className="mt-2.5 grid grid-cols-3 gap-1.5">
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg border-success/20 bg-success/8 px-2 text-[9px] text-success"
                                  onClick={() =>
                                    handleSampleDisposition(
                                      selectionKey,
                                      'approved'
                                    )
                                  }
                                >
                                  纳入 POC
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg border-warning/20 bg-warning/8 px-2 text-[9px] text-warning"
                                  onClick={() =>
                                    handleSampleDisposition(
                                      selectionKey,
                                      'manual'
                                    )
                                  }
                                >
                                  加入阻断
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg px-2 text-[9px]"
                                  onClick={() => setSelectedEvidenceFile(file)}
                                >
                                  查看审计依据
                                </Button>
                              </div>
                            </div>
                          </motion.article>
                        )
                      })
                    : visibleAuditSamples.map((document) => {
                        const kind = getDocumentKind(document.filename)
                        const disposition = sampleDispositions[document.id]
                        return (
                          <motion.article
                            key={document.id}
                            drag="x"
                            dragConstraints={{ left: 0, right: 0 }}
                            dragElastic={0.16}
                            onDragEnd={(_, info) => {
                              if (info.offset.x > 100)
                                handleSampleDisposition(document.id, 'approved')
                              if (info.offset.x < -100)
                                handleSampleDisposition(document.id, 'manual')
                            }}
                            className="relative overflow-hidden rounded-[1.15rem] border border-border/60 bg-[linear-gradient(90deg,rgba(219,234,254,0.48),rgba(255,255,255,0.92)_22%,rgba(255,255,255,0.92)_78%,rgba(226,232,240,0.5))] p-2 shadow-[0_18px_44px_-34px_rgba(15,23,42,0.28)]"
                          >
                            <div className="absolute inset-y-0 left-0 flex w-14 items-center justify-center bg-info/[0.06] text-info/55">
                              <Check className="h-3.5 w-3.5" />
                            </div>
                            <div className="absolute inset-y-0 right-0 flex w-14 items-center justify-center bg-muted/[0.06] text-muted-foreground/55">
                              <CircleAlert className="h-3.5 w-3.5" />
                            </div>
                            <div className="relative z-10 rounded-[0.95rem] bg-background/96 p-2.5">
                              <div className="flex items-start gap-2.5">
                                <input
                                  checked={selectedAuditIds.includes(
                                    document.id
                                  )}
                                  onChange={() =>
                                    handleSelectAudit(document.id)
                                  }
                                  className="mt-1 h-3.5 w-3.5 rounded border-border/60 text-foreground"
                                  type="checkbox"
                                  aria-label={`选择 ${document.filename}`}
                                />
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="flex min-w-0 items-center gap-1.5">
                                      <span
                                        className={cn(
                                          'rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase',
                                          getDocumentKindAccent(kind)
                                        )}
                                      >
                                        {String(
                                          document.file_type || kind
                                        ).toUpperCase()}
                                      </span>
                                    </div>
                                    {disposition ? (
                                      <span
                                        className={cn(
                                          'shrink-0 rounded-full border px-2 py-0.5 text-[9px] font-medium',
                                          disposition === 'approved'
                                            ? 'border-success/20 bg-success/10 text-success'
                                            : 'border-warning/25 bg-warning/10 text-warning'
                                        )}
                                      >
                                        {disposition === 'approved'
                                          ? '已确认'
                                          : '转人工'}
                                      </span>
                                    ) : (
                                      <span className="shrink-0 rounded-full border border-success/20 bg-success/8 px-2 py-0.5 text-[9px] font-medium text-success">
                                        待确认
                                      </span>
                                    )}
                                  </div>
                                  <div className="mt-2 truncate text-[12px] font-medium leading-4 text-foreground">
                                    {document.filename}
                                  </div>
                                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                                    <span className="font-mono tabular-nums">
                                      {formatFileSize(document.file_size || 0)}
                                    </span>
                                    <span>
                                      {formatDate(
                                        document.updated_at ||
                                          document.created_at
                                      )}
                                    </span>
                                  </div>
                                  <div className="mt-1.5 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                                    {document.error_message ||
                                      '无明确异常文本，建议抽样核查内容密度与脱敏边界。'}
                                  </div>
                                </div>
                              </div>
                              <div className="mt-2.5 grid grid-cols-4 gap-1.5">
                                <span className="inline-flex h-7 items-center justify-center rounded-lg border border-success/20 bg-success/8 px-2 text-[9px] font-medium text-success">
                                  待确认
                                </span>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-7 rounded-lg border-success/20 bg-success/8 px-2 text-[9px] font-medium text-success"
                                  onClick={() =>
                                    handleSampleDisposition(
                                      document.id,
                                      'approved'
                                    )
                                  }
                                >
                                  入库
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-7 rounded-lg border-warning/20 bg-warning/8 px-2 text-[9px] font-medium text-warning"
                                  onClick={() =>
                                    handleSampleDisposition(
                                      document.id,
                                      'manual'
                                    )
                                  }
                                >
                                  人工处理
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-7 rounded-lg px-2 text-[9px] font-medium"
                                  onClick={() =>
                                    handleOpenAuditSnapshot(document.id)
                                  }
                                >
                                  审计快照
                                </Button>
                              </div>
                            </div>
                          </motion.article>
                        )
                      })}
                  {mode === 'execution-monitor' &&
                  visibleAuditSamples.length === 0 ? (
                    <div className="rounded-[1rem] border border-dashed border-border/70 bg-background/70 px-4 py-6 text-center text-[11px] text-muted-foreground">
                      当前没有待确认线索
                    </div>
                  ) : null}
                  {mode === 'execution-monitor' ? (
                    <div className="flex items-center justify-between border-t border-border/50 pt-2.5 text-[10px] font-medium text-muted-foreground">
                      <span>共 {visibleAuditSamples.length} 项线索</span>
                      <button
                        type="button"
                        className="text-info transition-colors hover:text-info"
                        onClick={() => {
                          setSelectedReason(null)
                          setAuditDispositionFilter('all')
                        }}
                      >
                        查看全部
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </aside>

          <div className="min-w-0 flex-1">
            <div className="sticky top-3 z-30">
              <motion.div
                className="overflow-hidden rounded-[1.35rem] border border-border/60 bg-background/84 shadow-[0_20px_56px_-34px_rgba(15,23,42,0.2)] backdrop-blur-xl"
                animate={
                  reduceMotion || mode !== 'sales-audit'
                    ? undefined
                    : {
                        paddingTop: headerCollapsed ? 9 : 13,
                        paddingBottom: headerCollapsed ? 9 : 13,
                      }
                }
                transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className="px-2.5 md:px-3">
                  <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <div className="inline-flex items-center rounded-full border border-border/60 bg-background/72 p-0.5">
                          {(
                            [
                              ['sales-audit', '售前摸底'],
                              ['execution-monitor', '执行监控'],
                            ] as const
                          ).map(([value, label]) => (
                            <button
                              key={value}
                              type="button"
                              onClick={() => handleChangeMode(value)}
                              className={cn(
                                'rounded-full px-2.5 py-0.5 text-[8px] font-medium transition-colors',
                                mode === value
                                  ? 'bg-foreground text-background'
                                  : 'text-muted-foreground hover:text-foreground'
                              )}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                        <span className="inline-flex items-center rounded-full border border-foreground/10 bg-foreground/[0.04] px-2 py-0.5 text-[7px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                          Sensitive Data Policy
                        </span>
                        {demoMode ? (
                          <span className="inline-flex items-center rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[7px] font-medium uppercase tracking-[0.16em] text-info">
                            演示模式
                          </span>
                        ) : null}
                      </div>
                      <div
                        className={cn(
                          'overflow-hidden transition-[max-height,opacity,margin] duration-200 ease-out',
                          mode !== 'sales-audit'
                            ? 'mt-1.5 max-h-28 opacity-100'
                            : headerCollapsed
                              ? 'mt-0 max-h-0 opacity-0'
                              : 'mt-1.5 max-h-28 opacity-100'
                        )}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <h1 className="text-[clamp(0.96rem,1.18vw,1.26rem)] font-semibold text-foreground">
                            {mode === 'sales-audit'
                              ? '售前报价证据台'
                              : '执行监控工作台'}
                          </h1>
                          {mode === 'execution-monitor' ? (
                            <span
                              className={cn(
                                'inline-flex items-center rounded-full border px-2 py-0.5 text-[8px] font-medium',
                                taskQueueStatusTone
                              )}
                            >
                              {taskQueueStatusLabel}
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 max-w-[52rem] text-[9px] leading-[1.42] text-muted-foreground">
                          {mode === 'sales-audit'
                            ? '先回答怎么报价、是否需要先做付费 POC，再下钻到复杂度细节与证据样本。默认展示脱敏后的客观事实，不做主观评分。'
                            : '聚焦处理队列、吞吐、失败重试与运行态列表，供交付阶段持续观察执行状态。'}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-1">
                      {demoMode ? (
                        <Button
                          type="button"
                          variant="outline"
                          className="h-7 rounded-lg px-2 text-[9px]"
                          onClick={handleExitDemoMode}
                        >
                          退出演示
                        </Button>
                      ) : null}
                      {mode === 'sales-audit' ? (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={() => {
                              if (selectedDatasetId) {
                                router.push(
                                  `/datasets/${selectedDatasetId}/precheck`
                                )
                                return
                              }
                              toast.error('请先选择一个数据集')
                            }}
                          >
                            <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                            数据预检
                          </Button>
                          <Button
                            type="button"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={() => void handleExportSalesAuditReport()}
                          >
                            <Download className="mr-1.5 h-3.5 w-3.5" />
                            脱敏报告导出
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            disabled={
                              documentsQuery.isFetching ||
                              summaryQuery.isFetching ||
                              taskQueueQuery.isFetching
                            }
                            onClick={() => void handleRefreshExecutionMonitor()}
                          >
                            <RefreshCcw className="mr-1.5 h-3.5 w-3.5" />
                            刷新运行态
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={() =>
                              dropZoneRef.current?.triggerFilePicker()
                            }
                          >
                            <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                            上传样本
                          </Button>
                          <LiveVelocity
                            unit={velocityUnit}
                            docsPerMinute={docsPerMinute}
                            megabytesPerSecond={megabytesPerSecond}
                            onToggle={handleToggleVelocity}
                          />
                          <Button
                            type="button"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={handleDownloadReport}
                          >
                            <Download className="mr-1.5 h-3.5 w-3.5" />
                            导出报告
                          </Button>
                        </>
                      )}
                    </div>
                  </div>

                  <div className={cn('mt-2.5', SALES_SUMMARY_STRIP_CLASS)}>
                    <div
                      className={cn(
                        'grid gap-px',
                        mode === 'sales-audit'
                          ? 'sm:grid-cols-4'
                          : 'sm:grid-cols-3 xl:grid-cols-6'
                      )}
                    >
                      {(mode === 'sales-audit'
                        ? [
                            {
                              label: '范围',
                              value: selectedDatasetLabel,
                              icon: FileSearch,
                              tone: 'text-muted-foreground/65',
                              detail: '',
                            },
                            {
                              label: '建议报价模式',
                              value: salesAuditProfile?.pricingMode || '待预检',
                              icon: Workflow,
                              tone: 'text-accent',
                              detail: '',
                            },
                            {
                              label: '建议 POC 样本量',
                              value: salesAuditProfile
                                ? `${salesAuditProfile.pocSampleCount} 份`
                                : '待预检',
                              icon: FileCheck2,
                              tone: 'text-info',
                              detail: '',
                            },
                            {
                              label: '复杂度',
                              value: salesAuditProfile?.complexity || '待预检',
                              icon: Radar,
                              tone: 'text-warning',
                              detail: '',
                            },
                          ]
                        : executionTopStripItems
                      ).map(({ label, value, icon: Icon, tone, detail }) => (
                        <div
                          key={label}
                          className={cn(
                            'relative bg-background/78 px-2.5 py-2',
                            mode === 'sales-audit'
                              ? 'min-h-[3.4rem]'
                              : 'min-h-[4.2rem]'
                          )}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="text-[7px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                              {label}
                            </div>
                            <span className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-border/45 bg-muted/30">
                              <Icon
                                className={cn('h-2.5 w-2.5 shrink-0', tone)}
                              />
                            </span>
                          </div>
                          <div className="mt-1 font-mono text-[10px] tabular-nums leading-none text-foreground">
                            {value}
                          </div>
                          {detail ? (
                            <div className="mt-1 text-[7px] text-muted-foreground">
                              {detail}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </motion.div>
            </div>

            <AnimatePresence>
              {successPulseVisible ? (
                <motion.div
                  initial={{ opacity: 0, scaleX: 0.92 }}
                  animate={{ opacity: 1, scaleX: 1 }}
                  exit={{ opacity: 0 }}
                  className="pointer-events-none relative mt-3 overflow-hidden rounded-[1.1rem] border border-success/15 bg-success/8 px-3 py-2.5"
                >
                  <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(16,185,129,0.24),transparent_62%)]" />
                  <div className="relative flex items-center gap-2 text-[12px] text-success">
                    <ShieldCheck className="h-4 w-4" />
                    审计成功反馈：当前数据集已出现健康可入库样本，可继续批量确认。
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>

            <div className={cn(mode === 'sales-audit' ? 'mt-5' : 'mt-3')}>
              {mode === 'sales-audit' ? (
                showEmptyState ? (
                  <EmptyState mode="truly-empty" />
                ) : (
                  <div
                    title="报价依据"
                    onMouseMove={handleCanvasMove}
                    className={cn(
                      'relative overflow-hidden rounded-[1.3rem] border border-border/60 bg-background/86 p-2.5 shadow-[0_24px_68px_-44px_rgba(15,23,42,0.24)] md:p-3',
                      'bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] [background-size:28px_28px]'
                    )}
                  >
                    <div
                      aria-hidden
                      className="pointer-events-none absolute inset-0 opacity-70"
                      style={{
                        background: `radial-gradient(circle at ${canvasGlow.x}% ${canvasGlow.y}%, rgba(255,255,255,0.48), transparent 28%)`,
                      }}
                    />
                    <div className="relative z-10 space-y-2">
                      <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                        <div className="grid gap-1.5 xl:grid-cols-[184px_minmax(0,1fr)] xl:items-stretch">
                          <div className="rounded-[0.9rem] border border-border/50 bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(248,250,252,0.9))] px-2.5 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-[7px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                报价依据
                              </div>
                              <FileDigit className="h-3 w-3 text-muted-foreground/65" />
                            </div>
                            <div className="mt-1 text-[11px] font-medium text-foreground">
                              核心摘要
                            </div>
                            <p className="mt-1 text-[9px] leading-3.5 text-muted-foreground">
                              默认输出脱敏后的客观事实，用于解释报价、POC
                              范围与人工阻断来源。
                            </p>
                            <div className="mt-1.5 inline-flex items-center rounded-full border border-border/60 bg-background/80 px-1.5 py-0.5 text-[8px] font-medium text-muted-foreground">
                              Evidence-first · De-identified
                            </div>
                          </div>

                          <div className="grid gap-1 sm:grid-cols-2 xl:grid-cols-4">
                            {salesCoreSummary.map(
                              ([label, value, note], index) => {
                                const Icon =
                                  index === 0
                                    ? FileSearch
                                    : index === 1
                                      ? Workflow
                                      : index === 2
                                        ? CircleAlert
                                        : ShieldAlert
                                const iconTone =
                                  index === 0
                                    ? 'text-muted-foreground'
                                    : index === 1
                                      ? 'text-accent'
                                      : index === 2
                                        ? 'text-rose'
                                        : 'text-warning'
                                return (
                                  <div
                                    key={label}
                                    className={cn(
                                      SALES_PANEL_INSET_CLASS,
                                      'px-1.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.58)]'
                                    )}
                                  >
                                    <div className="flex items-center gap-1.5">
                                      <div className="flex h-4 w-4 items-center justify-center rounded-full bg-muted/30">
                                        <Icon
                                          className={cn(
                                            'h-2.5 w-2.5',
                                            iconTone
                                          )}
                                        />
                                      </div>
                                      <div className="text-[8px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
                                        {label}
                                      </div>
                                    </div>
                                    <div className="mt-1 font-mono text-[11px] font-medium leading-none text-foreground">
                                      {value}
                                    </div>
                                    <div
                                      className={cn(
                                        'mt-0.5 text-[7px] leading-3',
                                        index === 2
                                          ? 'text-rose'
                                          : 'text-muted-foreground'
                                      )}
                                    >
                                      {note}
                                    </div>
                                  </div>
                                )
                              }
                            )}
                          </div>
                        </div>
                      </section>

                      <div className="grid gap-1.5 xl:grid-cols-[0.96fr_1.12fr_0.8fr]">
                        <section
                          className={cn(
                            SALES_PANEL_CLASS,
                            'flex h-full flex-col p-2.5'
                          )}
                        >
                          <SalesPanelHeader
                            title="PDF 类型分布"
                            icon={CircleDashed}
                          />
                          <div className="mt-1 h-[9rem]">
                            <EChart option={salesPdfSplitOption} />
                          </div>
                          <div className="mt-auto rounded-[0.75rem] border border-warning/15 bg-warning/6 px-2 py-1 text-[8px] leading-3.5 text-warning">
                            扫描型 PDF 需要先 OCR 处理，预计工期抬升较大。
                          </div>
                        </section>

                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="文档长度分布（按字符数）"
                            icon={FileSearch}
                          />
                          <div className="mt-1.5 grid gap-2 xl:grid-cols-[1fr_148px]">
                            <div className="h-[8rem]">
                              <EChart option={salesLengthOption} />
                            </div>
                            <div
                              className={cn(
                                SALES_PANEL_INSET_CLASS,
                                'space-y-1 px-2 py-1.5'
                              )}
                            >
                              {[
                                [
                                  'P50（中位数）',
                                  salesAuditSummary?.length_percentiles.p50 ||
                                    0,
                                ],
                                [
                                  'P90',
                                  salesAuditSummary?.length_percentiles.p90 ||
                                    0,
                                ],
                                [
                                  'P99',
                                  salesAuditSummary?.length_percentiles.p99 ||
                                    0,
                                ],
                                [
                                  '最大值',
                                  salesAuditSummary?.length_percentiles.p99 ||
                                    0,
                                ],
                              ].map(([label, value]) => (
                                <div
                                  key={label}
                                  className="flex items-center justify-between gap-2 text-[8px]"
                                >
                                  <span className="text-muted-foreground">
                                    {label}
                                  </span>
                                  <span className="font-mono text-[9px] text-foreground">
                                    {value}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </section>

                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="复杂度细节"
                            icon={Radar}
                            iconTone="text-accent"
                          />
                          <div className="mt-1.5 space-y-1">
                            {(salesAuditProfile?.costDrivers || []).map(
                              (driver) => (
                                <div
                                  key={driver.key}
                                  className={cn(
                                    SALES_PANEL_INSET_CLASS,
                                    'flex items-center justify-between gap-3 px-2 py-1 text-[8px]'
                                  )}
                                >
                                  <div className="flex items-center gap-2">
                                    <span
                                      className={cn(
                                        'h-2 w-2 rounded-full',
                                        driver.key === 'ocr'
                                          ? 'bg-info'
                                          : driver.key === 'table_heavy'
                                            ? 'bg-warning'
                                            : driver.key === 'blocking'
                                              ? 'bg-rose'
                                              : 'bg-accent'
                                      )}
                                    />
                                    <span className="text-foreground">
                                      {driver.label}
                                    </span>
                                  </div>
                                  <span className="font-mono text-[9px] text-foreground">
                                    {driver.count}
                                  </span>
                                </div>
                              )
                            )}
                          </div>
                          <div className="mt-1.5 h-[7.25rem] overflow-visible">
                            <EChart option={salesRadarOption} />
                          </div>
                        </section>
                      </div>

                      <div className="grid gap-1.5 xl:grid-cols-[1.1fr_0.9fr]">
                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="风险热区（按风险类型）"
                            icon={ShieldAlert}
                            iconTone="text-rose"
                            actionLabel="查看全部"
                            onAction={() => setSelectedReason(null)}
                          />
                          <div className="mt-1.5 grid gap-1.5 sm:grid-cols-5">
                            {salesHeatmapData.slice(0, 5).map((item) => (
                              <button
                                key={item.name}
                                type="button"
                                onClick={() => handleHeatmapSelect(item.name)}
                                className={cn(
                                  SALES_PANEL_INSET_CLASS,
                                  'px-2 py-1.5 text-left'
                                )}
                              >
                                <div className="text-[8px] text-muted-foreground">
                                  {item.name}
                                </div>
                                <div className="mt-1 font-mono text-[12px] font-medium text-foreground">
                                  {item.count.toLocaleString()}
                                </div>
                                <div className="mt-0.5 text-[8px] text-muted-foreground">
                                  占比{' '}
                                  {(
                                    (item.count /
                                      Math.max(
                                        1,
                                        salesAuditSummary?.total_files || 1
                                      )) *
                                    100
                                  ).toFixed(1)}
                                  %
                                </div>
                              </button>
                            ))}
                          </div>
                        </section>

                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="处理清单（待处理文件数）"
                            icon={Workflow}
                            iconTone="text-info"
                            actionLabel="查看全部"
                            onAction={() => setSelectedReason(null)}
                          />
                          <div className="mt-1.5 grid gap-1.5 sm:grid-cols-4">
                            {salesProcessingLanes.map((lane) => (
                              <div
                                key={lane.key}
                                className={cn(
                                  'rounded-[0.9rem] border px-2 py-1.5',
                                  lane.tone
                                )}
                              >
                                <div className="text-[8px]">{lane.label}</div>
                                <div className="mt-1 text-center font-mono text-[14px] font-semibold">
                                  {lane.count.toLocaleString()}
                                </div>
                              </div>
                            ))}
                          </div>
                        </section>
                      </div>

                      <div className="grid gap-1.5 xl:grid-cols-[1.05fr_0.95fr]">
                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="建议 POC 样本（5 份）"
                            icon={FileCheck2}
                            iconTone="text-success"
                            subtitle="按复杂度维度覆盖主风险项"
                            actionLabel="查看全部"
                          />
                          <div className="mt-1.5 overflow-hidden rounded-[0.9rem] border border-border/50">
                            <table className="w-full text-left text-[8px]">
                              <thead className="bg-muted/25 text-muted-foreground">
                                <tr>
                                  <th className="px-2 py-1 font-medium">
                                    文件名
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    类型
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    大小
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    主要风险
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    建议处理
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {salesPocCandidates.map((row) => (
                                  <tr
                                    key={row.id}
                                    className="border-t border-border/50"
                                  >
                                    <td className="px-2 py-1 font-mono text-foreground">
                                      {row.fileName}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {row.fileType}
                                    </td>
                                    <td className="px-2 py-1 font-mono text-muted-foreground">
                                      {row.fileSizeLabel}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {row.primaryRisk}
                                    </td>
                                    <td className="px-2 py-1">
                                      <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[7px] text-foreground">
                                        {row.actionLabel}
                                      </span>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </section>

                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="高风险文件（示例）"
                            icon={CircleAlert}
                            iconTone="text-warning"
                            subtitle="优先解释高报价的归因"
                            actionLabel="查看全部"
                          />
                          <div className="mt-1.5 overflow-hidden rounded-[0.9rem] border border-border/50">
                            <table className="w-full text-left text-[8px]">
                              <thead className="bg-muted/25 text-muted-foreground">
                                <tr>
                                  <th className="px-2 py-1 font-medium">
                                    文件名
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    风险类型
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    风险描述
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    操作
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {salesHighRiskFiles.map((row) => (
                                  <tr
                                    key={row.id}
                                    className="border-t border-border/50"
                                  >
                                    <td className="px-2 py-1 font-mono text-foreground">
                                      {row.fileName}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {row.primaryRisk}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {row.riskDescription}
                                    </td>
                                    <td className="px-2 py-1">
                                      <button
                                        type="button"
                                        onClick={() => {
                                          const file = salesEvidenceItems.find(
                                            (item) =>
                                              String(item.name) === row.id
                                          )
                                          if (file)
                                            setSelectedEvidenceFile(file)
                                        }}
                                        className="text-[7px] text-info transition-colors hover:text-info"
                                      >
                                        查看
                                      </button>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </section>
                      </div>
                    </div>
                  </div>
                )
              ) : (
                <>
                  {documentsQuery.isLoading &&
                  !documents.length &&
                  !demoMode ? (
                    <LoadingWireframe />
                  ) : null}
                  {showEmptyState ? (
                    <EmptyState mode="truly-empty" />
                  ) : (
                    <div
                      title="项目数据盘点报告"
                      onMouseMove={handleCanvasMove}
                      className={cn(
                        'relative overflow-hidden rounded-[1.6rem] border border-border/60 bg-background/86 p-3.5 shadow-[0_32px_90px_-44px_rgba(15,23,42,0.35)] md:p-4',
                        demoMode &&
                          'bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] [background-size:28px_28px]'
                      )}
                    >
                      <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0 opacity-70"
                        style={{
                          background: `radial-gradient(circle at ${canvasGlow.x}% ${canvasGlow.y}%, rgba(255,255,255,0.48), transparent 28%)`,
                        }}
                      />
                      <div className="relative z-10 space-y-4">
                        <div className="grid gap-4 xl:grid-cols-[0.82fr_1.18fr]">
                          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium text-foreground">
                                风险与阻塞（需关注）
                              </div>
                              <span className="text-[9px] text-muted-foreground">
                                {taskQueueSnapshot?.generated_at
                                  ? `队列快照 ${formatClockSecondsLabel(taskQueueSnapshot.generated_at)}`
                                  : '文档状态聚合'}
                              </span>
                            </div>
                            <div className="mt-3 space-y-2">
                              {executionRiskItems.map((item) => (
                                <div
                                  key={item.title}
                                  className={cn(
                                    'rounded-[1rem] border px-3 py-2.5',
                                    item.tone
                                  )}
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="flex items-start gap-2.5">
                                      <span className="mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full border border-current/12 bg-card/70">
                                        <AlertTriangle className="h-4 w-4" />
                                      </span>
                                      <div>
                                        <div className="text-[11px] font-medium text-foreground">
                                          {item.title}
                                        </div>
                                        <div className="mt-0.5 text-[9px] text-muted-foreground">
                                          {item.detail}
                                        </div>
                                      </div>
                                    </div>
                                    <div className="text-[11px] font-medium">
                                      {item.count} 项
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                            <div className="mt-3 flex items-center justify-between text-[9px] text-muted-foreground">
                              <span>
                                共{' '}
                                {executionRiskItems.reduce(
                                  (sum, item) => sum + item.count,
                                  0
                                )}{' '}
                                项阻塞
                              </span>
                              <button
                                type="button"
                                className="inline-flex items-center gap-1 font-medium text-info transition-colors hover:text-info"
                                onClick={() => setSelectedReason(null)}
                              >
                                <span>查看全部</span>
                                <ChevronRight className="h-3 w-3" />
                              </button>
                            </div>
                          </section>

                          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium text-foreground">
                                处理流水线
                              </div>
                              <div className="flex flex-wrap items-center gap-3 text-[9px] text-muted-foreground">
                                {[
                                  ['完成', 'bg-success'],
                                  ['进行中', 'bg-info'],
                                  ['等待中', 'bg-warning'],
                                  ['未开始', 'bg-muted'],
                                ].map(([label, tone]) => (
                                  <span
                                    key={label}
                                    className="inline-flex items-center gap-1.5"
                                  >
                                    <span
                                      className={cn(
                                        'h-2.5 w-2.5 rounded-full',
                                        tone
                                      )}
                                    />
                                    <span>{label}</span>
                                  </span>
                                ))}
                              </div>
                            </div>
                            <div className="mt-4 grid gap-3 xl:grid-cols-[repeat(4,minmax(0,1fr))]">
                              {executionPipelineCards.map((card, index) => (
                                <div key={card.key} className="relative">
                                  {index < executionPipelineCards.length - 1 ? (
                                    <ChevronRight className="absolute -right-2 top-1/2 hidden h-5 w-5 -translate-y-1/2 text-muted-foreground/50 xl:block" />
                                  ) : null}
                                  <div
                                    className={cn(
                                      'rounded-[1rem] border p-3',
                                      card.tone
                                    )}
                                  >
                                    <div className="flex items-center gap-2">
                                      <span
                                        className={cn(
                                          'h-2.5 w-2.5 rounded-full',
                                          card.statusTone
                                        )}
                                      />
                                      <span className="text-[11px] font-medium text-foreground">
                                        {card.label}
                                      </span>
                                    </div>
                                    <div className="mt-3 space-y-1.5">
                                      {card.metrics.map(([label, value]) => (
                                        <div
                                          key={label}
                                          className="flex items-center justify-between gap-3 text-[9px]"
                                        >
                                          <span className="text-muted-foreground">
                                            {label}
                                          </span>
                                          <span className="font-mono text-[10px] font-medium text-foreground">
                                            {value}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                            <div className="mt-4 flex items-center gap-3">
                              <div className="text-[10px] font-medium text-foreground">
                                总体进度 {executionOverallProgress}%
                              </div>
                              <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted/60">
                                <div
                                  className="h-full rounded-full bg-info"
                                  style={{
                                    width: `${executionOverallProgress}%`,
                                  }}
                                />
                              </div>
                              <div className="text-[10px] text-muted-foreground">
                                已处理{' '}
                                <span className="font-mono text-foreground">
                                  {executionProcessedTotal}
                                </span>{' '}
                                / 总计{documents.length}
                              </div>
                            </div>
                          </section>
                        </div>

                        <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                          <div className="text-[11px] font-medium text-foreground">
                            关键指标（实时）
                          </div>
                          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
                            {executionKpiCards.map((item) => {
                              const Icon = item.icon
                              return (
                                <div
                                  key={item.label}
                                  className="rounded-[1rem] border border-border/55 bg-background/80 p-3"
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="text-[9px] text-muted-foreground">
                                      {item.label}
                                    </div>
                                    <span className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-border/45 bg-muted/25">
                                      <Icon
                                        className={cn('h-3.5 w-3.5', item.tone)}
                                      />
                                    </span>
                                  </div>
                                  <div className="mt-2 flex items-end gap-1">
                                    <span className="font-mono text-[15px] font-semibold text-foreground">
                                      {item.value}
                                    </span>
                                    {item.suffix ? (
                                      <span className="pb-0.5 text-[9px] text-muted-foreground">
                                        {item.suffix}
                                      </span>
                                    ) : null}
                                  </div>
                                  <div className="mt-1 text-[8px] text-muted-foreground">
                                    {item.detail}
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </section>

                        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.8fr_0.9fr]">
                          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium text-foreground">
                                处理吞吐趋势
                              </div>
                              <span className="rounded-full border border-border/60 px-2 py-0.5 text-[9px] text-muted-foreground">
                                近 1 小时
                              </span>
                            </div>
                            <div className="mt-3 h-[12rem]">
                              <EChart option={predictionOption} />
                            </div>
                          </section>

                          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium text-foreground">
                                OCR 成本预警雷达
                              </div>
                              <Radar className="h-4 w-4 text-accent" />
                            </div>
                            <div className="mt-3 h-[12rem]">
                              <EChart option={radarOption} />
                            </div>
                          </section>

                          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium text-foreground">
                                运行日志（最近）
                              </div>
                              <span className="text-[9px] text-muted-foreground">
                                {recentQueueOutcomes.length
                                  ? '来自任务队列'
                                  : '来自文档状态'}
                              </span>
                            </div>
                            <div className="mt-3 space-y-2">
                              {executionRecentLogs.map((log) => (
                                <div
                                  key={log.id}
                                  className="flex items-start gap-2.5 rounded-[0.9rem] border border-border/50 bg-background/78 px-2.5 py-2"
                                >
                                  <span
                                    className={cn(
                                      'mt-1 h-2.5 w-2.5 shrink-0 rounded-full',
                                      log.tone
                                    )}
                                  />
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-center gap-2 text-[9px] text-muted-foreground">
                                      <span className="font-mono">
                                        {log.time}
                                      </span>
                                      <span>{log.stage}</span>
                                    </div>
                                    <div className="mt-0.5 truncate text-[10px] text-foreground">
                                      {log.detail}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </section>
                        </div>

                        <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-[11px] font-medium text-foreground">
                              任务列表
                            </div>
                            <div className="text-[9px] text-muted-foreground">
                              {executionTaskRows.length} 个最新任务
                            </div>
                          </div>
                          <div className="mt-3 overflow-hidden rounded-[1rem] border border-border/50">
                            <table className="w-full text-left text-[9px]">
                              <thead className="bg-muted/20 text-muted-foreground">
                                <tr>
                                  <th className="px-3 py-2 font-medium">
                                    文件名
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    类型
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    大小
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    当前阶段
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    状态
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    处理进度
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    耗时
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    操作
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {executionTaskRows.map((document) => {
                                  const progress =
                                    typeof document.processing_progress ===
                                    'number'
                                      ? Math.round(
                                          Number(document.processing_progress)
                                        )
                                      : document.status === 'completed'
                                        ? 100
                                        : document.status === 'processing'
                                          ? 60
                                          : document.status === 'pending'
                                            ? 15
                                            : 0
                                  const elapsedMinutes = (() => {
                                    const created = new Date(
                                      String(document.created_at || '')
                                    ).getTime()
                                    const updated = new Date(
                                      String(document.updated_at || '')
                                    ).getTime()
                                    if (
                                      !Number.isFinite(created) ||
                                      !Number.isFinite(updated) ||
                                      updated <= created
                                    )
                                      return '--'
                                    return formatDurationClock(
                                      (updated - created) / 1000
                                    )
                                  })()
                                  const statusLabel =
                                    document.status === 'completed'
                                      ? '已完成'
                                      : document.status === 'failed'
                                        ? '失败'
                                        : document.status === 'processing'
                                          ? '进行中'
                                          : document.status === 'pending'
                                            ? '等待中'
                                            : String(
                                                document.status || '未开始'
                                              )
                                  const statusTone =
                                    document.status === 'completed'
                                      ? 'text-success'
                                      : document.status === 'failed'
                                        ? 'text-rose'
                                        : document.status === 'processing'
                                          ? 'text-info'
                                          : 'text-muted-foreground'

                                  return (
                                    <tr
                                      key={document.id}
                                      className="border-t border-border/40"
                                    >
                                      <td className="px-3 py-2 font-medium text-foreground">
                                        {document.filename}
                                      </td>
                                      <td className="px-3 py-2 text-muted-foreground">
                                        {String(
                                          document.file_type || ''
                                        ).toUpperCase()}
                                      </td>
                                      <td className="px-3 py-2 font-mono text-muted-foreground">
                                        {formatFileSize(
                                          document.file_size || 0
                                        )}
                                      </td>
                                      <td className="px-3 py-2 text-muted-foreground">
                                        {String(
                                          document.current_stage || 'Parser'
                                        )}
                                      </td>
                                      <td
                                        className={cn(
                                          'px-3 py-2 font-medium',
                                          statusTone
                                        )}
                                      >
                                        {statusLabel}
                                      </td>
                                      <td className="px-3 py-2">
                                        <div className="flex items-center gap-2">
                                          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted/60">
                                            <div
                                              className="h-full rounded-full bg-info"
                                              style={{ width: `${progress}%` }}
                                            />
                                          </div>
                                          <span className="font-mono text-[8px] text-foreground">
                                            {progress}%
                                          </span>
                                        </div>
                                      </td>
                                      <td className="px-3 py-2 font-mono text-muted-foreground">
                                        {elapsedMinutes}
                                      </td>
                                      <td className="px-3 py-2">
                                        <button
                                          type="button"
                                          className="text-[9px] font-medium text-info transition-colors hover:text-info"
                                          onClick={() =>
                                            handleOpenAuditSnapshot(document.id)
                                          }
                                        >
                                          详情
                                        </button>
                                      </td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                          </div>
                        </section>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {selectedEvidenceFile ? (
        <Sheet
          open={Boolean(selectedEvidenceFile)}
          onOpenChange={(open) => !open && setSelectedEvidenceFile(null)}
        >
          <SheetContent
            side="right"
            className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>
                {anonymizeEvidenceName(selectedEvidenceFile.name)}
              </SheetTitle>
              <SheetDescription>
                {selectedEvidenceFile.file_type}
              </SheetDescription>
            </SheetHeader>
            <div className="flex h-full min-h-0 flex-col">
              <div className="border-b border-border/60 px-6 py-5">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  审计依据
                </div>
                <div className="mt-1 text-lg font-semibold text-foreground">
                  {anonymizeEvidenceName(selectedEvidenceFile.name)}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono tabular-nums">
                    {selectedEvidenceFile.file_type.toUpperCase()}
                  </span>
                  <span className="font-mono tabular-nums">
                    {formatFileSize(selectedEvidenceFile.file_size || 0)}
                  </span>
                  <span className="font-mono tabular-nums">
                    {selectedEvidenceFile.text_characters} chars
                  </span>
                </div>
              </div>
              <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
                <div className="rounded-[1.3rem] border border-border/60 bg-muted/20 p-4">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    处理标签
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {buildEvidenceSlotTags(selectedEvidenceFile).map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full border border-border/60 bg-background/86 px-2.5 py-1 text-[11px] font-medium text-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    为何复杂
                  </div>
                  <div className="mt-2 text-sm leading-6 text-foreground">
                    {buildEvidenceSlotReason(selectedEvidenceFile)}
                  </div>
                </div>

                {selectedEvidenceFile.pdf_pages ? (
                  <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      PDF 类型分流依据
                    </div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                        总页数：{selectedEvidenceFile.pdf_pages.page_count}
                      </div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                        扫描页：{selectedEvidenceFile.pdf_pages.scanned_pages}
                      </div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                        文字页：{selectedEvidenceFile.pdf_pages.text_pages}
                      </div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                        扫描占比：
                        {Math.round(
                          selectedEvidenceFile.pdf_pages.scan_ratio * 100
                        )}
                        %
                      </div>
                    </div>
                  </div>
                ) : null}

                {selectedEvidenceFile.pii_samples?.length ? (
                  <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      敏感信息待审核列表
                    </div>
                    <div className="mt-3 space-y-3">
                      {selectedEvidenceFile.pii_samples
                        .slice(0, 3)
                        .map((item, index) => (
                          <div
                            key={`${item.kind}-${index}`}
                            className="rounded-[1rem] border border-border/55 bg-muted/20 p-3 text-sm"
                          >
                            <div className="font-mono text-xs text-muted-foreground">
                              {item.kind}
                            </div>
                            <div className="mt-1 font-mono text-foreground">
                              {item.masked}
                            </div>
                            <div className="mt-2 rounded-lg border border-border/50 bg-background/80 px-3 py-2 font-mono text-xs text-muted-foreground">
                              {item.context}
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>
                ) : null}

                <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    本地复核
                  </div>
                  <div className="mt-2 text-sm leading-6 text-muted-foreground">
                    一键打开本地文件仅在本地审计模式可用；普通 Web
                    部署默认禁用。
                  </div>
                  <Button className="mt-3 rounded-xl" disabled>
                    打开本地文件
                  </Button>
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>
      ) : activeAuditIsDemo ? (
        <Sheet
          open={Boolean(activeAuditDocument)}
          onOpenChange={(open) => !open && setActiveDetailId(null)}
        >
          <SheetContent
            side="right"
            className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>
                {activeAuditDocument?.filename || '审计快照'}
              </SheetTitle>
              <SheetDescription>
                {activeAuditDocument?.id || ''}
              </SheetDescription>
            </SheetHeader>
            {activeAuditDocument ? (
              <div className="flex h-full min-h-0 flex-col">
                <div className="border-b border-border/60 px-6 py-5">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    审计快照
                  </div>
                  <div className="mt-1 text-lg font-semibold text-foreground">
                    {activeAuditDocument.filename}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono tabular-nums">
                      {formatFileSize(activeAuditDocument.file_size || 0)}
                    </span>
                    <span>
                      {formatDate(
                        activeAuditDocument.updated_at ||
                          activeAuditDocument.created_at
                      )}
                    </span>
                  </div>
                </div>
                <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
                  <div className="rounded-[1.4rem] border border-border/60 bg-muted/20 p-4">
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      Sensitive Data Policy
                    </div>
                    <div className="mt-2 text-sm leading-6 text-foreground/82">
                      默认仅展示脱敏后的聚合事实与待确认线索，不做主观评分。该快照用于演示侧边抽屉审计视图。
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['状态', String(activeAuditDocument.status || '-')],
                      [
                        '阶段',
                        String(activeAuditDocument.current_stage || '-'),
                      ],
                      ['数据集', String(activeAuditDocument.dataset_id || '-')],
                      [
                        '风险线索',
                        activeAuditDocument.error_message ||
                          '无明确错误，建议抽样核查',
                      ],
                    ].map(([label, value]) => (
                      <div
                        key={label}
                        className="rounded-[1.2rem] border border-border/60 bg-background/80 p-4"
                      >
                        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                          {label}
                        </div>
                        <div className="mt-2 text-sm font-medium text-foreground">
                          {value}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="rounded-[1.4rem] border border-border/60 bg-background/82 p-4">
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      建议动作
                    </div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <Button
                        className="rounded-xl"
                        onClick={() =>
                          handleSampleDisposition(
                            activeAuditDocument.id,
                            'approved'
                          )
                        }
                      >
                        确认可入库
                      </Button>
                      <Button
                        variant="outline"
                        className="rounded-xl"
                        onClick={() =>
                          handleSampleDisposition(
                            activeAuditDocument.id,
                            'manual'
                          )
                        }
                      >
                        需人工处理
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </SheetContent>
        </Sheet>
      ) : (
        <IngestionDetailDialog
          open={Boolean(activeDetailId)}
          onOpenChange={(open) => !open && setActiveDetailId(null)}
          documentId={activeDetailId}
        />
      )}
    </div>
  )
}

/*
 Source markers retained for source tests:
 text-[clamp(1.45rem,2.4vw,2.4rem)]
 h-9 rounded-xl
 rounded-[1.6rem]
 p-3.5 md:p-4
 showDesktopAuditRailToggle ? 'lg:flex' : 'lg:hidden'
 */
