import type { Document } from '@/types'
import { z } from 'zod'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest } from '@/lib/api/core'

export interface ParsingElement {
  id: string
  kind: 'heading' | 'paragraph' | 'list' | 'table' | 'image' | 'equation' | 'seal' | 'unknown'
  page?: number | null
  pages?: number[] | null
  visual_kind?: string | null
  text?: string | null
  confidence?: number | null
  source_backend?: string | null
  source_element_id?: string | null
  bbox?: {
    x0: number
    y0: number
    x1: number
    y1: number
  } | null
  attributes?: Record<string, unknown> | null
}

export interface ParsingExtractFieldSpec {
  type?: 'string'
  source_kind?: string | null
  source_visual_kind?: string | null
  aliases?: string[]
}

export interface ParsingExtractRequest {
  mode?: 'schema' | 'prompt'
  schema?: Record<string, ParsingExtractFieldSpec> | null
  prompt?: string | null
  field_hints?: Record<string, ParsingExtractFieldSpec> | null
  max_evidence?: number
}

export interface ParsingExtractEvidence {
  element_id?: string | null
  kind?: ParsingElement['kind'] | null
  page?: number | null
  pages?: number[] | null
  visual_kind?: string | null
  bbox?: {
    x0: number
    y0: number
    x1: number
    y1: number
  } | null
  text?: string | null
  score?: number | null
}

export interface ParsingExtractFieldResult {
  value?: string | null
  confidence?: number | null
  evidence: ParsingExtractEvidence[]
  strategy?: string | null
}

export interface ParsingExtractResponse {
  document_id: string
  mode: 'schema' | 'prompt'
  result: Record<string, ParsingExtractFieldResult>
}

function normalizeExtractFieldSpecMap(
  value: Record<string, ParsingExtractFieldSpec> | null | undefined
): Record<string, { type: 'string'; source_kind?: string | null; aliases?: string[] }> | undefined {
  if (!value) return undefined
  const entries = Object.entries(value)
  if (entries.length === 0) return undefined
  const out: Record<string, { type: 'string'; source_kind?: string | null; source_visual_kind?: string | null; aliases?: string[] }> = {}
  for (const [key, spec] of entries) {
    out[key] = {
      type: 'string',
      source_kind: spec?.source_kind ?? undefined,
      source_visual_kind: spec?.source_visual_kind ?? undefined,
      aliases: spec?.aliases ?? undefined,
    }
  }
  return out
}

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
  elements?: ParsingElement[] | null
}

export interface ParsingContentUpdateRequest {
  markdown_content: string
  original_markdown_content?: string | null
}

const parsingContentStatsSchema = z.looseObject({
  page_count: z.number().int().optional(),
  table_count: z.number().int().optional(),
  image_count: z.number().int().optional(),
  block_count: z.number().int().optional(),
})

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

const parsingElementKindSchema = z.enum(['heading', 'paragraph', 'list', 'table', 'image', 'equation', 'seal', 'unknown'])

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

const parsingExtractFieldSpecSchema = z.looseObject({
  type: z.enum(['string']).optional(),
  source_kind: z.string().nullable().optional(),
  source_visual_kind: z.string().nullable().optional(),
  aliases: z.array(z.string()).optional(),
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

const parsingExtractResponseSchema = z.looseObject({
  document_id: z.string(),
  mode: z.enum(['schema', 'prompt']),
  result: z.record(z.string(), parsingExtractFieldResultSchema),
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
})

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
    options?: {
      parser_backend?: string
      image_caption_enabled?: boolean
      image_ocr_enabled?: boolean
      vlm_correction_enabled?: boolean
      signal?: AbortSignal
    }
  ): Promise<ParsingContentResponse> {
    const params: Record<string, any> = {}
    if (options?.parser_backend) params.parser_backend = options.parser_backend
    if (typeof options?.image_caption_enabled === 'boolean') params.image_caption_enabled = options.image_caption_enabled
    if (typeof options?.image_ocr_enabled === 'boolean') params.image_ocr_enabled = options.image_ocr_enabled
    if (typeof options?.vlm_correction_enabled === 'boolean') params.vlm_correction_enabled = options.vlm_correction_enabled

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

  async extract(documentId: string, payload: ParsingExtractRequest): Promise<ParsingExtractResponse> {
    const requestBody = {
      mode: payload.mode ?? 'schema',
      schema: normalizeExtractFieldSpecMap(payload.schema),
      prompt: payload.prompt ?? undefined,
      field_hints: normalizeExtractFieldSpecMap(payload.field_hints),
      max_evidence: payload.max_evidence ?? 1,
    }
    const data = await openapiRequest({
      path: '/api/v1/parsing/documents/{document_id}/extract',
      method: 'post',
      pathParams: { document_id: documentId },
      body: requestBody,
      responseSchema: parsingExtractResponseSchema as any,
      responseSchemaName: 'ParsingExtractResponse',
      timeoutMs: API_LONG_TIMEOUT_MS,
    })
    return data as ParsingExtractResponse
  },

  async delete(documentId: string): Promise<void> {
    await apiClient.delete(`/parsing/documents/${documentId}`)
  },
}
