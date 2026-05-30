import type {
  DatasetPrecheckFileOut,
  DatasetPrecheckNearDupResponse,
  DatasetPrecheckSummary,
  Document,
} from '@/types'

export type VelocityUnit = 'docs' | 'bytes'

export type RealChartRow = {
  t?: number | null
  ts?: number | null
  completed?: number | null
  failed?: number | null
  quarantined?: number | null
}

export type BulkActionAvailability = {
  canRetry: boolean
  canCancel: boolean
  canDelete: boolean
  canExport: boolean
}

export type DocumentKind = 'pdf' | 'markdown' | 'spreadsheet' | 'html' | 'text'

export type PercentileSummary = {
  p25: number
  p50: number
  p75: number
  p90: number
  p99: number
  max: number
}

export type ExecutionStatusRow = {
  key: string
  name: string
  value: number
  fill: string
}

export type StageTreemapRow = {
  name: string
  value: number
  fill: string
}

export type ThroughputAreaRow = {
  ts: number
  completed: number
  failed: number
  quarantined: number
  cancelled: number
  total: number
}

export type LatencyBoxplotRows = {
  categories: string[]
  values: Array<[number, number, number, number, number]>
}

export type ExecutionScatterRow = {
  documentId: string
  filename: string
  status: string
  fileSizeMB: number
  durationMinutes: number
}

export type SalesAuditComplexity = '低' | '中' | '高' | '超高'
export type SalesAuditPricingMode = '固定报价' | '阶梯报价' | 'POC优先'
export type EvidenceSlotTag =
  | 'OCR_REQUIRED'
  | 'TABLE_HEAVY'
  | 'PARSE_FAILED'
  | 'SENSITIVE_REVIEW'
  | 'VERSION_CONFLICT'
  | 'LOW_SIGNAL'
  | 'STRAIGHT_THROUGH'

export type SalesAuditDriver = {
  key: 'ocr' | 'table_heavy' | 'blocking' | 'dedup'
  label: string
  count: number
  tone: 'neutral' | 'cost' | 'blocker' | 'ready'
}

export type SalesAuditProfile = {
  complexity: SalesAuditComplexity
  pricingMode: SalesAuditPricingMode
  pocSampleCount: number
  costDrivers: SalesAuditDriver[]
}

export const STAGE_TOOLTIPS: Record<string, string> = {
  queued: '等待调度,即将开始处理',
  parsing: '通过 OCR / 解析器提取文本',
  chunking: '按语义切分文档为可检索片段',
  embedding: '向量化与索引构建中',
  completed: '已可被检索',
}

function countFinding(summary: Pick<DatasetPrecheckSummary, 'findings'>, key: string): number {
  return Number(summary.findings.find((item) => item.key === key)?.count || 0)
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

export function computeDocsPerMinute(rows: RealChartRow[]): number | null {
  const recent = rows.slice(-5)
  if (recent.length < 2) return null

  const bucketMs = Math.max(
    1,
    toFiniteNumber(recent[1]?.t ?? recent[1]?.ts) - toFiniteNumber(recent[0]?.t ?? recent[0]?.ts)
  )
  if (bucketMs <= 0) return null

  const total = recent.reduce(
    (sum, row) => sum + toFiniteNumber(row.completed) + toFiniteNumber(row.failed) + toFiniteNumber(row.quarantined),
    0
  )
  const minutes = (recent.length * bucketMs) / 60_000
  if (minutes <= 0) return null

  return total / minutes
}

export function computeMegabytesPerSecond(documents: Document[], now = new Date()): number | null {
  const nowMs = now.getTime()
  const fiveMinutesMs = 5 * 60 * 1000

  const totalBytes = documents.reduce((sum, doc) => {
    if (doc.status !== 'completed' || !doc.processed_at || !doc.file_size) return sum
    const processedAtMs = new Date(doc.processed_at).getTime()
    if (!Number.isFinite(processedAtMs)) return sum
    if (nowMs - processedAtMs > fiveMinutesMs) return sum
    return sum + toFiniteNumber(doc.file_size)
  }, 0)

  if (totalBytes <= 0) return null
  return totalBytes / (fiveMinutesMs / 1000) / (1024 * 1024)
}

export function computeRemainingMinutesEstimate(queueSize: number, docsPerMinute: number | null): number | null {
  const throughput = toFiniteNumber(docsPerMinute)
  if (throughput <= 0) return null
  return Math.max(0, Math.round((Math.max(0, queueSize) / throughput) * 10) / 10)
}

export function computeEngineLoadScore({
  pending,
  processing,
}: Readonly<{ pending: number; processing: number }>): number {
  const score = pending * 4 + processing * 18
  return Math.max(0, Math.min(100, Math.round(score)))
}

export function getBulkActionAvailability(documents: Document[]): BulkActionAvailability {
  return {
    canRetry: documents.some((doc) => doc.status === 'failed' || doc.status === 'cancelled'),
    canCancel: documents.some((doc) => doc.status === 'pending' || doc.status === 'processing'),
    canDelete: documents.length > 0,
    canExport: documents.length > 0,
  }
}

function escapeCsvCell(value: unknown): string {
  const raw = value == null ? '' : String(value)
  return /[",\n]/.test(raw) ? `"${raw.replaceAll('"', '""')}"` : raw
}

export function serializeDocumentsToCsv(documents: Document[]): string {
  const header = ['id', 'filename', 'status', 'file_size', 'current_stage', 'error_message', 'created_at', 'processed_at']
  const rows = documents.map((doc) =>
    [
      doc.id,
      doc.filename,
      doc.status,
      doc.file_size ?? '',
      doc.current_stage ?? '',
      doc.error_message ?? '',
      doc.created_at ?? '',
      doc.processed_at ?? '',
    ]
      .map(escapeCsvCell)
      .join(',')
  )

  return [header.join(','), ...rows].join('\n')
}

export async function runWithConcurrencyLimit<TInput, TOutput>(
  items: TInput[],
  limit: number,
  worker: (item: TInput, index: number) => Promise<TOutput>
): Promise<TOutput[]> {
  if (!items.length) return []

  const maxConcurrent = Math.max(1, Math.floor(limit))
  const results = new Array<TOutput>(items.length)
  let cursor = 0

  async function runWorker() {
    while (cursor < items.length) {
      const currentIndex = cursor
      cursor += 1
      results[currentIndex] = await worker(items[currentIndex], currentIndex)
    }
  }

  await Promise.all(Array.from({ length: Math.min(maxConcurrent, items.length) }, () => runWorker()))
  return results
}

export function buildSparklinePath(values: number[], width = 80, height = 24): string {
  if (!values.length) return ''
  if (values.length === 1) return `M 0 ${height / 2} L ${width} ${height / 2}`

  const max = Math.max(...values)
  const min = Math.min(...values)
  const range = max - min || 1

  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width
      const y = height - ((value - min) / range) * height
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')
}

export function buildSparklinePlaceholderPath(width = 80, height = 24): string {
  const middle = height / 2
  return `M 0 ${middle} L ${width} ${middle}`
}

export function matchesReasonFilter(doc: Document, reasonFilter: string | null): boolean {
  if (!reasonFilter) return true
  return String(doc.error_message ?? '').includes(reasonFilter)
}

export function getStageTooltip(stage: string | null | undefined): string | null {
  if (!stage) return null
  return STAGE_TOOLTIPS[String(stage).trim().toLowerCase()] ?? null
}

export function getDocumentKind(filename: string | null | undefined): DocumentKind {
  const lower = String(filename || '').trim().toLowerCase()
  if (lower.endsWith('.pdf')) return 'pdf'
  if (lower.endsWith('.md') || lower.endsWith('.mdx')) return 'markdown'
  if (lower.endsWith('.csv') || lower.endsWith('.xls') || lower.endsWith('.xlsx')) return 'spreadsheet'
  if (lower.endsWith('.html') || lower.endsWith('.htm')) return 'html'
  return 'text'
}

export function getDocumentKindAccent(kind: DocumentKind): string {
  switch (kind) {
    case 'pdf':
      return 'text-rose-500 border-rose-500/25 bg-rose-500/10'
    case 'markdown':
      return 'text-sky-500 border-sky-500/25 bg-sky-500/10'
    case 'spreadsheet':
      return 'text-emerald-500 border-emerald-500/25 bg-emerald-500/10'
    case 'html':
      return 'text-amber-500 border-amber-500/25 bg-amber-500/10'
    case 'text':
    default:
      return 'text-muted-foreground border-border/70 bg-muted/40'
  }
}

function percentile(sortedValues: number[], percentage: number): number {
  if (!sortedValues.length) return 0
  const index = Math.min(sortedValues.length - 1, Math.max(0, Math.ceil((percentage / 100) * sortedValues.length) - 1))
  return sortedValues[index]
}

function getDocumentMetadataNumber(
  document: Pick<Document, 'metadata'>,
  key: string
): number {
  const meta = document.metadata
  if (!meta || typeof meta !== 'object') return 0
  return toFiniteNumber((meta as Record<string, unknown>)[key])
}

function getDocumentStageDurationMs(
  document: Pick<Document, 'metadata'>,
  key: string
): number {
  const meta = document.metadata
  if (!meta || typeof meta !== 'object') return 0
  const stages = (meta as Record<string, unknown>).ingest_stage_durations_ms
  if (!stages || typeof stages !== 'object') return 0
  return toFiniteNumber((stages as Record<string, unknown>)[key])
}

function computeDocumentRuntimeDurationMinutes(
  document: Pick<Document, 'metadata'>
): number | null {
  const parseDurationSec = getDocumentMetadataNumber(document, 'parse_duration_sec')
  if (parseDurationSec > 0) return roundTo(parseDurationSec / 60, 2)

  const parseDurationMs = getDocumentStageDurationMs(document, 'parse')
  if (parseDurationMs > 0) return roundTo(parseDurationMs / 60_000, 2)

  return null
}

function computeDocumentDurationMinutes(
  document: Pick<Document, 'status' | 'created_at' | 'updated_at' | 'metadata'>
): number | null {
  if (document.status === 'pending' || document.status === 'processing') return null
  const runtimeDuration = computeDocumentRuntimeDurationMinutes(document)
  if (runtimeDuration != null) return runtimeDuration

  const createdAt = new Date(String(document.created_at || '')).getTime()
  const updatedAt = new Date(String(document.updated_at || '')).getTime()
  if (!Number.isFinite(createdAt) || !Number.isFinite(updatedAt) || updatedAt <= createdAt) return null
  return roundTo((updatedAt - createdAt) / 60_000, 2)
}

export function computePercentiles(values: number[]): PercentileSummary {
  const sorted = [...values].filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (!sorted.length) {
    return { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0, max: 0 }
  }

  return {
    p25: percentile(sorted, 25),
    p50: percentile(sorted, 50),
    p75: percentile(sorted, 75),
    p90: percentile(sorted, 90),
    p99: percentile(sorted, 99),
    max: sorted.at(-1) ?? 0,
  }
}

export function computeDurationPercentiles(documents: Document[]): PercentileSummary {
  return computePercentiles(
    documents
      .map((document) => computeDocumentDurationMinutes(document))
      .filter((value): value is number => value != null)
  )
}

export function buildExecutionStatusRows(documents: Document[]): ExecutionStatusRow[] {
  const counts = new Map<string, number>()
  documents.forEach((document) => {
    const key = String(document.status || 'unknown')
    counts.set(key, (counts.get(key) ?? 0) + 1)
  })

  const meta: Record<string, { name: string; fill: string }> = {
    processing: { name: '处理中', fill: '#38bdf8' },
    pending: { name: '等待队列', fill: '#94a3b8' },
    completed: { name: '已完成', fill: '#34d399' },
    failed: { name: '解析失败', fill: '#fb7185' },
    quarantined: { name: '失败/隔离', fill: '#f59e0b' },
    cancelled: { name: '已取消', fill: '#a78bfa' },
    unknown: { name: '未知状态', fill: '#64748b' },
  }

  return Array.from(counts.entries())
    .map(([key, value]) => ({
      key,
      name: meta[key]?.name ?? key,
      value,
      fill: meta[key]?.fill ?? meta.unknown.fill,
    }))
    .sort((left, right) => right.value - left.value)
}

export function buildStageTreemapRows(stageCounts: Record<string, number>): StageTreemapRow[] {
  const palette = ['#0ea5e9', '#8b5cf6', '#14b8a6', '#f97316', '#ef4444', '#a855f7', '#64748b']
  return Object.entries(stageCounts)
    .filter(([, value]) => Number(value) > 0)
    .sort((left, right) => Number(right[1]) - Number(left[1]))
    .map(([name, value], index) => ({
      name,
      value: toFiniteNumber(value),
      fill: palette[index % palette.length],
    }))
}

export function buildThroughputAreaRows(timeseries: Record<string, unknown[]> | null | undefined): ThroughputAreaRow[] {
  const ts = Array.isArray(timeseries?.ts_ms) ? timeseries.ts_ms : []
  const completed = Array.isArray(timeseries?.completed) ? timeseries.completed : []
  const failed = Array.isArray(timeseries?.failed) ? timeseries.failed : []
  const quarantined = Array.isArray(timeseries?.quarantined) ? timeseries.quarantined : []
  const cancelled = Array.isArray(timeseries?.cancelled) ? timeseries.cancelled : []

  return ts.map((value, index) => {
    const completedValue = toFiniteNumber(completed[index])
    const failedValue = toFiniteNumber(failed[index])
    const quarantinedValue = toFiniteNumber(quarantined[index])
    const cancelledValue = toFiniteNumber(cancelled[index])

    return {
      ts: toFiniteNumber(value),
      completed: completedValue,
      failed: failedValue,
      quarantined: quarantinedValue,
      cancelled: cancelledValue,
      total: completedValue + failedValue + quarantinedValue + cancelledValue,
    }
  })
}

export function buildDocumentThroughputAreaRows(
  documents: Document[],
  options: { bucketMinutes?: number; maxRows?: number } = {}
): ThroughputAreaRow[] {
  const bucketMinutes = Math.max(1, Math.round(toFiniteNumber(options.bucketMinutes) || 60))
  const bucketMs = bucketMinutes * 60_000
  const maxRows = Math.max(1, Math.round(toFiniteNumber(options.maxRows) || 120))
  const buckets = new Map<number, ThroughputAreaRow>()

  documents.forEach((document) => {
    const status = String(document.status || '').toLowerCase()
    if (!['completed', 'failed', 'quarantined', 'cancelled'].includes(status)) return

    const timestamp = Date.parse(
      String(document.processed_at || document.updated_at || document.created_at || '')
    )
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
    .slice(-maxRows)
}

export function buildLatencyBoxplotRows(documents: Document[]): LatencyBoxplotRows {
  const groups = [
    { label: '已完成', values: documents.filter((document) => document.status === 'completed') },
    { label: '失败/隔离', values: documents.filter((document) => ['failed', 'quarantined', 'cancelled'].includes(String(document.status))) },
  ]

  const rows = groups
    .map((group) => {
      const values = group.values
        .map((document) => computeDocumentDurationMinutes(document))
        .filter((value): value is number => value != null)
        .sort((left, right) => left - right)

      if (!values.length) return null
      return {
        category: group.label,
        values: [
          values[0],
          percentile(values, 25),
          percentile(values, 50),
          percentile(values, 75),
          values.at(-1) ?? 0,
        ] as [number, number, number, number, number],
      }
    })
    .filter((value): value is { category: string; values: [number, number, number, number, number] } => value != null)

  return {
    categories: rows.map((row) => row.category),
    values: rows.map((row) => row.values),
  }
}

export function buildExecutionScatterRows(documents: Document[]): ExecutionScatterRow[] {
  return documents
    .map((document) => {
      const durationMinutes = computeDocumentDurationMinutes(document)
      const fileSize = toFiniteNumber(document.file_size)
      if (durationMinutes == null || fileSize <= 0) return null

      return {
        documentId: String(document.id || ''),
        filename: String(document.filename || ''),
        status: String(document.status || 'unknown'),
        fileSizeMB: roundTo(fileSize / (1024 * 1024), 2),
        durationMinutes,
      }
    })
    .filter((value): value is ExecutionScatterRow => value != null)
}

export function buildFileTypeDistribution(documents: Document[]): Array<{ label: string; count: number }> {
  const counts = new Map<string, number>()
  documents.forEach((doc) => {
    const label = String(doc.file_type || getDocumentKind(doc.filename) || 'unknown').trim().toUpperCase() || 'UNKNOWN'
    counts.set(label, (counts.get(label) ?? 0) + 1)
  })
  return Array.from(counts.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count)
}

export function buildFileSizeDistribution(documents: Document[]): Array<{ label: string; count: number }> {
  const buckets = [
    { label: '<500KB', min: 0, max: 500 * 1024 },
    { label: '500KB-2MB', min: 500 * 1024, max: 2 * 1024 * 1024 },
    { label: '2MB-5MB', min: 2 * 1024 * 1024, max: 5 * 1024 * 1024 },
    { label: '5MB-10MB', min: 5 * 1024 * 1024, max: 10 * 1024 * 1024 },
    { label: '>10MB', min: 10 * 1024 * 1024, max: Number.POSITIVE_INFINITY },
  ]

  return buckets.map((bucket) => ({
    label: bucket.label,
    count: documents.filter((doc) => {
      const size = toFiniteNumber(doc.file_size)
      return size >= bucket.min && size < bucket.max
    }).length,
  }))
}

export function computeMeanFileSize(documents: Document[]): number {
  if (!documents.length) return 0
  const total = documents.reduce((sum, doc) => sum + toFiniteNumber(doc.file_size), 0)
  return Math.round(total / documents.length)
}

export function buildPdfDispositionBreakdown(documents: Document[]): Array<{ label: string; count: number }> {
  const counts = {
    OCR: 0,
    Native: 0,
    Mixed: 0,
  }

  for (const doc of documents) {
    if (String(doc.file_type || '').toLowerCase() !== 'pdf') continue
    const profile = String(doc.metadata?.audit_profile || '').toLowerCase()
    if (profile === 'scan_pdf') counts.OCR += 1
    else if (profile === 'mixed_pdf') counts.Mixed += 1
    else counts.Native += 1
  }

  return [
    { label: 'OCR', count: counts.OCR },
    { label: 'Native', count: counts.Native },
    { label: 'Mixed', count: counts.Mixed },
  ]
}

export function buildSalesAuditProfile(
  summary: DatasetPrecheckSummary,
  nearDup?: DatasetPrecheckNearDupResponse | null
): SalesAuditProfile {
  const totalFiles = Math.max(1, Number(summary.total_files || 0))
  const pdfTotal = Number(summary.pdf_scan.scanned || 0) + Number(summary.pdf_scan.not_scanned || 0) + Number(summary.pdf_scan.unknown || 0)
  const ocrCount = Number(summary.pdf_scan.scanned || 0) + Number(summary.pdf_scan.unknown || 0)
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
  const dedup = countFinding(summary, 'near_dup') + countFinding(summary, 'exact_dup') + Number(nearDup?.pairs_returned || 0)

  const score =
    ocrRatio * 42 +
    Math.min(20, (tableHeavy / totalFiles) * 80 + tableHeavy * 0.4) +
    Math.min(28, (blocking / totalFiles) * 130 + blocking * 0.35) +
    Math.min(14, (dedup / totalFiles) * 55 + Number(nearDup?.clusters_returned || 0) * 0.6)

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
  const pocSampleCount = clamp(Math.ceil(totalFiles * pocRatio), 5, 40)

  return {
    complexity,
    pricingMode,
    pocSampleCount,
    costDrivers: [
      { key: 'ocr', label: 'OCR / 混合 PDF', count: ocrCount, tone: ocrCount > 0 ? 'cost' : 'ready' },
      { key: 'table_heavy', label: '表格重文档', count: tableHeavy, tone: tableHeavy > 0 ? 'cost' : 'neutral' },
      { key: 'blocking', label: '阻断 / 待复核', count: blocking, tone: blocking > 0 ? 'blocker' : 'ready' },
      { key: 'dedup', label: '版本冲突', count: dedup, tone: dedup > 0 ? 'neutral' : 'ready' },
    ],
  }
}

export function buildEvidenceSlotTags(file: DatasetPrecheckFileOut): EvidenceSlotTag[] {
  const findings = new Set((file.findings || []).map((value) => String(value || '').trim().toLowerCase()))
  const tags: EvidenceSlotTag[] = []

  if (findings.has('parse_failed')) tags.push('PARSE_FAILED')
  if (file.file_type.toLowerCase() === 'pdf' && (file.pdf_scanned === true || findings.has('pdf_unknown'))) tags.push('OCR_REQUIRED')
  if (
    file.file_type.toLowerCase() === 'csv' ||
    file.file_type.toLowerCase() === 'xls' ||
    file.file_type.toLowerCase() === 'xlsx' ||
    findings.has('large_spreadsheet') ||
    findings.has('wide_spreadsheet') ||
    findings.has('many_sheets_spreadsheet') ||
    findings.has('merged_heavy_spreadsheet')
  ) {
    tags.push('TABLE_HEAVY')
  }
  if (findings.has('pii') || findings.has('secrets')) tags.push('SENSITIVE_REVIEW')
  if (findings.has('near_dup') || findings.has('exact_dup')) tags.push('VERSION_CONFLICT')
  if (findings.has('low_density_text') || findings.has('pdf_low_density') || findings.has('gibberish_text')) tags.push('LOW_SIGNAL')

  if (!tags.length) tags.push('STRAIGHT_THROUGH')

  return tags
}

export function buildEvidenceSlotReason(file: DatasetPrecheckFileOut): string {
  const findings = new Set((file.findings || []).map((value) => String(value || '').trim().toLowerCase()))

  if (findings.has('parse_failed')) {
    return `解析失败，需人工检查${file.error_message ? `：${file.error_message}` : ''}`
  }

  if (file.file_type.toLowerCase() === 'pdf' && file.pdf_pages?.page_count) {
    const scanRatio = Math.round(Number(file.pdf_pages.scan_ratio || 0) * 100)
    if (file.pdf_scanned === true || findings.has('pdf_unknown')) {
      return `扫描页占比 ${scanRatio}% ，建议先 OCR 再分流`
    }
  }

  if (file.spreadsheet) {
    return `表格结构复杂（${file.spreadsheet.row_count}x${file.spreadsheet.col_count} / ${file.spreadsheet.sheet_count} sheets）`
  }

  const sensitiveCount =
    Object.values(file.pii_hits || {}).reduce((sum, value) => sum + Number(value || 0), 0) +
    Object.values(file.secrets_hits || {}).reduce((sum, value) => sum + Number(value || 0), 0)
  if (sensitiveCount > 0) {
    return `发现 ${sensitiveCount} 条待审核敏感命中，建议复核上下文`
  }

  if (findings.has('near_dup') || findings.has('exact_dup')) {
    return '存在版本冲突候选，建议纳入抽样确认'
  }

  return `正文约 ${Number(file.text_characters || 0)} chars，可作为直通样本`
}
