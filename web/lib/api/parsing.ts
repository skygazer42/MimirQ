import type { Document, OpenApiSchema } from '@/types/backend'
import { z } from 'zod'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest, type ApiRequestOptions } from '@/lib/api/core'

export type ParsingElement = OpenApiSchema<'ParsingElementOut'>

export type ParsingExtractFieldSpec = OpenApiSchema<'ParsingExtractFieldSpec'>
export type ParsingExtractRequest = OpenApiSchema<'ParsingExtractRequest'>

export type ParsingExtractEvidence = OpenApiSchema<'ParsingExtractEvidence'>

type ParsingDocumentListParams = {
  skip?: number
  limit?: number
  status?: string
  dataset_id?: string
}

type ParsingDocumentListResponse = {
  total: number
  items: Document[]
}

export type ParsingContentUpdateRequest = OpenApiSchema<'ParsingContentUpdateRequest'>

const parsingContentStatsSchema = z
  .object({
    page_count: z.number().int().optional(),
    table_count: z.number().int().optional(),
    image_count: z.number().int().optional(),
    block_count: z.number().int().optional(),
  })
  .catchall(z.number().int())

export const parsingPdfQualitySchema = z
  .object({
    score: z.number(),
    text_quality_score: z.number(),
    format_consistency_score: z.number(),
    table_quality_score: z.number(),
    reading_order_score: z.number().nullable().optional(),
    is_scanned: z.boolean(),
    page_count: z.number().int(),
  })
  .nullable()
  .optional()

export const parsingQualityGateSchema = z
  .object({
    grade: z.enum(['pass', 'warn', 'fail']),
    reasons: z.array(z.string()),
    evidence: z.record(z.string(), z.unknown()).optional(),
  })
  .nullable()
  .optional()

const parsingElementKindSchema = z.enum([
  'heading',
  'paragraph',
  'list',
  'table',
  'image',
  'equation',
  'seal',
  'unknown',
])

const parsingElementSchema = z.looseObject({
  id: z.string(),
  kind: parsingElementKindSchema,
  page: z.number().int().nullable().optional(),
  pages: z.array(z.number().int()).nullable().optional(),
  visual_kind: z.string().nullable().optional(),
  text: z.string().nullable().optional(),
  confidence: z.number().nullable().optional(),
  source_backend: z.string().nullable().optional(),
  source_element_id: z.string().nullable().optional(),
  bbox: z
    .object({
      x0: z.number().int(),
      y0: z.number().int(),
      x1: z.number().int(),
      y1: z.number().int(),
    })
    .nullable()
    .optional(),
  attributes: z.record(z.string(), z.unknown()).nullable().optional(),
})

const parsingExtractEvidenceSchema = z.looseObject({
  element_id: z.string().nullable().optional(),
  kind: parsingElementKindSchema.nullable().optional(),
  page: z.number().int().nullable().optional(),
  pages: z.array(z.number().int()).nullable().optional(),
  visual_kind: z.string().nullable().optional(),
  bbox: z
    .object({
      x0: z.number().int(),
      y0: z.number().int(),
      x1: z.number().int(),
      y1: z.number().int(),
    })
    .nullable()
    .optional(),
  text: z.string().nullable().optional(),
  score: z.number().nullable().optional(),
})

const parsingExtractFieldResultSchema = z.looseObject({
  value: z.string().nullable().optional(),
  confidence: z.number().nullable().optional(),
  evidence: z.array(parsingExtractEvidenceSchema),
  strategy: z.string().nullable().optional(),
})

const parsingExtractResultsSchema = z
  .preprocess(
    (value) => {
      if (typeof value !== 'object' || value === null) return z.NEVER
      const prototype = Object.getPrototypeOf(value)
      if (prototype !== Object.prototype && prototype !== null) return z.NEVER
      return new Map(Object.entries(value))
    },
    z.map(z.string(), parsingExtractFieldResultSchema, { error: '抽取结果必须是字段对象' }),
  )
  .transform((fields) => Object.fromEntries(fields))

const parsingExtractResponseSchema = z.looseObject({
  document_id: z.string(),
  mode: z.enum(['schema', 'prompt']),
  result: parsingExtractResultsSchema,
})

const parsingContentResponseSchema = z.looseObject({
  document_id: z.string(),
  parser_backend: z.string(),
  markdown_content: z.string(),
  original_markdown_content: z.string(),
  stats: parsingContentStatsSchema.nullable().optional(),
  parse_duration_sec: z.number().nullable().optional(),
  pdf_quality: parsingPdfQualitySchema,
  quality_gate: parsingQualityGateSchema,
  elements: z.array(parsingElementSchema).nullable().optional(),
  edited: z.boolean(),
})

export type ParsingExtractFieldResult = z.output<typeof parsingExtractFieldResultSchema>
export type ParsingExtractResponse = z.output<typeof parsingExtractResponseSchema>
export type ParsingContentResponse = z.output<typeof parsingContentResponseSchema>

export const parsingApi = {
  async listDocuments(
    params?: ParsingDocumentListParams,
    options?: ApiRequestOptions,
  ): Promise<ParsingDocumentListResponse> {
    const { data } = await apiClient.get('/parsing/documents', { params, signal: options?.signal })
    return data
  },

  async upload(file: File, options?: { parser_backend?: string; dataset_id?: string | null }): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    if (options?.parser_backend) formData.append('parser_backend', options.parser_backend)
    if (options?.dataset_id) formData.append('dataset_id', options.dataset_id)
    const { data } = await apiClient.post('/parsing/documents', formData)
    return data
  },

  async parse(
    documentId: string,
    options?: {
      parser_backend?: string
      image_caption_enabled?: boolean
      image_ocr_enabled?: boolean
      vlm_correction_enabled?: boolean
      signal?: AbortSignal
    },
  ): Promise<ParsingContentResponse> {
    const params: {
      parser_backend?: string
      image_caption_enabled?: boolean
      image_ocr_enabled?: boolean
      vlm_correction_enabled?: boolean
    } = {}
    if (options?.parser_backend) params.parser_backend = options.parser_backend
    if (typeof options?.image_caption_enabled === 'boolean') {
      params.image_caption_enabled = options.image_caption_enabled
    }
    if (typeof options?.image_ocr_enabled === 'boolean') params.image_ocr_enabled = options.image_ocr_enabled
    if (typeof options?.vlm_correction_enabled === 'boolean') {
      params.vlm_correction_enabled = options.vlm_correction_enabled
    }

    const data = await openapiRequest({
      path: '/api/v1/parsing/documents/{document_id}/parse',
      method: 'post',
      pathParams: { document_id: documentId },
      query: Object.keys(params).length ? params : undefined,
      signal: options?.signal,
      timeoutMs: API_LONG_TIMEOUT_MS,
      responseSchema: parsingContentResponseSchema,
      responseSchemaName: 'ParsingContentResponse',
    })
    return data as ParsingContentResponse
  },

  async getContent(documentId: string, options?: ApiRequestOptions): Promise<ParsingContentResponse> {
    const data = await openapiRequest({
      path: '/api/v1/parsing/documents/{document_id}/content',
      method: 'get',
      pathParams: { document_id: documentId },
      responseSchema: parsingContentResponseSchema,
      responseSchemaName: 'ParsingContentResponse',
      signal: options?.signal,
    })
    return data as ParsingContentResponse
  },

  async updateContent(documentId: string, payload: ParsingContentUpdateRequest): Promise<ParsingContentResponse> {
    const data = await openapiRequest({
      path: '/api/v1/parsing/documents/{document_id}/content',
      method: 'patch',
      pathParams: { document_id: documentId },
      body: payload,
      responseSchema: parsingContentResponseSchema,
      responseSchemaName: 'ParsingContentResponse',
    })
    return data as ParsingContentResponse
  },

  async extract(
    documentId: string,
    payload: ParsingExtractRequest,
    options?: ApiRequestOptions,
  ): Promise<ParsingExtractResponse> {
    const data = await openapiRequest({
      path: '/api/v1/parsing/documents/{document_id}/extract',
      method: 'post',
      pathParams: { document_id: documentId },
      body: payload,
      responseSchema: parsingExtractResponseSchema,
      responseSchemaName: 'ParsingExtractResponse',
      timeoutMs: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
    })
    return data as ParsingExtractResponse
  },

  async delete(documentId: string): Promise<void> {
    await apiClient.delete(`/parsing/documents/${documentId}`)
  },
}
