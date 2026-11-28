import * as React from 'react'
import type { PlatformIcon } from '@/components/icons'

import { cn } from '@/lib/utils'

type EmptyStateProps = {
  title: string
  description?: React.ReactNode
  icon?: PlatformIcon
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
      className={cn('group flex min-h-[240px] flex-col items-center justify-center px-6 py-10 text-center', className)}
    >
      {Icon ? (
        <Icon
          aria-hidden="true"
          appearance={iconClassName ? 'monochrome' : 'color'}
          className={cn('mb-4 size-6 text-muted-foreground', iconClassName)}
        />
      ) : null}

      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {description ? (
        <div className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">{description}</div>
      ) : null}

      {children ? <div className="mt-5 flex items-center gap-2.5">{children}</div> : null}
    </section>
  )
}
