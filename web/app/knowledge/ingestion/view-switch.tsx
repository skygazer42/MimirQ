'use client'

import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'

import { cn } from '@/lib/utils'

type IngestionView = 'operation' | 'execution-monitor'

const VIEW_OPTIONS: Array<{ value: IngestionView; label: string }> = [
  { value: 'operation', label: '入库操作' },
  { value: 'execution-monitor', label: '执行监控' },
]

export function IngestionViewSwitch({ className }: Readonly<{ className?: string }>) {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const activeView: IngestionView = searchParams.get('mode') === 'execution-monitor' ? 'execution-monitor' : 'operation'

  function getViewHref(nextView: IngestionView) {
    const params = new URLSearchParams(searchParams.toString())
    if (nextView === 'execution-monitor') {
      params.set('mode', 'execution-monitor')
    } else {
      params.delete('mode')
    }
    const query = params.toString()
    return query === '' ? pathname : `${pathname}?${query}`
  }

  return (
    <nav className={cn('inline-flex self-stretch gap-5', className)} aria-label="入库视图">
      {VIEW_OPTIONS.map((option) => {
        const selected = activeView === option.value
        return (
          <Link
            key={option.value}
            href={getViewHref(option.value)}
            aria-current={selected ? 'page' : undefined}
            replace
            className={cn(
              'inline-flex h-full min-h-11 items-center border-b-2 text-[13px] transition-colors',
              selected
                ? 'border-accent font-medium text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {option.label}
          </Link>
        )
      })}
    </nav>
  )
}
