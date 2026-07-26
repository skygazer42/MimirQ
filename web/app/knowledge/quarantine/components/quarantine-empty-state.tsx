'use client'

import { RefreshCw, RotateCcw, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function QuarantineEmptyState({
  hasActiveFilters,
  autoRefresh,
  isFetching,
  onResetFilters,
  onRefresh,
}: Readonly<{
  hasActiveFilters: boolean
  autoRefresh: boolean
  isFetching: boolean
  onResetFilters: () => void
  onRefresh: () => void
}>) {
  return (
    <div className="flex min-h-[10.5rem] flex-col items-center justify-center px-6 py-3.5 text-center">
      <div className="relative mb-2 h-[58px] w-[92px]">
        <div className="absolute inset-x-2 bottom-2 h-14 rounded-[1.35rem] bg-primary/15 blur-2xl" />
        <div className="absolute left-4 top-4 h-8 w-14 rounded-[0.8rem] border border-primary/20 bg-primary/10 shadow-[0_14px_30px_-24px_hsl(var(--primary)/0.55)]" />
        <div className="absolute left-4 top-2.5 h-4 w-8 rounded-t-xl bg-primary/15" />
        <div className="absolute left-7 top-6 flex size-9 items-center justify-center rounded-full border-[3px] border-primary/40 bg-background/80 shadow-sm">
          <Search className="size-4 text-primary" />
        </div>
        <span className="absolute left-1 top-7 size-1.5 rounded-full bg-primary/30" />
        <span className="absolute right-6 top-2 size-2 rounded-full bg-primary/30" />
        <span className="absolute right-2 top-10 size-1.5 rounded-full bg-primary/20" />
      </div>

      <div className="text-[0.98rem] font-semibold text-foreground">
        {hasActiveFilters
          ? '当前筛选条件下暂无隔离记录'
          : '当前没有待审隔离样本'}
      </div>
      <p className="mt-1 max-w-lg text-[10px] leading-5 text-muted-foreground">
        {hasActiveFilters
          ? '尝试调整筛选条件，或手动同步最新数据后重新检查。'
          : '隔离队列目前为空。保持自动刷新开启即可在有新样本进入时即时看到。'}
      </p>

      <div className="mt-2.5 flex flex-wrap items-center justify-center gap-2.5">
        <Button
          type="button"
          variant="outline"
          className="h-8 rounded-xl border-border/60 bg-background px-3.5 text-[11px] font-medium"
          onClick={onResetFilters}
        >
          <RotateCcw className="size-4" />
          重置筛选
        </Button>
        <Button
          type="button"
          className="h-8 rounded-xl bg-primary px-3.5 text-[11px] font-semibold text-primary-foreground shadow-[0_16px_30px_-22px_hsl(var(--primary)/0.8)] hover:bg-primary/90"
          onClick={onRefresh}
        >
          <RefreshCw
            className={cn(
              'size-4',
              isFetching ? 'animate-spin motion-reduce:animate-none' : ''
            )}
          />
          同步数据
        </Button>
      </div>

      <div className="mt-2 text-[11px] text-muted-foreground">
        {autoRefresh
          ? '自动刷新已开启，每 5 秒轮询一次。'
          : '自动刷新已关闭，仅手动同步。'}
      </div>
    </div>
  )
}
