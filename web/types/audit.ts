export type AuditLogFilters = {
  actor_id?: string
  action?: string
  resource_type?: string
  resource_id?: string
  request_id?: string
  since?: string
  until?: string
}

export type AuditLogQuery = AuditLogFilters & { skip?: number; limit?: number }

export type AuditLogItem = {
  id: string
  tenant_id: string
  actor_id: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  request_id: string | null
  ip: string | null
  user_agent: string | null
  details: Record<string, unknown>
  created_at: string
}

export type AuditLogListResponse = {
  total: number
  items: AuditLogItem[]
}
