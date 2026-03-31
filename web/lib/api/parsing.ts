import type { Document } from '@/types'
import { z } from 'zod'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest } from '@/lib/api/core'

export interface ParsingContentResponse {
  document_id: string
  parser_backend: string
  markdown_content: string
  original_markdown_content: string
  stats?: {
    page_count?: number
    table_count?: number
    image_count?: number
    block_count?: number
  } | null
  parse_duration_sec?: number | null
  pdf_quality?: {
    score: number
    text_quality_score: number
    format_consistency_score: number
    table_quality_score: number
    is_scanned: boolean
    page_count: number
  } | null
  quality_gate?: {
    grade: 'pass' | 'warn' | 'fail'
    reasons: string[]
    evidence?: Record<string, any>
  } | null
}

export interface ParsingContentUpdateRequest {
  markdown_content: string
  original_markdown_content?: string | null
}

const parsingContentStatsSchema = z
  .object({
    page_count: z.number().int().optional(),
    table_count: z.number().int().optional(),
    image_count: z.number().int().optional(),
    block_count: z.number().int().optional(),
  })
  .passthrough()

const parsingPdfQualitySchema = z
  .object({
    score: z.number(),
    text_quality_score: z.number(),
    format_consistency_score: z.number(),
    table_quality_score: z.number(),
    is_scanned: z.boolean(),
    page_count: z.number().int(),
  })
  .nullable()
  .optional()

const parsingQualityGateSchema = z
  .object({
    grade: z.enum(['pass', 'warn', 'fail']),
    reasons: z.array(z.string()),
    evidence: z.record(z.string(), z.unknown()).optional(),
  })
  .nullable()
  .optional()

const parsingContentResponseSchema = z
  .object({
    document_id: z.string(),
    parser_backend: z.string(),
    markdown_content: z.string(),
    original_markdown_content: z.string(),
    stats: parsingContentStatsSchema.nullable().optional(),
    parse_duration_sec: z.number().nullable().optional(),
    pdf_quality: parsingPdfQualitySchema,
    quality_gate: parsingQualityGateSchema,
  })
  .passthrough()

export const parsingApi = {
  async listDocuments(params?: { skip?: number; limit?: number; status?: string }): Promise<{ total: number; items: Document[] }> {
    const { data } = await apiClient.get('/parsing/documents', { params })
    return data
  },

  async upload(file: File, options?: { parser_backend?: string }): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', (options?.parser_backend || 'auto').toString())
    const { data } = await apiClient.post('/parsing/documents', formData)
    return data
  },

  async parse(
    documentId: string,
    options?: { parser_backend?: string; image_caption_enabled?: boolean; signal?: AbortSignal }
  ): Promise<ParsingContentResponse> {
    const params: Record<string, any> = {}
    if (options?.parser_backend) params.parser_backend = options.parser_backend
    if (options?.image_caption_enabled) params.image_caption_enabled = true

    const data = await openapiRequest({
      path: '/api/v1/parsing/documents/{document_id}/parse',
      method: 'post',
      pathParams: { document_id: documentId },
      query: Object.keys(params).length ? params : undefined,
      signal: options?.signal,
      timeoutMs: API_LONG_TIMEOUT_MS,
      responseSchema: parsingContentResponseSchema as any,
      responseSchemaName: 'ParsingContentResponse',
    })
    return data as ParsingContentResponse
  },

  async getContent(documentId: string): Promise<ParsingContentResponse> {
    const data = await openapiRequest({
      path: '/api/v1/parsing/documents/{document_id}/content',
      method: 'get',
      pathParams: { document_id: documentId },
      responseSchema: parsingContentResponseSchema as any,
      responseSchemaName: 'ParsingContentResponse',
    })
    return data as ParsingContentResponse
  },

  async updateContent(documentId: string, payload: ParsingContentUpdateRequest): Promise<ParsingContentResponse> {
    const data = await openapiRequest({
      path: '/api/v1/parsing/documents/{document_id}/content',
      method: 'patch',
      pathParams: { document_id: documentId },
      body: payload,
      responseSchema: parsingContentResponseSchema as any,
      responseSchemaName: 'ParsingContentResponse',
    })
    return data as ParsingContentResponse
  },

  async delete(documentId: string): Promise<void> {
    await apiClient.delete(`/parsing/documents/${documentId}`)
  },
}
