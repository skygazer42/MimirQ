'use client'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import GroupWorkspace from './group-workspace'
import { useAccessAdminSession } from '../use-access-admin-session'

export default function SettingsGroupsPage() {
  const session = useAccessAdminSession()
  return (
    <TenantPermissionGate permission={TENANT_PERMISSIONS.SETTINGS_READ} pageName="组管理">
      <GroupWorkspace key={session} />
    </TenantPermissionGate>
  )
}
