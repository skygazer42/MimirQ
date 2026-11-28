'use client'

import { z } from 'zod'
import type { EvidenceItemCreate, EvidenceItemStatus, EvidenceRetrieveResponse } from '@/types'
import { evidenceCitationSchema, parseEvidenceCitations, type EvidenceCitation } from '@/lib/evidence-citations'
import { downloadBlob } from '@/lib/download'

export const RETRIEVAL_PROFILE_VALUES = ['recall50', 'coverage80', 'recall20'] as const
export type RetrievalProfile = (typeof RETRIEVAL_PROFILE_VALUES)[number]
export const EMPTY_CITATIONS: readonly EvidenceCitation[] = []

export type EvidenceRetrieveResult = Omit<EvidenceRetrieveResponse, 'citations'> & { citations: EvidenceCitation[] }

const evidenceImportPackSchema = z.looseObject({
  citations: z.array(evidenceCitationSchema),
  selected_chunk_ids: z.array(z.string()).optional(),
  retrieval_profile: z.string().nullish(),
  version: z.union([z.string(), z.number()]).nullish(),
})
export type EvidenceImportPack = z.infer<typeof evidenceImportPackSchema>
type EvidenceReferenceSource = EvidenceItemCreate['reference_sources'][number]

export function parseEvidenceRetrieveResult(response: EvidenceRetrieveResponse): EvidenceRetrieveResult {
  return { ...response, citations: parseEvidenceCitations(response.citations) }
}

export function parseEvidenceImportPack(value: unknown): EvidenceImportPack {
  return evidenceImportPackSchema.parse(value)
}

export function downloadJson(filename: string, data: unknown): void {
  downloadBlob(filename, new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' }))
}

export function evidenceStatusBadgeVariant(status: EvidenceItemStatus): 'outline' | 'secondary' | 'soft' {
  if (status === 'approved') return 'soft'
  if (status === 'reviewed') return 'secondary'
  return 'outline'
}

function referenceCoordinate(value: number | null | undefined, minimum: number): number | null | undefined {
  if (value === undefined || value === null) return value
  return Number.isInteger(value) && value >= minimum ? value : undefined
}

function referenceText(value: string | null | undefined, limit: number): string | null | undefined {
  if (value === undefined || value === null) return value
  return Array.from(value).slice(0, limit).join('')
}

export function buildReferenceSources(
  citations: readonly EvidenceCitation[],
  selectedChunkIds: ReadonlySet<string>,
): EvidenceReferenceSource[] {
  const references: EvidenceReferenceSource[] = []
  const addedChunkIds = new Set<string>()
  for (const citation of citations) {
    const chunkId = citation.chunk_id
    if (!chunkId || !selectedChunkIds.has(chunkId) || addedChunkIds.has(chunkId)) continue
    if (!citation.document_id) throw new Error('所选引用缺少文档标识')
    references.push({
      document_id: citation.document_id,
      chunk_id: chunkId,
      chunk_index: referenceCoordinate(citation.chunk_index, 0),
      page_number: referenceCoordinate(citation.page_number, 1),
      start_char: referenceCoordinate(citation.start_char, 0),
      end_char: referenceCoordinate(citation.end_char, 0),
      doc_pipeline_key: citation.doc_pipeline_key,
      pipeline_hash: citation.pipeline_hash,
      family_collapse_key: citation.family_collapse_key,
      hierarchy_family_key: citation.hierarchy_family_key,
      record_identity: citation.record_identity,
      semantic_keys: citation.semantic_keys ?? undefined,
      quote: referenceText(citation.chunk_content, 2000),
      label: referenceText(citation.header_path ?? citation.document_name, 100),
    })
    addedChunkIds.add(chunkId)
  }
  if (addedChunkIds.size !== selectedChunkIds.size) throw new Error('所选切片不在当前引用中')
  return references
}

export function safeIsoForFilename(timestamp: string): string {
  return timestamp.replaceAll(/[:.]/g, '-')
}
