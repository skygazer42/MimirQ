import type { Document } from '@/types'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient } from '@/lib/api/core'

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

    const { data } = await apiClient.post(`/parsing/documents/${documentId}/parse`, null, {
      timeout: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
      params: Object.keys(params).length ? params : undefined,
    })
    return data
  },

  async getContent(documentId: string): Promise<ParsingContentResponse> {
    const { data } = await apiClient.get(`/parsing/documents/${documentId}/content`)
    return data
  },

  async updateContent(documentId: string, payload: ParsingContentUpdateRequest): Promise<ParsingContentResponse> {
    const { data } = await apiClient.patch(`/parsing/documents/${documentId}/content`, payload)
    return data
  },

  async delete(documentId: string): Promise<void> {
    await apiClient.delete(`/parsing/documents/${documentId}`)
  },
}
