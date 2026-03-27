'use client'

import type {
  Citation,
  EvidenceItemStatus,
  EvidenceRetrieveResponse,
  JsonObject,
  ReferenceSource,
} from '@/types'

export type RetrievalProfile = 'recall50' | 'coverage80' | 'recall20'

type JsonRecord = JsonObject

export type EvidenceRetrieveResult = Omit<EvidenceRetrieveResponse, 'citations'> & {
  citations?: Citation[]
}

export type EvidenceImportPack = JsonObject & {
  citations?: Citation[]
  selected_chunk_ids?: string[]
  retrieval_profile?: string | null
  version?: string | number | null
}

export const RETRIEVAL_PROFILE_VALUES = ['recall50', 'coverage80', 'recall20'] as const
export const EMPTY_CITATIONS: Citation[] = []

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function safeJsonStringify(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value)
  } catch {
    return ''
  }
}

function toOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function toOptionalNumber(value: unknown): number | undefined {
  const next = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(next) ? next : undefined
}

function toStringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined
  const items = value.map((item) => String(item || '').trim()).filter(Boolean)
  return items.length ? items : undefined
}

function toCitation(value: unknown): Citation | null {
  if (!isRecord(value)) return null
  const document_id = toOptionalString(value.document_id) ?? ''
  const document_name = toOptionalString(value.document_name) ?? ''
  const chunk_content = typeof value.chunk_content === 'string' ? value.chunk_content : ''
  const relevance_score = toOptionalNumber(value.relevance_score) ?? 0

  if (!document_id || !document_name) return null

  const citation: Citation = {
    document_id,
    document_name,
    chunk_content,
    relevance_score,
  }

  citation.chunk_id = toOptionalString(value.chunk_id)
  citation.page_number = toOptionalNumber(value.page_number)
  citation.chunk_index = toOptionalNumber(value.chunk_index)
  citation.start_char = toOptionalNumber(value.start_char)
  citation.end_char = toOptionalNumber(value.end_char)
  citation.header_path = toOptionalString(value.header_path)
  citation.doc_pipeline_key = toOptionalString(value.doc_pipeline_key)
  citation.pipeline_hash = toOptionalString(value.pipeline_hash)
  citation.hit_type = toOptionalString(value.hit_type)
  citation.retrieval_score = toOptionalNumber(value.retrieval_score)
  citation.rerank_score = toOptionalNumber(value.rerank_score)
  citation.vector_score = toOptionalNumber(value.vector_score)
  citation.bm25_score = toOptionalNumber(value.bm25_score)
  citation.keyword_score = toOptionalNumber(value.keyword_score)
  citation.matched_terms = toStringList(value.matched_terms)

  return citation
}

export function normalizeCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return EMPTY_CITATIONS
  const citations = value.map(toCitation).filter((citation): citation is Citation => citation !== null)
  return citations.length ? citations : EMPTY_CITATIONS
}

export function normalizeRetrieveResult(value: EvidenceRetrieveResponse | null | undefined): EvidenceRetrieveResult | null {
  if (!value) return null
  return {
    ...value,
    citations: normalizeCitations(value.citations),
  }
}

export function normalizeImportPack(value: unknown): EvidenceImportPack | null {
  if (!isRecord(value)) return null
  return {
    ...value,
    citations: normalizeCitations(value.citations),
    selected_chunk_ids: toStringList(value.selected_chunk_ids),
    retrieval_profile: typeof value.retrieval_profile === 'string' ? value.retrieval_profile : null,
    version: typeof value.version === 'string' || typeof value.version === 'number' ? value.version : null,
  }
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  let text = ''
  if (typeof error === 'string') {
    text = error.trim()
  } else if (typeof error === 'number' || typeof error === 'boolean' || typeof error === 'bigint') {
    text = String(error)
  } else if (isRecord(error)) {
    text = safeJsonStringify(error)
  }
  return text || 'unknown'
}

export function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  return null
}

export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

export function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

export function evidenceStatusBadgeVariant(status: EvidenceItemStatus): 'outline' | 'secondary' | 'soft' | 'destructive' {
  if (status === 'approved') return 'soft'
  if (status === 'reviewed') return 'secondary'
  if (status === 'archived') return 'outline'
  return 'outline'
}

export function buildReferenceSources(citations: Citation[], selectedChunkIds: Set<string>): ReferenceSource[] {
  const out: ReferenceSource[] = []
  for (const citation of citations || []) {
    const chunkId = String(citation.chunk_id || '')
    if (!chunkId || !selectedChunkIds.has(chunkId)) continue
    const docId = String(citation.document_id || '')
    if (!docId) continue
    out.push({
      document_id: docId,
      chunk_id: chunkId,
      chunk_index: typeof citation.chunk_index === 'number' ? citation.chunk_index : undefined,
      page_number: typeof citation.page_number === 'number' ? citation.page_number : undefined,
      start_char: typeof citation.start_char === 'number' ? citation.start_char : undefined,
      end_char: typeof citation.end_char === 'number' ? citation.end_char : undefined,
      doc_pipeline_key: citation.doc_pipeline_key || undefined,
      pipeline_hash: citation.pipeline_hash || undefined,
      quote: (citation.chunk_content || '').slice(0, 2000) || undefined,
      label: citation.header_path || citation.document_name || undefined,
    })
  }
  return out
}

export function safeIsoForFilename(ts: string) {
  return (ts || new Date().toISOString()).replaceAll(/[:.]/g, '-')
}
