import { toSingleLinePrimitiveString } from './primitive-text'

export type DatasetHealthSuggestion = {
  severity: 'info' | 'warning' | 'error'
  title: string
  detail: string
}

export type DatasetHealthExportInput = {
  datasetId: string
  datasetName?: string | null
  exportedAt?: string | null
  generatedAt?: string | null
  profile?: any
  ingestion?: any
  suggestions?: DatasetHealthSuggestion[]
}

function asInt(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

function oneLine(value: unknown): string {
  return toSingleLinePrimitiveString(value)
}

export function datasetHealthToMarkdown(input: DatasetHealthExportInput): string {
  const lines: string[] = []

    lines.push('# Dataset Health', '', `- dataset_id: ${oneLine(input.datasetId)}`)
  if (input.datasetName) lines.push(`- dataset_name: ${oneLine(input.datasetName)}`)
  if (input.exportedAt) lines.push(`- exported_at: ${oneLine(input.exportedAt)}`)
  if (input.generatedAt) lines.push(`- generated_at: ${oneLine(input.generatedAt)}`)
  lines.push('')

  const profile = input.profile || {}
    lines.push('## Profile', `- total_documents: ${asInt(profile.total_documents)}`)
  if (profile.total_size_bytes != null) lines.push(`- total_size_bytes: ${asInt(profile.total_size_bytes)}`)
  lines.push('')

  const ingestion = input.ingestion || {}
    lines.push('## Ingestion', `- total_documents: ${asInt(ingestion.total_documents)}`, `- failed: ${asInt(ingestion.failed)}`, `- quarantined: ${asInt(ingestion.quarantined)}`)

  const byStatus = ingestion.by_status && typeof ingestion.by_status === 'object' ? ingestion.by_status : null
  if (byStatus) {
    const parts = Object.entries(byStatus)
      .map(([k, v]) => `${oneLine(k)}=${asInt(v)}`)
      .filter((x) => !x.endsWith('=0'))
    if (parts.length) lines.push(`- by_status: ${parts.join(', ')}`)
  }
  lines.push('')

  const suggestions = Array.isArray(input.suggestions) ? input.suggestions : []
  lines.push('## Suggestions')
  if (suggestions.length === 0) {
    lines.push('- (none)')
  } else {
    for (const s of suggestions) {
      const sev = oneLine(s.severity || 'info')
      const title = oneLine(s.title)
      const detail = oneLine(s.detail)
      const detailSuffix = detail ? `: ${detail}` : ''
      lines.push(`- [${sev}] ${title}${detailSuffix}`)
    }
  }

  lines.push('')
  return lines.join('\n')
}
