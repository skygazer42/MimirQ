import type { PlatformIcon } from '@/components/icons'
import type { ComponentProps } from 'react'

import { PageBody } from '@/components/ui/page-body'
import { PageContainer } from '@/components/ui/page-container'
import { PageHeader } from '@/components/ui/page-header'
import { PageHeaderBar } from '@/components/ui/page-header-bar'
import type { PageTitleIconName } from '@/components/ui/page-title-icon'
import { PageToolbar } from '@/components/ui/page-toolbar'
import { cn } from '@/lib/utils'

type PageScaffoldProps = {
  title: string
  description?: React.ReactNode
  icon?: PlatformIcon
  iconImage?: PageTitleIconName
  iconColor?: string
  badge?: string
  actions?: React.ReactNode
  status?: React.ReactNode
  top?: React.ReactNode
  toolbar?: React.ReactNode
  children: React.ReactNode
  size?: ComponentProps<typeof PageContainer>['size']
  showHeader?: boolean
  compact?: boolean
  density?: 'default' | 'system-dense'
  bodyGutter?: ComponentProps<typeof PageBody>['gutter']
  headerClassName?: string
  topClassName?: string
  toolbarClassName?: string
  toolbarBarClassName?: string
  bodyClassName?: string
  bodyContainerClassName?: string
}

export function PageScaffold({
  title,
  description,
  icon,
  iconImage,
  iconColor,
  badge,
  actions,
  status,
  top,
  toolbar,
  children,
  size = '6xl',
  showHeader = true,
  compact = true,
  density = 'default',
  bodyGutter,
  headerClassName,
  topClassName,
  toolbarClassName,
  toolbarBarClassName,
  bodyClassName,
  bodyContainerClassName,
}: Readonly<PageScaffoldProps>) {
  const isSystemDense = density === 'system-dense'
  const compactSpacing = isSystemDense || compact
  const headerSpacingClass = compactSpacing ? 'px-4 py-2 md:px-5 lg:px-6' : 'px-6 py-3 md:px-8'
  const topSpacingClass = compactSpacing ? 'px-4 md:px-5 lg:px-6 pb-2.5' : 'px-6 md:px-8 pb-6'
  const toolbarSpacingClass = compactSpacing ? 'px-4 md:px-5 lg:px-6 py-2' : 'px-6 md:px-8 py-3 md:py-4'
  const effectiveBodyGutter = bodyGutter || (isSystemDense ? 'dense' : 'default')

  return (
    <>
      {showHeader ? (
        <div className={cn('flex-shrink-0 relative z-10', headerSpacingClass)}>
          <PageContainer size={size}>
            <PageHeader
              title={title}
              description={description}
              icon={icon}
              iconImage={iconImage}
              iconColor={iconColor}
              badge={badge}
              status={status}
              compact={compact}
              className={cn('p-0', headerClassName)}
            >
              {actions}
            </PageHeader>
          </PageContainer>
        </div>
      ) : null}

      {top ? (
        <div className={cn('flex-shrink-0 relative z-10', topSpacingClass, topClassName)}>
          <PageContainer size={size}>{top}</PageContainer>
        </div>
      ) : null}

      {toolbar ? (
        <PageHeaderBar className={cn('z-20', toolbarBarClassName)}>
          <div className={cn(toolbarSpacingClass, toolbarClassName)}>
            <PageContainer size={size}>
              <PageToolbar>{toolbar}</PageToolbar>
            </PageContainer>
          </div>
        </PageHeaderBar>
      ) : null}

      <PageBody className={bodyClassName} compact={compact} gutter={effectiveBodyGutter}>
        <PageContainer size={size} className={bodyContainerClassName}>
          {children}
        </PageContainer>
      </PageBody>
    </>
  )
}
