import {
  CircleAlert,
  CircleDashed,
  FileDigit,
  FileSearch,
  LucideIcon,
  ShieldAlert,
  TableProperties,
  Workflow,
} from 'lucide-react'

import type { DatasetPrecheckFileOut, Document } from '@/types'

import {
  estimatePdfPageCountFromSignals,
  getDocumentRuntimeStats,
  stringifyForDisplay,
} from './document-signals'
import type { IngestionMode, SampleDisposition } from './types'

export type SalesProcessingLane = {
  key: string
  label: string
  count: number
  tone: string
}

export type SalesEvidenceTableRow = {
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

export type RiskTagPresentation = {
  actionLabel: string
  icon: LucideIcon
  iconTone: string
  primaryRisk: string
}

export type StatusToneResult = {
  label: string
  tone: string
}

export type BatchProfileFile = {
  blockCount: number
  chars: number
  fileSize: number
  fileType: string
  imageCount: number
  pageCountEstimated: boolean
  pdfPages: number
  tableCount: number
}

export const SALES_PANEL_CLASS =
  'rounded-[1rem] border border-border/55 bg-background/92 shadow-[0_14px_28px_-24px_rgba(15,23,42,0.12)]'
export const SALES_PANEL_INSET_CLASS =
  'rounded-[0.9rem] border border-border/50 bg-background/82'
export const SALES_SUMMARY_STRIP_CLASS =
  'overflow-hidden rounded-[1rem] border border-border/55 bg-background/72 shadow-[0_12px_28px_-24px_rgba(15,23,42,0.1)]'

export function resolveThroughputRowsSource(
  hasBackendRows: boolean,
  documentRowsLength: number
): 'backend' | 'documents' {
  if (hasBackendRows) return 'backend'
  if (documentRowsLength) return 'documents'
  return 'backend'
}

export function getQueueOutcomeReason(item: { reason?: unknown }, ok: boolean): string {
  const reason = stringifyForDisplay(item.reason)
  if (reason) return reason
  if (ok) return '任务完成'
  return '任务失败或被跳过'
}

export function getRecentLogDetail(status: string, filename: string): string {
  switch (status) {
    case 'failed':
      return `解析失败：${filename}`
    case 'completed':
      return `解析成功：${filename}`
    default:
      return `开始解析：${filename}`
  }
}

export function getRecentLogTone(status: string): string {
  switch (status) {
    case 'failed':
      return 'bg-rose'
    case 'completed':
      return 'bg-success'
    default:
      return 'bg-muted-foreground/40'
  }
}

export function resolveFallbackComplexity({
  durationP90,
  executionRetryRate,
  pdfRatio,
  totalCharacters,
  totalSizeBytes,
}: Readonly<{
  durationP90: number
  executionRetryRate: number
  pdfRatio: number
  totalCharacters: number
  totalSizeBytes: number
}>): '高' | '中' | '低' {
  if (pdfRatio >= 0.35 || executionRetryRate >= 8 || durationP90 >= 20) {
    return '高'
  }
  if (pdfRatio >= 0.12 || totalSizeBytes >= 500 * 1024 * 1024 || totalCharacters >= 500_000) {
    return '中'
  }
  return '低'
}

export function formatPdfPageAverageLabel({
  avgPdfPages,
  hasEstimatedPdfPages,
  hasPdfProfiles,
}: Readonly<{
  avgPdfPages: number
  hasEstimatedPdfPages: boolean
  hasPdfProfiles: boolean
}>): string {
  if (avgPdfPages) {
    const estimatedSuffix = hasEstimatedPdfPages ? '估算' : ''
    return `${Math.round(avgPdfPages)} 页${estimatedSuffix}`
  }
  if (hasPdfProfiles) return '后端未回传'
  return '无 PDF'
}

export function formatStructureAverageLabel({
  avgPdfBlocks,
  avgPdfTables,
  hasPdfProfiles,
}: Readonly<{
  avgPdfBlocks: number
  avgPdfTables: number
  hasPdfProfiles: boolean
}>): string {
  if (!hasPdfProfiles) return '无 PDF'
  if (avgPdfTables) return `${Math.round(avgPdfTables)} 表`
  return `${Math.round(avgPdfBlocks).toLocaleString()} 块`
}

export function getRiskTagPresentation(firstTag: string): RiskTagPresentation {
  switch (firstTag) {
    case 'OCR_REQUIRED':
      return {
        actionLabel: 'OCR 处理',
        icon: CircleDashed,
        iconTone: 'text-info',
        primaryRisk: '扫描件',
      }
    case 'PARSE_FAILED':
      return {
        actionLabel: '人工审核',
        icon: CircleAlert,
        iconTone: 'text-rose',
        primaryRisk: '解析失败',
      }
    case 'TABLE_HEAVY':
      return {
        actionLabel: '格式转换',
        icon: TableProperties,
        iconTone: 'text-orange',
        primaryRisk: '合并单元格',
      }
    case 'SENSITIVE_REVIEW':
      return {
        actionLabel: '确认入库',
        icon: ShieldAlert,
        iconTone: 'text-warning',
        primaryRisk: '敏感信息',
      }
    case 'VERSION_CONFLICT':
      return {
        actionLabel: '确认入库',
        icon: FileDigit,
        iconTone: 'text-success',
        primaryRisk: '版本冲突',
      }
    default:
      return {
        actionLabel: '确认入库',
        icon: FileDigit,
        iconTone: 'text-success',
        primaryRisk: '通用文档',
      }
  }
}

export function getSeverityFill(severity: string, intensity: number): string {
  if (severity === 'error') {
    return `linear-gradient(135deg, rgba(185,28,28,${0.16 + intensity * 0.32}), rgba(127,29,29,${0.24 + intensity * 0.28}))`
  }
  if (severity === 'warning') {
    return `linear-gradient(135deg, rgba(217,119,6,${0.16 + intensity * 0.32}), rgba(146,64,14,${0.24 + intensity * 0.28}))`
  }
  return `linear-gradient(135deg, rgba(71,85,105,${0.16 + intensity * 0.32}), rgba(51,65,85,${0.24 + intensity * 0.28}))`
}

export function getPdfSplitColor(name: string): string {
  switch (name) {
    case 'SCAN':
      return '#f59e0b'
    case 'MIXED':
      return '#94a3b8'
    default:
      return '#10b981'
  }
}

export function getSalesCoreIcon(index: number): LucideIcon {
  switch (index) {
    case 0:
      return FileSearch
    case 1:
      return Workflow
    case 2:
      return CircleAlert
    default:
      return ShieldAlert
  }
}

export function getSalesCoreIconTone(index: number): string {
  switch (index) {
    case 0:
      return 'text-muted-foreground'
    case 1:
      return 'text-accent'
    case 2:
      return 'text-rose'
    default:
      return 'text-warning'
  }
}

export function getDriverDotTone(key: string): string {
  switch (key) {
    case 'ocr':
      return 'bg-info'
    case 'table_heavy':
      return 'bg-warning'
    case 'blocking':
      return 'bg-rose'
    default:
      return 'bg-accent'
  }
}

export function getAuditRailStatusTone({
  disposition,
  status,
}: Readonly<{
  disposition?: SampleDisposition
  status: string
}>): StatusToneResult {
  if (disposition === 'approved') {
    return {
      label: '已确认',
      tone: 'border-success/20 bg-success/10 text-success',
    }
  }
  if (disposition === 'manual') {
    return {
      label: '转人工',
      tone: 'border-warning/25 bg-warning/10 text-warning',
    }
  }

  switch (status) {
    case 'completed':
      return {
        label: '已完成',
        tone: 'border-success/20 bg-success/10 text-success',
      }
    case 'failed':
      return {
        label: '失败',
        tone: 'border-destructive/20 bg-destructive/10 text-destructive',
      }
    case 'processing':
      return {
        label: '处理中',
        tone: 'border-info/25 bg-info/10 text-info',
      }
    case 'pending':
      return {
        label: '待处理',
        tone: 'border-border/55 bg-muted/20 text-muted-foreground',
      }
    default:
      return {
        label: '待确认',
        tone: 'border-border/55 bg-muted/20 text-muted-foreground',
      }
  }
}

export function getProgressTone(status: string): string {
  switch (status) {
    case 'completed':
      return 'bg-success'
    case 'failed':
      return 'bg-destructive'
    default:
      return 'bg-info'
  }
}

export function getTaskProgress(document: Document): number {
  if (typeof document.processing_progress === 'number') {
    return Math.round(Number(document.processing_progress))
  }
  switch (document.status) {
    case 'completed':
      return 100
    case 'processing':
      return 60
    case 'pending':
      return 15
    default:
      return 0
  }
}

export function getDocumentStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    case 'processing':
      return '进行中'
    case 'pending':
      return '等待中'
    default:
      return String(status || '未开始')
  }
}

export function getDocumentStatusTone(status: string | null | undefined): string {
  switch (status) {
    case 'completed':
      return 'text-success'
    case 'failed':
      return 'text-rose'
    case 'processing':
      return 'text-info'
    default:
      return 'text-muted-foreground'
  }
}

export function buildPrecheckProfileFile(file: DatasetPrecheckFileOut): BatchProfileFile {
  return {
    chars: Number(file.text_characters || 0),
    fileSize: Number(file.file_size || 0),
    fileType: String(file.file_type || ''),
    pdfPages:
      Number(file.pdf_pages?.page_count || 0) ||
      estimatePdfPageCountFromSignals({
        characters: Number(file.text_characters || 0),
        fileSize: Number(file.file_size || 0),
      }),
    pageCountEstimated: !file.pdf_pages?.page_count,
    imageCount: Number(file.pdf_pages?.scanned_pages || 0),
    tableCount: 0,
    blockCount: 0,
  }
}

export function buildDocumentProfileFile(document: Document): BatchProfileFile {
  const runtimeStats = getDocumentRuntimeStats(document)
  const isPdf = String(document.file_type || '').toLowerCase() === 'pdf'
  const estimatedPdfPages =
    isPdf && runtimeStats.pageCount <= 0
      ? estimatePdfPageCountFromSignals({
          characters: Number(document.total_characters || 0),
          fileSize: Number(document.file_size || 0),
        })
      : 0

  return {
    blockCount: runtimeStats.blockCount,
    chars: Number(document.total_characters || 0),
    fileSize: Number(document.file_size || 0),
    fileType: String(document.file_type || ''),
    imageCount: runtimeStats.imageCount,
    pageCountEstimated: Boolean(isPdf && estimatedPdfPages > 0),
    pdfPages: runtimeStats.pageCount || estimatedPdfPages,
    tableCount: runtimeStats.tableCount,
  }
}

export function getHeaderAnimation({
  headerCollapsed,
  mode,
  reduceMotion,
}: Readonly<{
  headerCollapsed: boolean
  mode: IngestionMode
  reduceMotion: boolean | null
}>): { paddingBottom: number; paddingTop: number } | undefined {
  if (reduceMotion || mode !== 'sales-audit') return undefined
  const padding = headerCollapsed ? 9 : 13
  return {
    paddingBottom: padding,
    paddingTop: padding,
  }
}

export function getHeaderBodyVisibilityClass(
  mode: IngestionMode,
  headerCollapsed: boolean
): string {
  if (mode !== 'sales-audit') return 'mt-1.5 max-h-28 opacity-100'
  if (headerCollapsed) return 'mt-0 max-h-0 opacity-0'
  return 'mt-1.5 max-h-28 opacity-100'
}
