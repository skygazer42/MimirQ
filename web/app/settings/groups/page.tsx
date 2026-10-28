'use client'

import {TenantPermissionGate} from '@/components/auth/tenant-permission-gate'
import {TENANT_PERMISSIONS} from '@/lib/tenant-permissions'
import GroupWorkspace from './group-workspace'

export default function SettingsGroupsPage() {
  return <TenantPermissionGate permission={TENANT_PERMISSIONS.SETTINGS_READ} pageName="组管理"><GroupWorkspace/></TenantPermissionGate>
}
