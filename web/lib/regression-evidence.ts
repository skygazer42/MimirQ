import { z } from 'zod'

import { recordSchema } from '@/lib/response-schema'
import { evidenceCitationSchema } from '@/lib/evidence-citations'
import { regressionReferenceSourceSchema, type RegressionReferenceSource } from '@/lib/regression-case-schema'

const regressionEvidenceCitationSchema = evidenceCitationSchema.extend({
  document_id: z.string().min(1),
  chunk_id: z.string().min(1),
  chunk_index: regressionReferenceSourceSchema.shape.chunk_index,
  page_number: regressionReferenceSourceSchema.shape.page_number,
  start_char: regressionReferenceSourceSchema.shape.start_char,
  end_char: regressionReferenceSourceSchema.shape.end_char,
  doc_pipeline_key: regressionReferenceSourceSchema.shape.doc_pipeline_key,
  pipeline_hash: regressionReferenceSourceSchema.shape.pipeline_hash,
  family_collapse_key: regressionReferenceSourceSchema.shape.family_collapse_key,
  hierarchy_family_key: regressionReferenceSourceSchema.shape.hierarchy_family_key,
  semantic_keys: regressionReferenceSourceSchema.shape.semantic_keys,
  metadata: z
    .looseObject({
      _record_identity: recordSchema.optional(),
      semantic_keys: regressionReferenceSourceSchema.shape.semantic_keys,
    })
    .nullish(),
})

const regressionEvidencePackSchema = z.looseObject({
  dataset_id: z.string().min(1).nullish(),
  query: z.string().optional(),
  query_for_retrieval: z.string().nullish(),
  metrics: recordSchema.nullish(),
  citations: z.array(regressionEvidenceCitationSchema).min(1),
  exported_at: z.string().optional(),
  has_evidence: z.boolean().nullish(),
  abstain_triggered: z.boolean().nullish(),
  abstain_reason: z.string().nullish(),
  selected_chunk_ids: z.array(z.string()).optional(),
})

export type RegressionEvidencePack = z.infer<typeof regressionEvidencePackSchema>

export function parseRegressionEvidencePack(value: unknown): RegressionEvidencePack {
  const pack = regressionEvidencePackSchema.parse(value)
  const chunkIds = new Set(pack.citations.map((citation) => citation.chunk_id))
  if (chunkIds.size !== pack.citations.length) throw new Error('证据包包含重复的切片标识')
  if (pack.selected_chunk_ids?.some((chunkId) => !chunkIds.has(chunkId))) {
    throw new Error('证据包的已选切片不在引用列表中')
  }
  return pack
}

export function buildRegressionReferenceSources(
  pack: RegressionEvidencePack,
  selectedChunkIds: ReadonlySet<string>,
  source: 'retrieve_preview' | 'evidence_pack',
): RegressionReferenceSource[] {
  const references = pack.citations
    .filter((citation) => selectedChunkIds.has(citation.chunk_id))
    .map((citation) => {
      const recordIdentity = citation.metadata?._record_identity
      const semanticKeys = new Set(citation.semantic_keys)
      if (citation.metadata?.semantic_keys !== undefined) {
        for (const key of citation.metadata.semantic_keys) semanticKeys.add(key)
      }
      return regressionReferenceSourceSchema.parse({
        document_id: citation.document_id,
        chunk_id: citation.chunk_id,
        chunk_index: citation.chunk_index,
        page_number: citation.page_number,
        start_char: citation.start_char,
        end_char: citation.end_char,
        doc_pipeline_key: citation.doc_pipeline_key,
        pipeline_hash: citation.pipeline_hash,
        family_collapse_key: citation.family_collapse_key,
        hierarchy_family_key: citation.hierarchy_family_key,
        record_identity: recordIdentity === undefined ? citation.record_identity : recordIdentity,
        semantic_keys: [...semanticKeys],
        quote:
          typeof citation.chunk_content === 'string'
            ? Array.from(citation.chunk_content).slice(0, 2000).join('')
            : citation.chunk_content,
        label: source === 'retrieve_preview' ? 'ground_truth' : 'evidence_pack',
      })
    })
  if (references.length !== selectedChunkIds.size) throw new Error('所选切片不在当前引用中')
  return references
}
