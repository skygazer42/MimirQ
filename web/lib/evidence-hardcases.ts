import { z } from 'zod'

const hardcaseCandidateSchema = z.looseObject({
  question_hash: z.string().min(1),
  cluster_size: z.number(),
  feedback_ids: z.array(z.string().min(1)),
  request_ids: z.array(z.string().min(1)),
  retrieval_config_hash: z.string().nullish(),
  citations_count: z.number().nullish(),
  retrieval_error_kinds: z.record(z.string(), z.number()),
  rag_config_template: z
    .looseObject({
      template_key: z.string().nullish(),
      version: z.number().nullish(),
      patch_hash: z.string().nullish(),
    })
    .nullish(),
})

const hardcaseDiscoverySchema = z.looseObject({
  generated_at: z.string(),
  enabled: z.boolean(),
  window_minutes: z.number(),
  max_bytes: z.number(),
  truncated: z.boolean(),
  feedback_scanned: z.number(),
  trace_index_size: z.number(),
  candidates: z.array(hardcaseCandidateSchema),
})

export type HardcaseDiscovery = z.infer<typeof hardcaseDiscoverySchema>
export type HardcaseSnapshot = Readonly<{
  data: HardcaseDiscovery
  maxRating: number
  includeExisting: boolean
  maxCandidates: number
}>

export function parseHardcaseDiscovery(value: unknown): HardcaseDiscovery {
  return hardcaseDiscoverySchema.parse(value)
}
