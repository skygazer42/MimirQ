import type { LucideIcon } from 'lucide-react'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'
import { PageContainer } from '@/components/ui/page-container'
import { PageHeader } from '@/components/ui/page-header'
import { PageHeaderBar } from '@/components/ui/page-header-bar'
import { WorkbenchPane } from './workbench-pane'

type WorkbenchScaffoldProps = {
  title: string
  description?: React.ReactNode
  icon: LucideIcon
  iconColor?: string
  badge?: string
  actions?: React.ReactNode

  top?: React.ReactNode
  pipelineRail?: React.ReactNode
  toolbar?: React.ReactNode

  leftPanel?: React.ReactNode
  rightPanel?: React.ReactNode

  mainPanel?: React.ReactNode
  children?: React.ReactNode

  size?: ComponentProps<typeof PageContainer>['size']
  compactHeader?: boolean

  className?: string
  headerClassName?: string
  toolbarClassName?: string
  bodyClassName?: string
}

export function WorkbenchScaffold({
  title,
  description,
  icon,
  iconColor,
  badge,
  actions,
  top,
  pipelineRail,
  toolbar,
  leftPanel,
  rightPanel,
  mainPanel,
  children,
  size = '6xl',
  compactHeader = true,
  className,
  headerClassName,
  toolbarClassName,
  bodyClassName,
}: Readonly<WorkbenchScaffoldProps>) {
  const resolvedMainPanel =
    mainPanel ?? (children ? <WorkbenchPane className="flex-1">{children}</WorkbenchPane> : null)

  if (!resolvedMainPanel) {
    throw new Error('WorkbenchScaffold requires `mainPanel` or `children`.')
  }

  return (
    <div className={cn('flex h-full min-h-0 flex-col overflow-hidden', className)}>
      <div className={cn(
        'flex-shrink-0 relative z-10',
        compactHeader
          ? 'px-4 md:px-6 pt-3 md:pt-4 pb-2 md:pb-3'
          : 'px-6 md:px-8 pt-6 md:pt-8 pb-5 md:pb-6'
      )}>
        <PageContainer size={size}>
          <PageHeader
            title={title}
            description={description}
            icon={icon}
            iconColor={iconColor}
            badge={badge}
            compact={compactHeader}
            className={cn('p-0', headerClassName)}
          >
            {actions}
          </PageHeader>

          {top ? <div className={compactHeader ? 'mt-2' : 'mt-4'}>{top}</div> : null}
          {pipelineRail ? <div className={compactHeader ? 'mt-2' : 'mt-4'}>{pipelineRail}</div> : null}
        </PageContainer>
      </div>

      {toolbar ? (
        <PageHeaderBar className="z-20">
          <div className={cn(
            compactHeader ? 'px-4 md:px-6 py-2 md:py-3' : 'px-6 md:px-8 py-3 md:py-4',
            toolbarClassName
          )}>
            <PageContainer size={size}>{toolbar}</PageContainer>
          </div>
        </PageHeaderBar>
      ) : null}

      <div className={cn(
        'flex-1 min-h-0 overflow-hidden pb-8',
        compactHeader ? 'px-4 md:px-6' : 'px-6 md:px-8',
        bodyClassName
      )}>
        <PageContainer size={size} className="h-full">
          <div className="flex h-full min-h-0 gap-4">
            {leftPanel ? (
              <aside className="hidden lg:flex w-80 min-h-0 overflow-hidden flex-col">
                {leftPanel}
              </aside>
            ) : null}

            <section className="flex-1 min-w-0 min-h-0 overflow-hidden flex flex-col">
              {resolvedMainPanel}
            </section>

            {rightPanel ? (
              <aside className="hidden xl:flex w-96 min-h-0 overflow-hidden flex-col">
                {rightPanel}
              </aside>
            ) : null}
          </div>
        </PageContainer>
      </div>
    </div>
  )
}
