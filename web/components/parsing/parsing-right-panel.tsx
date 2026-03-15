'use client'

import { cn } from '@/lib/utils'

type ParsingRightPanelProps = {
  children: React.ReactNode
  className?: string
}

export function ParsingRightPanel({ children, className }: Readonly<ParsingRightPanelProps>) {
  return (
    <div
      data-page-scroll-container="true"
      className={cn('min-h-0 min-w-0 overflow-y-auto overscroll-contain', className)}
    >
      {children}
    </div>
  )
}
