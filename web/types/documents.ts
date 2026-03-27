/**
 * Document-related types re-exported by `@/types`.
 */

import type { JsonObject } from './common'

export type Document = import('./backend').Document
export type DocumentList = import('./backend').DocumentList
export type GovernanceInfo = import('./backend').GovernanceInfo
export type DocumentStatus = import('./backend').DocumentStatus
export type DocumentTimelineItem = import('./backend').DocumentTimelineItem
export type DocumentTimelineResponse = import('./backend').DocumentTimelineResponse
export type DocumentVersionInfo = import('./backend').DocumentVersionInfo
export type DocumentVersionList = import('./backend').DocumentVersionList
export type DocumentVersionDiff = import('./backend').DocumentVersionDiff
export type DocumentAccessInfo = import('./backend').DocumentAccessInfo
export type DocumentAccessUpdateRequest = import('./backend').DocumentAccessUpdateRequest
export type DocumentFolderNode = import('./backend').DocumentFolderNode
export type DocumentFolderTreeResponse = import('./backend').DocumentFolderTreeResponse

export interface DocumentHealthParsing {
  parser_backend?: string | null
  parser_backend_requested?: string | null
  parse_quality?: JsonObject | null
  pdf_quality?: JsonObject | null

  is_scanned?: boolean | null
  page_count?: number | null

  processed_at?: string | null
}

export interface DocumentHealthChunkCoverage {
  sum_chunk_chars: number
  covered_chars: number
  coverage_ratio: number
  overlap_waste_ratio: number
  gap_count: number
  largest_gap: number
}

export interface DocumentHealthSemanticQualitySummary {
  sampled_chunks: number
  needs_review: number
  needs_review_ratio: number

  mean_information_density?: number | null
  mean_semantic_completeness?: number | null
  mean_self_containedness?: number | null
  mean_pronoun_ratio?: number | null

  overall_histogram_10: number[]
  note?: string | null
}

export interface DocumentHealthChunking {
  chunk_strategy?: string | null
  chunk_strategy_requested?: string | null

  chunk_count: number
  total_characters: number

  coverage: DocumentHealthChunkCoverage
  semantic_quality?: DocumentHealthSemanticQualitySummary | null
}

export interface DocumentHealthRetrievalHits {
  enabled: boolean
  available: boolean
  path?: string | null
  window_minutes: number
  max_bytes: number
  truncated: boolean

  traces_scanned: number
  traces_with_hits: number
  citations_matched: number
  unique_chunks_matched?: number | null
  hit_rate?: number | null
}

export interface DocumentHealthCard {
  document_id: string
  dataset_id?: string | null
  filename?: string | null
  file_type?: string | null
  file_size?: number | null
  created_at?: string | null
  updated_at?: string | null

  generated_at: string
  status?: string | null

  parsing: DocumentHealthParsing
  chunking: DocumentHealthChunking
  kg?: JsonObject | null
  retrieval_hits?: DocumentHealthRetrievalHits | null
}
