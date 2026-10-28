'use client'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import MembersWorkspace from './members-workspace'

export default function SettingsRbacPage() {
  return <TenantPermissionGate permission={TENANT_PERMISSIONS.SETTINGS_READ} pageName="成员权限"><MembersWorkspace /></TenantPermissionGate>
}
