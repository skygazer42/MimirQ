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
import {
  canShowAdminControlledNavigationModule,
  type AdminControlledNavigationModule,
} from '@/lib/navigation-visibility'

type NavigationVisibilityGateProps = {
  moduleKey: AdminControlledNavigationModule
  pageName: string
  children: ReactNode
}

export function NavigationVisibilityGate({
  moduleKey,
  pageName,
  children,
}: Readonly<NavigationVisibilityGateProps>) {
  const [hasHydrated, setHasHydrated] = useState(false)
  const { isDevMode } = useAuth()
  const access = useTenantAccess()
  const allowed = hasHydrated && canShowAdminControlledNavigationModule(access.data, moduleKey)
  const effectiveAllowed = hasHydrated && (isDevMode || allowed)
  async function recheckAccess() {
    toast.dismiss('navigation-access-recheck')
    const result = await access.refetch()
    if (result.isSuccess && !canShowAdminControlledNavigationModule(result.data, moduleKey)) {
      toast.info('校验完成，此入口仍未向当前账号开放。', { id: 'navigation-access-recheck', duration: 3200 })
    }
  }

  useEffect(() => {
    setHasHydrated(true)
  }, [])

  if (!hasHydrated || access.isLoading) {
    return (
      <AppFrame>
        <PageLoading
          className="min-h-full bg-transparent"
          message="正在校验入口权限..."
          srMessage={`正在校验${pageName}入口权限`}
        />
      </AppFrame>
    )
  }

  if (!effectiveAllowed) {
    const isUnknown = access.isError || !access.data
    return (
      <AppFrame>
        <PageStatus
          title={isUnknown ? '无法确认入口权限' : '入口未开放'}
          description={
            isUnknown
              ? '暂时无法读取账号权限或入口配置，请检查登录状态或服务连接后重试。'
              : `「${pageName}」尚未向当前账号开放，请联系管理员。`
          }
          icon={isUnknown ? <ShieldAlert /> : <LockKeyhole />}
          actions={<Button variant="outline" className={pageStatusActionClass} disabled={access.isFetching} aria-busy={access.isFetching} onClick={() => { void recheckAccess() }}>{access.isFetching ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="size-4" />}重新校验</Button>}
          metadata={<details><summary className="cursor-pointer py-1 text-[13px]">入口信息</summary><dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1"><dt>入口标识</dt><dd className="break-all font-mono text-foreground">{moduleKey}</dd><dt>最近读取的角色</dt><dd className="break-all text-foreground">{access.data?.role || '未读取'}</dd></dl><p className="mt-3">管理员可在「设置 → 导航权限」调整。</p></details>}
        />
      </AppFrame>
    )
  }

  return <>{children}</>
}
