'use client'

import { LockKeyhole, RefreshCw, ShieldAlert } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/ui/page-loading'
import { PageScaffold } from '@/components/ui/page-scaffold'
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
  const access = useTenantAccess()
  const allowed = hasHydrated && canShowAdminControlledNavigationModule(access.data, moduleKey)

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

  if (!allowed) {
    const isUnknown = access.isError || !access.data
    return (
      <AppFrame>
        <PageScaffold
          title={isUnknown ? '无法确认入口权限' : '入口未开放'}
          description={
            isUnknown
              ? '当前无法读取租户角色或导航配置，请检查登录状态或后端服务后重试。'
              : `管理员未向当前角色开放「${pageName}」前端入口。`
          }
          icon={isUnknown ? ShieldAlert : LockKeyhole}
          size="5xl"
          compact
        >
          <div className="rounded-2xl border border-border/80 bg-card p-6 shadow-sm">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-sm font-semibold text-foreground">入口标识：{moduleKey}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  当前角色：{access.data?.role || '未知'}。如需访问，请联系管理员在「设置 → 导航权限」中开放。
                </p>
              </div>
              <Button variant="outline" className="gap-2 self-start" onClick={() => access.refetch()}>
                <RefreshCw className="size-4" />
                重新校验
              </Button>
            </div>
          </div>
        </PageScaffold>
      </AppFrame>
    )
  }

  return <>{children}</>
}
