import { z } from 'zod'

import type { ChatMessageMetadata } from '@/types/chat'
import type { OntologyActionProposal } from '@/types/enterprise-ontology'

export const ontologyActionProposalSchema: z.ZodType<OntologyActionProposal> = z.object({
  ontology_id: z.uuid(),
  version_id: z.uuid(),
  action_id: z.string(),
  label: z.string(),
  target: z.string(),
  approval_required: z.boolean(),
  key_fields: z.record(z.string(), z.string()),
  parameter_fields: z.record(z.string(), z.object({ label: z.string(), required: z.boolean() })),
  key: z.record(z.string(), z.string()),
  parameters: z.record(z.string(), z.union([z.string(), z.number(), z.boolean()])),
})

const claimEvidenceReferenceSchema = z.object({
  document_id: z.string().nullable(),
  chunk_id: z.string().nullable(),
  start_char: z.number().int().nullable(),
  end_char: z.number().int().nullable(),
  quote: z.string(),
  score: z.number(),
})

const claimEvidenceSchema = z.array(z.object({ claim: z.string(), evidence: z.array(claimEvidenceReferenceSchema) }))

const knownMetadataSchema: z.ZodType<ChatMessageMetadata> = z.looseObject({
  request_id: z.string().nullish(),
  confidence_score: z.number().min(0).max(1).nullish(),
  claim_evidence: claimEvidenceSchema.nullish(),
  sentence_citations: claimEvidenceSchema.nullish(),
  retrieved_docs: z.array(z.unknown()).nullish(),
  docs_returned: z.number().int().nonnegative().nullish(),
  followup_questions: z.array(z.string()).nullish(),
  dataset_id: z.string().nullish(),
  send_state: z.enum(['sending', 'accepted', 'unconfirmed']).optional(),
})

// Validate known fields while retaining the original diagnostic dictionary and nested values.
export const chatMessageMetadataSchema = z.custom<ChatMessageMetadata>(
  (value) => knownMetadataSchema.safeParse(value).success,
)
