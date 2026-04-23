import type { Document } from '@/types'

export type VelocityUnit = 'docs' | 'bytes'

export type RealChartRow = {
  t: number
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

export const STAGE_TOOLTIPS: Record<string, string> = {
  queued: '等待调度,即将开始处理',
  parsing: '通过 OCR / 解析器提取文本',
  chunking: '按语义切分文档为可检索片段',
  embedding: '向量化与索引构建中',
  completed: '已可被检索',
}

function toFiniteNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

export function computeDocsPerMinute(rows: RealChartRow[]): number | null {
  const recent = rows.slice(-5)
  if (recent.length < 2) return null

  const bucketMs = Math.max(1, toFiniteNumber(recent[1]?.t) - toFiniteNumber(recent[0]?.t))
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
    max: sorted[sorted.length - 1],
  }
}

export function buildFileTypeDistribution(documents: Document[]): Array<{ label: string; count: number }> {
  const counts = new Map<string, number>()
  documents.forEach((doc) => {
    const label = String(doc.file_type || 'unknown').trim().toUpperCase() || 'UNKNOWN'
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
    const profile = String((doc.metadata as Record<string, unknown> | undefined)?.audit_profile || '').toLowerCase()
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
