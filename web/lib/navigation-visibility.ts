import { TENANT_PERMISSIONS, tenantAccessAllows, type TenantAccess } from '@/lib/tenant-permissions'

export const ADMIN_CONTROLLED_NAVIGATION_MODULES = [
  'governanceProfiles',
  'commonLines',
  'knowledgeGraph',
  'graphSnapshots',
  'graphDiagnostics',
  'ragas',
  'ablations',
  'reports',
  'prompts',
] as const

export type AdminControlledNavigationModule = (typeof ADMIN_CONTROLLED_NAVIGATION_MODULES)[number]

const ADMIN_CONTROLLED_NAVIGATION_MODULE_SET = new Set<string>(ADMIN_CONTROLLED_NAVIGATION_MODULES)
const ADMIN_ROLES = new Set(['owner', 'admin'])

export function normalizeNavigationModules(value: unknown): AdminControlledNavigationModule[] {
  const modules = typeof value === 'string' ? value.split(',') : value
  if (!Array.isArray(modules)) return []

  const requested = new Set<string>()
  for (const item of modules) {
    if (typeof item === 'string') requested.add(item.trim())
  }
  return ADMIN_CONTROLLED_NAVIGATION_MODULES.filter((module) => requested.has(module))
}

export function tenantAccessIsAdmin(access: TenantAccess | null | undefined): boolean {
  if (access?.is_active !== true) return false
  const role = access.role.trim().toLowerCase()
  return ADMIN_ROLES.has(role) || tenantAccessAllows(access, TENANT_PERMISSIONS.SETTINGS_READ)
}

export function canShowAdminControlledNavigationModule(
  access: TenantAccess | null | undefined,
  moduleKey?: AdminControlledNavigationModule,
): boolean {
  if (!moduleKey) return true
  if (!ADMIN_CONTROLLED_NAVIGATION_MODULE_SET.has(moduleKey)) return false
  if (tenantAccessIsAdmin(access)) return true
  return normalizeNavigationModules(access?.navigation_user_visible_modules).includes(moduleKey)
}
