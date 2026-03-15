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
      <div className="px-6 md:px-8 pt-6 md:pt-8 pb-5 md:pb-6 flex-shrink-0 relative z-10">
        <PageContainer size={size}>
          <PageHeader
            title={title}
            description={description}
            icon={icon}
            iconColor={iconColor}
            badge={badge}
            className={cn('p-0', headerClassName)}
          >
            {actions}
          </PageHeader>

          {top ? <div className="mt-4">{top}</div> : null}
          {pipelineRail ? <div className="mt-4">{pipelineRail}</div> : null}
        </PageContainer>
      </div>

      {toolbar ? (
        <PageHeaderBar className="z-20">
          <div className={cn('px-6 md:px-8 py-3 md:py-4', toolbarClassName)}>
            <PageContainer size={size}>{toolbar}</PageContainer>
          </div>
        </PageHeaderBar>
      ) : null}

      <div className={cn('flex-1 min-h-0 overflow-hidden px-6 md:px-8 pb-8', bodyClassName)}>
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
