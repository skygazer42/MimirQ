import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

interface PageHeaderProps {
  title: string
  description?: React.ReactNode
  icon: LucideIcon
  iconColor?: string
  children?: React.ReactNode
  className?: string
  badge?: string
}

export function PageHeader({
  title,
  description,
  icon: Icon,
  iconColor = "text-primary",
  children,
  className,
  badge,
}: Readonly<PageHeaderProps>) {
  return (
    <header className={cn("flex-shrink-0 relative z-10", className)}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4 min-w-0">
          <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl border border-sidebar-border/70 bg-sidebar/80 shadow-sm backdrop-blur-xl">
            <Icon className={cn("size-6", iconColor)} />
          </div>

          <div className="min-w-0 pt-0.5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <h1 className="text-balance text-4xl md:text-5xl font-semibold leading-[1.02] tracking-[-0.03em] text-foreground">
                {title}
              </h1>
              {badge ? (
                <span className="inline-flex items-center rounded-full border border-sidebar-border/70 bg-sidebar/80 px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.14em] text-muted-foreground tabular-nums backdrop-blur-xl">
                  {badge}
                </span>
              ) : null}
            </div>

            {description ? (
              <div className="mt-2 max-w-[72ch] text-pretty text-sm leading-[1.75] text-muted-foreground md:text-[15px]">
                {description}
              </div>
            ) : null}
          </div>
        </div>

        {children ? <div className="flex items-center gap-2 pt-1">{children}</div> : null}
      </div>
    </header>
  )
}
