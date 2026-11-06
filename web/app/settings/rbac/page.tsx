'use client'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import MembersWorkspace from './members-workspace'
import { useAccessAdminSession } from '../use-access-admin-session'

export default function SettingsRbacPage() {
  const session = useAccessAdminSession()
  return (
    <TenantPermissionGate permission={TENANT_PERMISSIONS.SETTINGS_READ} pageName="成员权限">
      <MembersWorkspace key={session} />
    </TenantPermissionGate>
  )
}
