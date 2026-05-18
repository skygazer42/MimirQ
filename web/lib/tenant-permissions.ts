export const TENANT_PERMISSIONS = {
  SETTINGS_READ: 'settings.read',
  SETTINGS_WRITE: 'settings.write',
  OBSERVABILITY_READ: 'observability.read',
  USAGE_READ: 'usage.read',
  AUDIT_READ: 'audit.read',
  AUDIT_MANAGE: 'audit.manage',
  TABLE_SQL_READ: 'table_sql.read',
  LIFECYCLE_MANAGE: 'lifecycle.manage',
} as const

export type TenantPermission = (typeof TENANT_PERMISSIONS)[keyof typeof TENANT_PERMISSIONS]

export type TenantAccess = {
  tenant_id: string
  account_id: string
  role: string
  permissions: string[]
  navigation_user_visible_modules?: string[]
  is_active: boolean
  is_current: boolean
}

export function tenantAccessAllows(access: TenantAccess | null | undefined, permission: TenantPermission): boolean {
  if (!access?.is_active) return false
  return new Set(access.permissions || []).has(permission)
}
