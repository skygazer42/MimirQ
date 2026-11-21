import type { DatasetHealthResponse } from './dataset-profile-schema'

type DatasetHealthExportInput = Readonly<{
  dataset: Readonly<{ id: string; name: string }>
  exported_at: string
  health: DatasetHealthResponse
}>

function toSingleLine(text: string): string {
  return text.replaceAll(/\s+/g, ' ').trim()
}

export function datasetHealthToMarkdown({ dataset, exported_at, health }: DatasetHealthExportInput): string {
  const { profile, ingestion } = health
  const lines = [
    '# Dataset Health',
    '',
    `- dataset_id: ${toSingleLine(dataset.id)}`,
    `- dataset_name: ${toSingleLine(dataset.name)}`,
    `- exported_at: ${exported_at}`,
    `- generated_at: ${health.generated_at}`,
    '',
    '## Profile',
    `- total_documents: ${profile.total_documents}`,
    `- total_size_bytes: ${profile.total_size_bytes}`,
    '',
    '## Ingestion',
    `- total_documents: ${ingestion.total_documents}`,
    `- failed: ${ingestion.failed}`,
    `- quarantined: ${ingestion.quarantined}`,
  ]

  for (const [status, count] of Object.entries(ingestion.by_status)) {
    lines.push(`- ${toSingleLine(status)}: ${count}`)
  }

  lines.push('')
  return lines.join('\n')
}
