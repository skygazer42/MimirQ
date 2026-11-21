import { z } from 'zod'

export const evidenceCitationSchema = z.looseObject({
  document_id: z.string().nullish(),
  document_name: z.string().nullish(),
  chunk_id: z.string().nullish(),
  chunk_content: z.string().nullish(),
  page_number: z.number().nullish(),
  chunk_index: z.number().nullish(),
  start_char: z.number().nullish(),
  end_char: z.number().nullish(),
  evidence_start_char: z.number().nullish(),
  evidence_end_char: z.number().nullish(),
  header_path: z.string().nullish(),
  doc_pipeline_key: z.string().nullish(),
  pipeline_hash: z.string().nullish(),
  family_collapse_key: z.string().nullish(),
  hierarchy_family_key: z.string().nullish(),
  record_identity: z.record(z.string(), z.unknown()).nullish(),
  semantic_keys: z.array(z.string()).nullish(),
  hit_type: z.string().nullish(),
  has_image: z.boolean().nullish(),
  img_url: z.string().nullish(),
  matched_terms: z.array(z.string()).nullish(),
  retrieval_score: z.number().nullish(),
  rerank_score: z.number().nullish(),
  relevance_score: z.number().nullish(),
  vector_score: z.number().nullish(),
  bm25_score: z.number().nullish(),
  keyword_score: z.number().nullish(),
})

export type EvidenceCitation = z.infer<typeof evidenceCitationSchema>

export function parseEvidenceCitations(value: unknown): EvidenceCitation[] {
  return z.array(evidenceCitationSchema).parse(value)
}

export function getEvidenceScore(citation: EvidenceCitation): number | null | undefined {
  return (
    citation.retrieval_score ??
    citation.rerank_score ??
    citation.relevance_score ??
    citation.vector_score ??
    citation.bm25_score
  )
}

export function formatEvidenceScore(citation: EvidenceCitation): string {
  const score = getEvidenceScore(citation)
  return score === undefined || score === null ? '未提供' : score.toFixed(4)
}
