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
  compact?: boolean
}

export function PageHeader({
  title,
  description,
  icon: Icon,
  iconColor = "text-primary",
  children,
  className,
  badge,
  compact = true,
}: Readonly<PageHeaderProps>) {
  return (
    <header className={cn("flex-shrink-0 relative z-10", className)}>
      <div className={cn("flex items-start justify-between", compact ? "gap-3" : "gap-4")}>
        <div className={cn("flex items-center min-w-0", compact ? "gap-2.5" : "gap-4")}>
          <div className={cn(
            "shrink-0 flex items-center justify-center border-0 bg-primary/10 shadow-subtle backdrop-blur-xl",
            compact ? "size-9 rounded-xl" : "size-14 rounded-2xl"
          )}>
            <Icon className={cn(compact ? "size-[18px]" : "size-6", iconColor)} />
          </div>

          <div className="min-w-0">
            <div className={cn("flex flex-wrap items-center", compact ? "gap-x-2.5 gap-y-1" : "gap-x-3 gap-y-2")}>
              <h1 className={cn(
                "text-balance font-semibold text-foreground",
                compact
                  ? "text-lg md:text-xl leading-snug tracking-[-0.01em]"
                  : "text-4xl md:text-5xl leading-[1.02] tracking-[-0.03em]"
              )}>
                {title}
              </h1>
              {badge ? (
                <span className="inline-flex items-center rounded-full border border-sidebar-border/70 bg-sidebar/80 px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.14em] text-muted-foreground tabular-nums backdrop-blur-xl">
                  {badge}
                </span>
              ) : null}
            </div>

            {description ? (
              <div className={cn(
                "max-w-[72ch] text-pretty text-muted-foreground",
                compact
                  ? "mt-0.5 text-[13px] leading-relaxed md:text-sm"
                  : "mt-2 text-sm leading-[1.75] md:text-[15px]"
              )}>
                {description}
              </div>
            ) : null}
          </div>
        </div>

        {children ? <div className={cn("flex items-center gap-2", compact ? "pt-0" : "pt-1")}>{children}</div> : null}
      </div>
    </header>
  )
}
