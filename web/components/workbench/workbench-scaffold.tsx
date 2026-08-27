import type { LucideIcon } from 'lucide-react'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'
import { PageContainer } from '@/components/ui/page-container'
import { PageHeader } from '@/components/ui/page-header'
import { PageHeaderBar } from '@/components/ui/page-header-bar'
import type { PageTitleIconName } from '@/components/ui/page-title-icon'
import { WorkbenchPane } from './workbench-pane'

type WorkbenchScaffoldProps = {
  title: React.ReactNode
  description?: React.ReactNode
  icon?: LucideIcon
  iconImage?: PageTitleIconName
  iconColor?: string
  badge?: string
  actions?: React.ReactNode
  header?: React.ReactNode

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
  paneGroupClassName?: string
  mainPaneClassName?: string
  mainPaneBodyClassName?: string
}

function getWorkbenchHeaderSpacingClass(compactHeader: boolean): string {
  if (compactHeader) return 'px-4 md:px-6 pt-3 md:pt-4 pb-2 md:pb-3'
  return 'px-6 md:px-8 pt-6 md:pt-8 pb-5 md:pb-6'
}

function getWorkbenchSectionMarginClass(compactHeader: boolean): string {
  if (compactHeader) return 'mt-2'
  return 'mt-4'
}

function getWorkbenchToolbarSpacingClass(compactHeader: boolean): string {
  if (compactHeader) return 'px-4 md:px-6 py-2 md:py-3'
  return 'px-6 md:px-8 py-3 md:py-4'
}

function getWorkbenchBodySpacingClass(compactHeader: boolean): string {
  if (compactHeader) return 'px-4 md:px-6'
  return 'px-6 md:px-8'
}

export function WorkbenchScaffold({
  title,
  description,
  icon,
  iconImage,
  iconColor,
  badge,
  actions,
  header,
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
  paneGroupClassName,
  mainPaneClassName,
  mainPaneBodyClassName,
}: Readonly<WorkbenchScaffoldProps>) {
  let resolvedMainPanel = mainPanel
  if (!resolvedMainPanel && children) {
    resolvedMainPanel = (
      <WorkbenchPane
        className={cn('flex-1', mainPaneClassName)}
        bodyClassName={mainPaneBodyClassName}
      >
        {children}
      </WorkbenchPane>
    )
  }

  if (!resolvedMainPanel) {
    throw new Error('WorkbenchScaffold requires `mainPanel` or `children`.')
  }

  return (
    <div className={cn('flex h-full min-h-0 flex-col overflow-hidden', className)}>
      <div className={cn(
        'flex-shrink-0 relative z-10',
        getWorkbenchHeaderSpacingClass(compactHeader)
      )}>
        <PageContainer size={size}>
          {header ? (
            <div className={cn('p-0', headerClassName)}>{header}</div>
          ) : (
            <PageHeader
              title={title}
              description={description}
              icon={icon}
              iconImage={iconImage}
              iconColor={iconColor}
              badge={badge}
              compact={compactHeader}
              className={cn('p-0', headerClassName)}
            >
              {actions}
            </PageHeader>
          )}

          {top ? <div className={getWorkbenchSectionMarginClass(compactHeader)}>{top}</div> : null}
          {pipelineRail ? <div className={getWorkbenchSectionMarginClass(compactHeader)}>{pipelineRail}</div> : null}
        </PageContainer>
      </div>

      {toolbar ? (
        <PageHeaderBar className="z-20">
          <div className={cn(
            getWorkbenchToolbarSpacingClass(compactHeader),
            toolbarClassName
          )}>
            <PageContainer size={size}>{toolbar}</PageContainer>
          </div>
        </PageHeaderBar>
      ) : null}

      <div className={cn(
        'flex-1 min-h-0 overflow-hidden pb-8',
        getWorkbenchBodySpacingClass(compactHeader),
        bodyClassName
      )}>
        <PageContainer size={size} className="h-full">
          <div
            data-workbench-pane-group="true"
            className={cn('flex h-full min-h-0 gap-4', paneGroupClassName)}
          >
            {leftPanel ? (
              <aside className="hidden lg:flex w-[280px] min-h-0 overflow-hidden flex-col">
                {leftPanel}
              </aside>
            ) : null}

            <section className="flex-1 min-w-0 min-h-0 overflow-hidden flex flex-col">
              {resolvedMainPanel}
            </section>

            {rightPanel ? (
              <aside className="hidden xl:flex w-[360px] min-h-0 overflow-hidden flex-col">
                {rightPanel}
              </aside>
            ) : null}
          </div>
        </PageContainer>
      </div>
    </div>
  )
}
