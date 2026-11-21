import { z } from 'zod'

import type { Citation } from '@/types/processing'

const optionalPositionSchema = z
  .number()
  .int()
  .nullish()
  .transform((value) => value ?? undefined)

const retrievalCitationSchema = z.object({
  document_id: z.string(),
  document_name: z.string(),
  chunk_content: z.string(),
  relevance_score: z.number(),
  chunk_id: z
    .string()
    .nullish()
    .transform((value) => value ?? undefined),
  matched_terms: z
    .array(z.string())
    .nullish()
    .transform((value) => value ?? undefined),
  page_number: optionalPositionSchema,
  chunk_index: optionalPositionSchema,
  start_char: optionalPositionSchema,
  end_char: optionalPositionSchema,
})

export function parseRetrievalCitation(value: unknown): Citation {
  return retrievalCitationSchema.parse(value)
}
