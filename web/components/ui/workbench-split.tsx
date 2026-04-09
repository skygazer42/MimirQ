import { cn } from "@/lib/utils"

type WorkbenchSplitProps = {
  left?: React.ReactNode
  center: React.ReactNode
  right?: React.ReactNode
  leftWidth?: string
  rightWidth?: string
  className?: string
  leftClassName?: string
  centerClassName?: string
  rightClassName?: string
}

export function WorkbenchSplit({
  left,
  center,
  right,
  leftWidth = '320px',
  rightWidth = '420px',
  className,
  leftClassName,
  centerClassName,
  rightClassName,
}: Readonly<WorkbenchSplitProps>) {
  return (
    <div className={cn('flex min-h-0 flex-1 overflow-hidden', className)}>
      {left ? (
        <aside
          className={cn('min-h-0 shrink-0 border-r border-border/70 bg-background', leftClassName)}
          style={{ width: leftWidth }}
        >
          {left}
        </aside>
      ) : null}

      <section className={cn('min-h-0 min-w-0 flex-1 bg-background', centerClassName)}>{center}</section>

      {right ? (
        <aside
          className={cn('min-h-0 shrink-0 border-l border-border/70 bg-background', rightClassName)}
          style={{ width: rightWidth }}
        >
          {right}
        </aside>
      ) : null}
    </div>
  )
}
