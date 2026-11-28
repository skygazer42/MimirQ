import { z } from 'zod'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { integerSchema, recordSchema } from '@/lib/response-schema'
import { parseApiResponse } from '@/lib/openapi-request'

const chunkLineageSchema = z.looseObject({
  schema: z.string(),
  chunk: recordSchema,
  document: recordSchema,
  connector: recordSchema,
  acl: recordSchema,
  pipeline: recordSchema,
  retrieval_usage: recordSchema,
})
const answerLineageSchema = z
  .looseObject({
    schema: z.string(),
    request_id: z.string().nullable(),
    conversation_id: z.string().nullable(),
    ts_ms: integerSchema.nullable(),
    retrieval: recordSchema,
    citations_count: integerSchema,
    documents: z.array(recordSchema),
    chunks: z.array(recordSchema),
  })
  .refine((lineage) => lineage.citations_count === lineage.chunks.length, {
    message: 'Invalid answer lineage citation count',
    path: ['citations_count'],
  })

type ChunkLineage = z.output<typeof chunkLineageSchema>
type AnswerLineage = z.output<typeof answerLineageSchema>

export const lineageApi = {
  async getChunkLineage(chunkId: string, options?: ApiRequestOptions): Promise<ChunkLineage> {
    const response = await apiClient.get<unknown>(`/lineage/chunk/${encodeURIComponent(chunkId)}`, {
      signal: options?.signal,
    })
    return parseApiResponse(response, chunkLineageSchema, 'ChunkLineage')
  },

  async getAnswerLineageIfAvailable(requestId: string, options?: ApiRequestOptions): Promise<AnswerLineage | null> {
    const response = await apiClient.get<unknown>(`/lineage/answer/${encodeURIComponent(requestId)}`, {
      signal: options?.signal,
      validateStatus: (status) => (status >= 200 && status < 300) || status === 404,
    })
    if (response.status === 404) return null
    return parseApiResponse(response, answerLineageSchema, 'AnswerLineage')
  },
}
