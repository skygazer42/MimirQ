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
        "group flex min-h-[240px] flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/40 px-6 py-10 text-center",
        className
      )}
    >
      {Icon ? (
        <div className="mb-6 grid size-16 place-items-center rounded-2xl border-0 bg-primary/10 shadow-subtle group-hover:scale-105 transition-transform duration-200 motion-reduce:transition-none">
            <Icon className={cn("size-8 text-primary", iconClassName)} />
        </div>
      ) : null}

      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      {description ? (
        <div className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          {description}
        </div>
      ) : null}

      {children ? <div className="mt-6 flex items-center gap-3">{children}</div> : null}
    </section>
  )
}
