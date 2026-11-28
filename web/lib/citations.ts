import { z } from 'zod'

import { recordSchema } from '@/lib/response-schema'
import type { Citation } from '@/types/processing'

function optionalCitationField<T>(schema: z.ZodType<T>): z.ZodType<T | undefined> {
  return schema.nullish().transform((value) => (value === null ? undefined : value))
}

const optionalText = optionalCitationField(z.string())
const optionalNumber = optionalCitationField(z.number())
const optionalBoolean = optionalCitationField(z.boolean())
const optionalTextList = optionalCitationField(z.array(z.string()))

export function getCitationRange({
  evidence_start_char: evidenceStart,
  evidence_end_char: evidenceEnd,
  start_char: start,
  end_char: end,
}: Pick<Citation, 'evidence_start_char' | 'evidence_end_char' | 'start_char' | 'end_char'>) {
  if (evidenceStart !== undefined && evidenceEnd !== undefined && evidenceEnd > evidenceStart) {
    return { start: evidenceStart, end: evidenceEnd }
  }
  return start !== undefined && end !== undefined && end > start ? { start, end } : undefined
}

const citationSchema = z.looseObject({
  document_id: z.string(),
  document_name: z.string(),
  chunk_content: z.string(),
  relevance_score: z.number(),
  chunk_id: optionalText,
  matched_terms: optionalTextList,
  page_number: optionalNumber,
  bbox: optionalCitationField(z.object({ x0: z.number(), y0: z.number(), x1: z.number(), y1: z.number() })),
  bbox_page_number: optionalNumber,
  chunk_index: optionalNumber,
  start_char: optionalNumber,
  end_char: optionalNumber,
  evidence_start_char: optionalNumber,
  evidence_end_char: optionalNumber,
  header_path: optionalText,
  chunk_strategy: optionalText,
  chunk_role: optionalText,
  chunk_semantic_role: optionalText,
  policy_clause_id: optionalText,
  policy_clause_number: optionalText,
  policy_path: optionalTextList,
  policy_path_str: optionalText,
  parent_id: optionalText,
  retrieval_role: optionalText,
  neighbor_of: optionalText,
  kg_path: optionalCitationField(z.array(z.object({ entity_id: z.string(), type: optionalText }))),
  kg_path_provenance: optionalCitationField(recordSchema),
  doc_pipeline_key: optionalText,
  pipeline_hash: optionalText,
  vector_score: optionalNumber,
  bm25_score: optionalNumber,
  keyword_score: optionalNumber,
  rerank_score: optionalNumber,
  retrieval_score: optionalNumber,
  reranker_provider: optionalText,
  rerank_elapsed_sec: optionalNumber,
  rerank_model_used: optionalText,
  retrieval_mode: optionalText,
  vector_backend: optionalText,
  retrieval_elapsed_sec: optionalNumber,
  hit_type: optionalText,
  has_image: optionalBoolean,
  img_id: optionalText,
  img_url: optionalText,
})

export const citationListSchema: z.ZodType<Citation[]> = z.array(
  citationSchema.transform((citation) => {
    delete citation.sparse_score
    delete citation.colbert_score
    return citation
  }),
)

export const retrievalPreviewCitationsSchema = z.array(
  z.looseObject({
    document_id: optionalText,
    document_name: optionalText,
    chunk_id: optionalText,
    chunk_content: optionalText,
    matched_terms: optionalTextList,
    retrieval_role: optionalText,
    family_hit: optionalBoolean,
    img_url: optionalText,
    score: optionalNumber,
    relevance_score: optionalNumber,
    retrieval_score: optionalNumber,
    policy_clause_number: optionalText,
    policy_path_str: optionalText,
    page_number: optionalNumber,
    bbox_page_number: optionalNumber,
    start_char: optionalNumber,
    end_char: optionalNumber,
    evidence_start_char: optionalNumber,
    evidence_end_char: optionalNumber,
  }),
)

export type RetrievePreviewCitation = z.infer<typeof retrievalPreviewCitationsSchema>[number]
