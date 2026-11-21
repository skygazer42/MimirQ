import type { DatasetPrecheckNearDupResponse, DatasetPrecheckSummary, Document } from '@/types'
import type { IngestionDashboardSummaryResponse } from '@/types/observability'
import { recordSchema } from '@/lib/response-schema'

type DocumentKind = 'pdf' | 'markdown' | 'spreadsheet' | 'html' | 'text'

type ThroughputAreaRow = {
  ts: number
  completed: number
  failed: number
  quarantined: number
  cancelled: number
  total: number
}

type SalesAuditComplexity = '低' | '中' | '高' | '超高'
type SalesAuditPricingMode = '固定报价' | '阶梯报价' | 'POC优先'
type SalesAuditDriver = {
  key: 'ocr' | 'table_heavy' | 'blocking' | 'dedup'
  label: string
  count: number
  tone: 'neutral' | 'cost' | 'blocker' | 'ready'
}

type SalesAuditProfile = {
  complexity: SalesAuditComplexity
  pricingMode: SalesAuditPricingMode
  pocSampleCount: number
  costDrivers: SalesAuditDriver[]
}

function countFinding(summary: Pick<DatasetPrecheckSummary, 'findings'>, key: string): number {
  return summary.findings.find((item) => item.key === key)?.count ?? 0
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function toFiniteNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function roundTo(value: number, digits = 1): number {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

export function computeDocsPerMinute(rows: readonly ThroughputAreaRow[], bucketMinutes: number): number | null {
  const recent = rows.slice(-5)
  if (recent.length < 2) return null

  const elapsedMs = recent[recent.length - 1].ts - recent[0].ts + bucketMinutes * 60_000
  if (!Number.isFinite(elapsedMs) || elapsedMs <= 0) return null

  const total = recent.reduce((sum, row) => sum + row.total, 0)
  return (total * 60_000) / elapsedMs
}

export function getDocumentKind(filename: string): DocumentKind {
  const lower = filename.trim().toLowerCase()
  if (lower.endsWith('.pdf')) return 'pdf'
  if (lower.endsWith('.md') || lower.endsWith('.mdx')) return 'markdown'
  if (lower.endsWith('.csv') || lower.endsWith('.xls') || lower.endsWith('.xlsx')) return 'spreadsheet'
  if (lower.endsWith('.html') || lower.endsWith('.htm')) return 'html'
  return 'text'
}

function getDocumentMetadataNumber(document: Pick<Document, 'metadata'>, key: string): number {
  return toFiniteNumber(document.metadata?.[key])
}

function getDocumentStageDurationMs(document: Pick<Document, 'metadata'>, key: string): number {
  const stages = recordSchema.safeParse(document.metadata?.ingest_stage_durations_ms)
  return stages.success ? toFiniteNumber(stages.data[key]) : 0
}

function computeDocumentRuntimeDurationMinutes(document: Pick<Document, 'metadata'>): number | null {
  const parseDurationSec = getDocumentMetadataNumber(document, 'parse_duration_sec')
  if (parseDurationSec > 0) return roundTo(parseDurationSec / 60, 2)

  const parseDurationMs = getDocumentStageDurationMs(document, 'parse')
  if (parseDurationMs > 0) return roundTo(parseDurationMs / 60_000, 2)

  return null
}

function computeDocumentDurationMinutes(
  document: Pick<Document, 'status' | 'created_at' | 'updated_at' | 'metadata'>,
): number | null {
  if (document.status === 'pending' || document.status === 'processing') return null
  const runtimeDuration = computeDocumentRuntimeDurationMinutes(document)
  if (runtimeDuration != null) return runtimeDuration

  const createdAt = Date.parse(document.created_at)
  const updatedAt = Date.parse(document.updated_at)
  if (!Number.isFinite(createdAt) || !Number.isFinite(updatedAt) || updatedAt <= createdAt) return null
  return roundTo((updatedAt - createdAt) / 60_000, 2)
}

export function computeDocumentDurationP90(documents: Document[]): number | null {
  const durations = documents
    .map(computeDocumentDurationMinutes)
    .filter((duration) => duration !== null)
    .sort((left, right) => left - right)
  if (durations.length === 0) return null
  return durations[Math.ceil(0.9 * durations.length) - 1]
}

export function buildThroughputAreaRows(
  timeseries: IngestionDashboardSummaryResponse['timeseries'] | undefined,
): ThroughputAreaRow[] {
  if (timeseries === undefined) return []
  const { ts_ms, completed, failed, quarantined, cancelled } = timeseries
  return ts_ms.map((ts, index) => ({
    ts,
    completed: completed[index],
    failed: failed[index],
    quarantined: quarantined[index],
    cancelled: cancelled[index],
    total: completed[index] + failed[index] + quarantined[index] + cancelled[index],
  }))
}

export function buildDocumentThroughputAreaRows(
  documents: Document[],
  options: Readonly<{ bucketMinutes: number; maxRows: number }>,
): ThroughputAreaRow[] {
  const bucketMs = options.bucketMinutes * 60_000
  const buckets = new Map<number, ThroughputAreaRow>()

  documents.forEach((document) => {
    const status = document.status
    if (!['completed', 'failed', 'quarantined', 'cancelled'].includes(status)) return

    const processedAt = document.processed_at ?? document.updated_at
    const timestamp = Date.parse(processedAt)
    if (!Number.isFinite(timestamp)) return

    const bucketTs = Math.floor(timestamp / bucketMs) * bucketMs
    const bucket =
      buckets.get(bucketTs) ??
      ({
        ts: bucketTs,
        completed: 0,
        failed: 0,
        quarantined: 0,
        cancelled: 0,
        total: 0,
      } satisfies ThroughputAreaRow)

    if (status === 'completed') bucket.completed += 1
    if (status === 'failed') bucket.failed += 1
    if (status === 'quarantined') bucket.quarantined += 1
    if (status === 'cancelled') bucket.cancelled += 1
    bucket.total = bucket.completed + bucket.failed + bucket.quarantined + bucket.cancelled
    buckets.set(bucketTs, bucket)
  })

  return Array.from(buckets.values())
    .sort((left, right) => left.ts - right.ts)
    .slice(-options.maxRows)
}

export function buildSalesAuditProfile(
  summary: DatasetPrecheckSummary,
  nearDup?: DatasetPrecheckNearDupResponse | null,
): SalesAuditProfile {
  const totalFiles = summary.total_files
  const fileCountForRatios = Math.max(1, totalFiles)
  const { scanned, not_scanned, unknown } = summary.pdf_scan
  const pdfTotal = scanned + not_scanned + unknown
  const ocrCount = scanned + unknown
  const ocrRatio = pdfTotal > 0 ? ocrCount / pdfTotal : 0

  const tableHeavy =
    countFinding(summary, 'large_spreadsheet') +
    countFinding(summary, 'wide_spreadsheet') +
    countFinding(summary, 'many_sheets_spreadsheet') +
    countFinding(summary, 'merged_heavy_spreadsheet')
  const blocking =
    countFinding(summary, 'parse_failed') +
    countFinding(summary, 'pdf_unknown') +
    countFinding(summary, 'pii') +
    countFinding(summary, 'secrets')
  const dedup = countFinding(summary, 'near_dup') + countFinding(summary, 'exact_dup') + (nearDup?.pairs_returned ?? 0)

  const score =
    ocrRatio * 42 +
    Math.min(20, (tableHeavy / fileCountForRatios) * 80 + tableHeavy * 0.4) +
    Math.min(28, (blocking / fileCountForRatios) * 130 + blocking * 0.35) +
    Math.min(14, (dedup / fileCountForRatios) * 55 + (nearDup?.clusters_returned ?? 0) * 0.6)

  let complexity: SalesAuditComplexity = '低'
  if (score >= 82) complexity = '超高'
  else if (score >= 42) complexity = '高'
  else if (score >= 18) complexity = '中'

  let pricingMode: SalesAuditPricingMode = '固定报价'
  if (complexity === '超高' || complexity === '高' || blocking >= 10 || ocrRatio >= 0.28) {
    pricingMode = 'POC优先'
  } else if (complexity === '中' || tableHeavy > 0 || dedup > 0) {
    pricingMode = '阶梯报价'
  }

  const pocRatio = complexity === '超高' ? 0.1 : complexity === '高' ? 0.08 : complexity === '中' ? 0.05 : 0.03
  const pocSampleCount = Math.min(totalFiles, clamp(Math.ceil(totalFiles * pocRatio), 5, 40))

  return {
    complexity,
    pricingMode,
    pocSampleCount,
    costDrivers: [
      { key: 'ocr', label: '扫描件 / 待识别 PDF', count: ocrCount, tone: ocrCount > 0 ? 'cost' : 'ready' },
      { key: 'table_heavy', label: '表格重文档', count: tableHeavy, tone: tableHeavy > 0 ? 'cost' : 'neutral' },
      { key: 'blocking', label: '阻断 / 待复核', count: blocking, tone: blocking > 0 ? 'blocker' : 'ready' },
      { key: 'dedup', label: '版本冲突', count: dedup, tone: dedup > 0 ? 'neutral' : 'ready' },
    ],
  }
}
