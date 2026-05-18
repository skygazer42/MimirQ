import type { TenantAccess } from '@/lib/tenant-permissions'

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
  const raw = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(',')
      : []
  const requested = new Set(raw.map((item) => String(item || '').trim()).filter(Boolean))

  return ADMIN_CONTROLLED_NAVIGATION_MODULES.filter((module) => requested.has(module))
}

export function tenantAccessIsAdmin(access: TenantAccess | null | undefined): boolean {
  if (!access?.is_active) return false
  const role = String(access.role || '').trim().toLowerCase()
  return ADMIN_ROLES.has(role) || (access.permissions || []).includes('settings.read')
}

export function canShowAdminControlledNavigationModule(
  access: TenantAccess | null | undefined,
  moduleKey?: AdminControlledNavigationModule
): boolean {
  if (!moduleKey) return true
  if (!ADMIN_CONTROLLED_NAVIGATION_MODULE_SET.has(moduleKey)) return false
  if (tenantAccessIsAdmin(access)) return true
  return normalizeNavigationModules(access?.navigation_user_visible_modules).includes(moduleKey)
}
