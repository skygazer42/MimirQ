'use client'

import { cn } from '@/lib/utils'

type ParsingMainPanelProps = {
  children: React.ReactNode
  className?: string
}

export function ParsingMainPanel({ children, className }: Readonly<ParsingMainPanelProps>) {
  return (
    <div className={cn('flex-1 min-w-0 min-h-0 flex overflow-hidden', className)}>
      {children}
    </div>
  )
}

