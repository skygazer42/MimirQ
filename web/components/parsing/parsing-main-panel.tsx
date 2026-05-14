'use client'

import type { HTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

type ParsingMainPanelProps = HTMLAttributes<HTMLDivElement> & {
  children: React.ReactNode
  className?: string
}

export function ParsingMainPanel({ children, className, ...props }: Readonly<ParsingMainPanelProps>) {
  return (
    <div {...props} className={cn('flex-1 min-w-0 min-h-0 flex overflow-hidden', className)}>
      {children}
    </div>
  )
}
