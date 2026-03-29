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
          <div className="size-12 shrink-0 rounded-xl bg-card border border-border shadow-sm flex items-center justify-center">
            <Icon className={cn("size-6", iconColor)} />
          </div>

          <div className="min-w-0 pt-0.5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 className="text-balance text-3xl md:text-4xl font-semibold leading-tight text-foreground">
                {title}
              </h1>
              {badge ? (
                <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-[11px] font-mono text-muted-foreground tabular-nums">
                  {badge}
                </span>
              ) : null}
            </div>

            {description ? (
              <div className="mt-1.5 max-w-[70ch] text-pretty text-sm leading-relaxed text-muted-foreground">
                {description}
              </div>
            ) : null}
          </div>
        </div>

        {children ? <div className="flex items-center gap-2 pt-0.5">{children}</div> : null}
      </div>
    </header>
  )
}
