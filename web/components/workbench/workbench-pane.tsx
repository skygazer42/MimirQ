import { cn } from '@/lib/utils'
import { Panel } from '@/components/ui/panel'

type WorkbenchPaneProps = {
  header?: React.ReactNode
  children: React.ReactNode
  className?: string
  headerClassName?: string
  bodyClassName?: string
}

export function WorkbenchPane({
  header,
  children,
  className,
  headerClassName,
  bodyClassName,
}: Readonly<WorkbenchPaneProps>) {
  return (
    <Panel padding="none" className={cn('min-h-0 overflow-hidden flex flex-col', className)}>
      {header ? (
        <div
          className={cn(
            'flex items-center justify-between gap-3 border-b border-sidebar-border/70 bg-sidebar/72 px-4 py-3 backdrop-blur-xl',
            headerClassName
          )}
        >
          {header}
        </div>
      ) : null}

      <div
        data-page-scroll-container="true"
        className={cn(
          'flex-1 min-h-0 overflow-y-auto overscroll-contain custom-scrollbar p-4',
          bodyClassName
        )}
      >
        {children}
      </div>
    </Panel>
  )
}
