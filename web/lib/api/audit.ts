import type { AuditLogListResponse } from '@/types'
import type { OpenApiSchema } from '@/types/backend'

import { apiClient } from '@/lib/api/core'
import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'

export type AuditLogPurgeResponse = OpenApiSchema<'AuditLogPurgeResponse'>
export type AuditLogDeleteResponse = OpenApiSchema<'AuditLogDeleteResponse'>

const AUDIT_BULK_DELETE_CHUNK_SIZE = 500

function mergeAuditDeleteResponses(responses: AuditLogDeleteResponse[]): AuditLogDeleteResponse {
  return responses.reduce<AuditLogDeleteResponse>(
    (acc, item) => ({
      requested: acc.requested + Number(item.requested || 0),
      deleted: acc.deleted + Number(item.deleted || 0),
      missing: acc.missing + Number(item.missing || 0),
      ids: [...acc.ids, ...(Array.isArray(item.ids) ? item.ids : [])],
    }),
    { requested: 0, deleted: 0, missing: 0, ids: [] }
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

export const auditApi = {
  async listLogs(params: {
    skip?: number
    limit?: number
    actor_id?: string
    action?: string
    resource_type?: string
    resource_id?: string
    request_id?: string
    since?: string
    until?: string
  } = {}): Promise<AuditLogListResponse> {
    const { data } = await apiClient.get('/audit/logs', { params })
    return data
  },

  async exportLogs(params: {
    limit?: number
    actor_id?: string
    action?: string
    resource_type?: string
    resource_id?: string
    request_id?: string
    since?: string
    until?: string
    after_created_at?: string
    after_id?: string
    include_sensitive?: boolean
    gzip?: boolean
  } = {}): Promise<Blob> {
    const { data } = await apiClient.get('/audit/logs/export', { params, responseType: 'blob' })
    return data as Blob
  },

  async purgeLogs(params: {
    retention_days?: number
    max_delete?: number
    dry_run?: boolean
    purge_scope?: 'retention' | 'filtered'
    actor_id?: string
    action?: string
    resource_type?: string
    resource_id?: string
    request_id?: string
    since?: string
    until?: string
  } = {}): Promise<AuditLogPurgeResponse> {
    const { data } = await apiClient.post('/audit/logs/purge', undefined, { params })
    return data
  },

  async deleteLog(logId: string): Promise<AuditLogDeleteResponse> {
    const { data } = await apiClient.delete(`/audit/logs/${encodeURIComponent(logId)}`)
    return data
  },

  async bulkDeleteLogs(ids: string[]): Promise<AuditLogDeleteResponse> {
    const chunks: string[][] = []
    for (let index = 0; index < ids.length; index += AUDIT_BULK_DELETE_CHUNK_SIZE) {
      chunks.push(ids.slice(index, index + AUDIT_BULK_DELETE_CHUNK_SIZE))
    }

    const responses: AuditLogDeleteResponse[] = []
    for (const chunk of chunks) {
      const { data } = await apiClient.post(
        '/audit/logs/bulk-delete',
        { ids: chunk },
        { timeout: API_LONG_TIMEOUT_MS }
      )
      responses.push(data)
    }
    return mergeAuditDeleteResponses(responses)
  },

  async exportAccessGraph(params: {
    limit?: number
    after_kind?: string
    after_created_at?: string
    after_id?: string
    include_sensitive?: boolean
    export_format?: 'ndjson' | 'json'
    gzip?: boolean
  } = {}): Promise<Blob> {
    const { data } = await apiClient.get('/audit/access-graph/export', { params, responseType: 'blob' })
    return data as Blob
  },

  async exportAccessGraphPage(params: {
    limit?: number
    after_kind?: string
    after_created_at?: string
    after_id?: string
    include_sensitive?: boolean
    export_format?: 'ndjson' | 'json'
    gzip?: boolean
  } = {}): Promise<{
    blob: Blob
    nextCursor: { after_kind: string; after_created_at: string; after_id: string } | null
  }> {
    const resp = await apiClient.get('/audit/access-graph/export', { params, responseType: 'blob' })
    const headers = isRecord(resp.headers) ? resp.headers : {}
    const raw = headers['x-next-cursor'] || headers['X-Next-Cursor'] || ''
    const rawCursor = toTrimmedPrimitiveString(raw)
    let nextCursor: { after_kind: string; after_created_at: string; after_id: string } | null = null

    if (rawCursor) {
      try {
        const obj = JSON.parse(rawCursor) as unknown
        if (isRecord(obj)) {
          const afterKind = toTrimmedPrimitiveString(obj.after_kind)
          const afterCreatedAt = toTrimmedPrimitiveString(obj.after_created_at)
          const afterId = toTrimmedPrimitiveString(obj.after_id)
          if (afterKind && afterCreatedAt && afterId) {
            nextCursor = {
              after_kind: afterKind,
              after_created_at: afterCreatedAt,
              after_id: afterId,
            }
          }
        }
      } catch {
        // Ignore cursor parse errors; callers can treat it as "no more pages".
      }
    }

    return { blob: resp.data as Blob, nextCursor }
  },

  async getAccessGraphSummary(): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/audit/access-graph/summary')
    return data
  },
}
