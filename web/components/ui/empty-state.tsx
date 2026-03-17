import * as React from "react"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export type EmptyStateProps = {
  title: string
  description?: React.ReactNode
  icon?: LucideIcon
  iconClassName?: string
  className?: string
  children?: React.ReactNode
}

export function EmptyState({
  title,
  description,
  icon: Icon,
  iconClassName,
  className,
  children,
}: Readonly<EmptyStateProps>) {
  return (
    <section
      className={cn(
        "flex min-h-[320px] flex-col items-center justify-center rounded-lg border border-dashed border-border/60 bg-card/30 px-6 py-12 text-center",
        className
      )}
    >
      {Icon ? (
        <div className="mb-5 grid size-12 place-items-center rounded-lg border border-border/50 bg-muted/50">
            <Icon className={cn("size-6 text-muted-foreground", iconClassName)} />
        </div>
      ) : null}

      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      {description ? (
        <div className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted-foreground">
          {description}
        </div>
      ) : null}

      {children ? <div className="mt-5 flex items-center gap-2">{children}</div> : null}
    </section>
  )
}
