import { z } from 'zod'
import type { AxiosResponse } from 'axios'

import type { AuditLogFilters, AuditLogListResponse, AuditLogQuery } from '@/types/audit'
import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { dateTimeSchema, recordSchema } from '@/lib/response-schema'
import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { parseApiResponse } from '@/lib/openapi-request'

const auditLogSchema = z.looseObject({
  id: z.string().min(1),
  tenant_id: z.string(),
  actor_id: z.string().nullable(),
  action: z.string(),
  resource_type: z.string().nullable(),
  resource_id: z.string().nullable(),
  request_id: z.string().nullable(),
  ip: z.string().nullable(),
  user_agent: z.string().nullable(),
  details: recordSchema,
  created_at: dateTimeSchema,
})
const auditLogListSchema: z.ZodType<AuditLogListResponse> = z.looseObject({
  total: z.number().int().nonnegative(),
  items: z.array(auditLogSchema),
})
const auditLogDeleteSchema = z
  .looseObject({
    requested: z.number().int().nonnegative(),
    deleted: z.number().int().nonnegative(),
    missing: z.number().int().nonnegative(),
    ids: z.array(z.string()),
  })
  .refine((result) => result.deleted + result.missing === result.requested && result.ids.length === result.requested, {
    message: 'Invalid audit log deletion receipt',
  })
const auditLogPurgeSchema = z.looseObject({
  dry_run: z.boolean(),
  scope: z.enum(['retention', 'filtered']),
  retention_days: z.number().int(),
  cutoff: dateTimeSchema,
  max_delete: z.number().int(),
  eligible: z.number().int().nonnegative(),
  deleted: z.number().int().nonnegative(),
  filters: recordSchema,
})

export type AuditLogDeleteResponse = z.infer<typeof auditLogDeleteSchema>
export type AuditLogPurgeResponse = z.infer<typeof auditLogPurgeSchema>
export type AuditPurgeParameters = { max_delete: number; dry_run: boolean } & (
  { purge_scope: 'retention'; retention_days: number } | (AuditLogFilters & { purge_scope: 'filtered' })
)

function parseAuditLogDeleteResponse(response: AxiosResponse<unknown>, ids: readonly string[]): AuditLogDeleteResponse {
  const receipt = parseApiResponse(response, auditLogDeleteSchema, 'AuditLogDelete')
  const requestedIds = new Set(ids)
  const confirmedIds = new Set(receipt.ids)
  if (
    receipt.requested !== requestedIds.size ||
    confirmedIds.size !== requestedIds.size ||
    receipt.ids.some((id) => !requestedIds.has(id))
  ) {
    throw new Error('删除回执的日志 ID 与本次选择不匹配，请重新读取列表核对')
  }
  return receipt
}

export const auditApi = {
  async listLogs(params: AuditLogQuery = {}, options: ApiRequestOptions = {}): Promise<AuditLogListResponse> {
    const response = await apiClient.get<unknown>('/audit/logs', { params, signal: options.signal })
    return parseApiResponse(response, auditLogListSchema, 'AuditLogList')
  },

  async exportLogs(
    params: AuditLogFilters & { limit?: number; include_sensitive?: boolean; gzip?: boolean } = {},
    options: ApiRequestOptions = {},
  ): Promise<Blob> {
    const response = await apiClient.get<Blob>('/audit/logs/export', {
      params,
      signal: options.signal,
      responseType: 'blob',
    })
    if (response.data.type.split(';', 1)[0].trim() !== 'application/x-ndjson') {
      throw new Error('审计导出响应不是有效的 NDJSON 文件')
    }
    return response.data
  },

  async purgeLogs(params: AuditPurgeParameters): Promise<AuditLogPurgeResponse> {
    const response = await apiClient.post<unknown>('/audit/logs/purge', undefined, {
      params,
      timeout: API_LONG_TIMEOUT_MS,
    })
    const receipt = parseApiResponse(response, auditLogPurgeSchema, 'AuditLogPurge')
    if (
      receipt.dry_run !== params.dry_run ||
      receipt.scope !== params.purge_scope ||
      receipt.max_delete !== params.max_delete ||
      receipt.deleted > params.max_delete ||
      (params.dry_run && receipt.deleted !== 0) ||
      (params.purge_scope === 'retention' && receipt.retention_days !== params.retention_days)
    ) {
      throw new Error('清理回执与本次提交的模式或范围不匹配，请重新读取列表核对')
    }
    return receipt
  },

  async deleteLog(logId: string): Promise<AuditLogDeleteResponse> {
    const response = await apiClient.delete<unknown>(`/audit/logs/${encodeURIComponent(logId)}`, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return parseAuditLogDeleteResponse(response, [logId])
  },

  async bulkDeleteLogs(ids: string[]): Promise<AuditLogDeleteResponse> {
    const response = await apiClient.post<unknown>('/audit/logs/bulk-delete', { ids }, { timeout: API_LONG_TIMEOUT_MS })
    return parseAuditLogDeleteResponse(response, ids)
  },
}
