import type { DatasetProfileHistogramBin, DatasetProfileSummary } from '@/lib/dataset-profile-schema'

type ProfileChartRow = Readonly<{ key: string | null; name: string; value: number }>

const DOCUMENT_STATUS_PRESENTATION = new Map<string, { name: string; fill: string }>([
  ['pending', { name: '等待', fill: 'hsl(var(--info))' }],
  ['processing', { name: '处理中', fill: 'hsl(var(--warning))' }],
  ['completed', { name: '已完成', fill: 'hsl(var(--success))' }],
  ['failed', { name: '失败', fill: 'hsl(var(--destructive))' }],
  ['quarantined', { name: '已隔离', fill: 'hsl(var(--warning))' }],
  ['cancelled', { name: '已取消', fill: 'hsl(var(--muted-foreground))' }],
  ['deleting', { name: '删除中', fill: 'hsl(var(--warning))' }],
])

const QUALITY_LABELS: Readonly<Record<string, string>> = {
  high_density: '高密度',
  mid_density: '中密度',
  low_density: '低密度',
  outline_heavy: '目录/标题占比高',
  tiny: '内容过短',
  unknown: '未知',
}

function countRows(counts: Readonly<Record<string, number>>) {
  return Object.entries(counts).map(([key, value]) => ({ key, name: key, value }))
}
function histogramRows(bins: readonly DatasetProfileHistogramBin[]) {
  return bins.map((bin) => ({ name: bin.label, value: bin.count }))
}
function largestRows(
  counts: Readonly<Record<string, number>>,
  { limit, includeRemainder = false }: Readonly<{ limit: number; includeRemainder?: boolean }>,
) {
  const rows = countRows(counts).sort((a, b) => b.value - a.value || a.name.localeCompare(b.name))
  const top: ProfileChartRow[] = rows.slice(0, limit)
  if (includeRemainder && rows.length > limit) {
    top.push({ key: null, name: '其他（汇总）', value: rows.slice(limit).reduce((total, row) => total + row.value, 0) })
  }
  return top
}
function orderedRows(counts: Readonly<Record<string, number>>, order: readonly string[]) {
  function rank(key: string) {
    const index = order.indexOf(key)
    return index === -1 ? order.length : index
  }
  return countRows(counts).sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))
}

export function buildDatasetProfileModel(summary: DatasetProfileSummary, palette: readonly [string, ...string[]]) {
  function colored(rows: readonly ProfileChartRow[]) {
    return rows.map((row, index) => ({ ...row, fill: palette[index % palette.length] }))
  }
  return {
    fileTypes: colored(largestRows(summary.by_file_type, { limit: 10, includeRemainder: true })),
    statuses: countRows(summary.by_status).map((row) => ({
      ...row,
      ...(DOCUMENT_STATUS_PRESENTATION.get(row.key) ?? { fill: 'hsl(var(--muted-foreground))' }),
    })),
    lengths: histogramRows(summary.length_histogram),
    fileSizes: histogramRows(summary.file_size_histogram),
    pageCounts: histogramRows(summary.page_number_histogram),
    parseQuality: histogramRows(summary.parse_quality_histogram),
    chunkCounts: histogramRows(summary.chunk_count_histogram),
    averageChunkChars: histogramRows(summary.avg_chunk_chars_histogram),
    chunkLengths: histogramRows(summary.chunk_length_histogram),
    languages: colored(orderedRows(summary.language_mix, ['zh', 'en', 'mixed', 'unknown'])),
    directories: largestRows(summary.by_directory, { limit: 12, includeRemainder: true }),
    qualityBuckets: orderedRows(summary.by_quality_bucket, Object.keys(QUALITY_LABELS)).map((row) => ({
      ...row,
      name: Object.hasOwn(QUALITY_LABELS, row.key) ? QUALITY_LABELS[row.key] : row.name,
    })),
    pdfScans: [
      { name: 'scanned', value: summary.pdf_scan.scanned, fill: '#fb7185' },
      { name: 'text', value: summary.pdf_scan.not_scanned, fill: '#38bdf8' },
      { name: 'unknown', value: summary.pdf_scan.unknown, fill: '#94a3b8' },
    ],
    pii: largestRows(summary.pii_hits_total, { limit: 10 }),
    secrets: largestRows(summary.secrets_hits_total, { limit: 10 }),
    parsingBackends: largestRows(summary.parsing_provenance.by_resolved_backend, { limit: 10 }),
    chunkTargets: summary.chunk_targets,
    parseLowQualityFinding: summary.findings.find((finding) => finding.key === 'parse_low_quality'),
    fallbackRate:
      summary.parsing_provenance.docs_with_provenance > 0
        ? summary.parsing_provenance.fallback_docs / summary.parsing_provenance.docs_with_provenance
        : null,
    activeFindings: summary.findings.filter((finding) => finding.count > 0),
    zeroFindings: summary.findings.filter((finding) => finding.count === 0),
    piiCount: Object.values(summary.pii_hits_total).reduce((total, count) => total + count, 0),
    secretsCount: Object.values(summary.secrets_hits_total).reduce((total, count) => total + count, 0),
    piiRecorded: Object.keys(summary.pii_hits_total).length > 0,
    secretsRecorded: Object.keys(summary.secrets_hits_total).length > 0,
    pdfCount: summary.pdf_scan.scanned + summary.pdf_scan.not_scanned + summary.pdf_scan.unknown,
  } as const
}
