'use client'

import { LockKeyhole, Loader2, RefreshCw, ShieldAlert } from '@/components/icons'
import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/ui/page-loading'
import { PageStatus, pageStatusActionClass } from '@/components/ui/page-status'
import { useAuth } from '@/hooks/use-auth'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { tenantAccessAllows, type TenantPermission } from '@/lib/tenant-permissions'

type TenantPermissionGateProps = {
  permission: TenantPermission
  pageName: string
  children: ReactNode
}

export function TenantPermissionGate({ permission, pageName, children }: Readonly<TenantPermissionGateProps>) {
  const [hasHydrated, setHasHydrated] = useState(false)
  const { isDevMode } = useAuth()
  const access = useTenantAccess()
  const allowed = hasHydrated && (isDevMode || tenantAccessAllows(access.data, permission))
  async function recheckAccess() {
    toast.dismiss('tenant-access-recheck')
    const result = await access.refetch()
    if (result.isSuccess && !tenantAccessAllows(result.data, permission)) {
      toast.info('校验完成，当前账号仍无法访问此页面。', { id: 'tenant-access-recheck', duration: 3200 })
    }
  }

  useEffect(() => {
    setHasHydrated(true)
  }, [])

  if (!hasHydrated || (!isDevMode && access.isLoading)) {
    return (
      <AppFrame>
        <PageLoading
          className="min-h-full bg-transparent"
          message="正在校验页面权限..."
          srMessage={`正在校验${pageName}访问权限`}
        />
      </AppFrame>
    )
  }

  if (!allowed) {
    const isUnknown = access.isError || !access.data
    return (
      <AppFrame>
        <PageStatus
          title={isUnknown ? '无法确认权限' : '无权限访问'}
          description={
            isUnknown
              ? '暂时无法读取账号权限，请检查登录状态或服务连接后重试。'
              : `当前账号没有访问「${pageName}」的权限。如需使用，请联系管理员。`
          }
          icon={isUnknown ? <ShieldAlert /> : <LockKeyhole />}
          actions={<Button variant="outline" className={pageStatusActionClass} disabled={access.isFetching} aria-busy={access.isFetching} onClick={() => { void recheckAccess() }}>{access.isFetching ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="size-4" />}重新校验</Button>}
          metadata={<details><summary className="cursor-pointer py-1 text-[13px]">权限信息</summary><dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1"><dt>需要权限</dt><dd className="break-all font-mono text-foreground">{permission}</dd><dt>最近读取的角色</dt><dd className="break-all text-foreground">{access.data?.role || '未读取'}</dd></dl></details>}
        />
      </AppFrame>
    )
  }

  return <>{children}</>
}
