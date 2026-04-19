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
        "group flex min-h-[240px] flex-col items-center justify-center rounded-2xl border border-border/60 bg-card/60 px-6 py-10 text-center",
        className
      )}
    >
      {Icon ? (
        <div className="mb-5 grid size-14 place-items-center rounded-2xl bg-muted/50 border border-border/50">
            <Icon className={cn("size-7 text-muted-foreground/70", iconClassName)} />
        </div>
      ) : null}

      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {description ? (
        <div className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground/80">
          {description}
        </div>
      ) : null}

      {children ? <div className="mt-5 flex items-center gap-2.5">{children}</div> : null}
    </section>
  )
}
