'use client'

import { useCallback } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'

import { cn } from '@/lib/utils'

type IngestionView = 'operation' | 'execution-monitor'

type IngestionViewSwitchProps = {
  className?: string
  compact?: boolean
}

const VIEW_OPTIONS: Array<{ value: IngestionView; label: string }> = [
  { value: 'operation', label: '入库操作' },
  { value: 'execution-monitor', label: '执行监控' },
]

export function IngestionViewSwitch({ className, compact = false }: Readonly<IngestionViewSwitchProps>) {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const activeView: IngestionView =
    searchParams.get('mode') === 'execution-monitor' ? 'execution-monitor' : 'operation'

  const handleChangeView = useCallback(
    (nextView: IngestionView) => {
      const params = new URLSearchParams(searchParams.toString())
      if (nextView === 'execution-monitor') {
        params.set('mode', 'execution-monitor')
      } else {
        params.delete('mode')
      }
      const query = params.toString()
      router.replace(query ? `${pathname}?${query}` : pathname)
    },
    [pathname, router, searchParams]
  )

  return (
    <div
      className={cn(
        'inline-flex rounded-2xl border border-border/60 bg-card/72 p-1 shadow-[0_10px_28px_hsl(var(--primary)/0.06)] backdrop-blur-xl',
        compact && 'rounded-xl p-0.5 shadow-none',
        className
      )}
    >
      {VIEW_OPTIONS.map((option) => {
        const selected = activeView === option.value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            onClick={() => handleChangeView(option.value)}
            className={cn(
              'h-8 rounded-xl px-3 text-sm font-medium transition-colors',
              compact && 'h-7 rounded-lg px-2 text-[9px]',
              selected
                ? 'bg-primary text-primary-foreground shadow-[0_8px_20px_hsl(var(--primary)/0.18)]'
                : 'text-muted-foreground hover:bg-background/82 hover:text-foreground'
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
