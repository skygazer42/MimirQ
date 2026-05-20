import type { AuditLogListResponse } from '@/types'

import { apiClient } from '@/lib/api/core'
import { API_LONG_TIMEOUT_MS } from '@/lib/env'

export type AuditLogDeleteResponse = {
  requested: number
  deleted: number
  missing: number
  ids: string[]
}

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
  } = {}): Promise<any> {
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
    const headers: Record<string, any> = (resp as any)?.headers || {}
    const raw = headers['x-next-cursor'] || headers['X-Next-Cursor'] || ''
    let nextCursor: { after_kind: string; after_created_at: string; after_id: string } | null = null

    if (raw) {
      try {
        const obj = JSON.parse(String(raw))
        if (obj && typeof obj === 'object' && obj.after_kind && obj.after_created_at && obj.after_id) {
          nextCursor = {
            after_kind: String(obj.after_kind),
            after_created_at: String(obj.after_created_at),
            after_id: String(obj.after_id),
          }
        }
      } catch {
        // Ignore cursor parse errors; callers can treat it as "no more pages".
      }
    }

    return { blob: resp.data as Blob, nextCursor }
  },

  async getAccessGraphSummary(): Promise<any> {
    const { data } = await apiClient.get('/audit/access-graph/summary')
    return data
  },
}
