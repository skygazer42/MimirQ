'use client'

import { cn } from '@/lib/utils'

export function ErrorTreemap({
  data,
  selectedReason,
  onReasonSelect,
}: Readonly<{
  data: Array<{ name: string; count: number; fill: string; formatLabel: string; timeLabel: string }>
  selectedReason: string | null
  onReasonSelect: (reason: string) => void
}>) {
  return (
    <div aria-label="风险重灾区热力图" role="grid" className="grid auto-rows-fr gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {data.map((payload) => {
        const isActive = payload.name === selectedReason
        return (
          <button
            key={payload.name}
            type="button"
            role="gridcell"
            onClick={() => onReasonSelect(payload.name)}
            className="group relative h-full overflow-hidden rounded-[0.95rem] border border-border/5 p-0 text-left transition-all duration-300 hover:z-10 hover:-translate-y-0.5 hover:shadow-lg"
            style={{
              background: payload.fill,
            }}
          >
            {isActive && (
              <div className="absolute inset-0 bg-card/20 animate-pulse ring-2 ring-inset ring-white/60 z-20" />
            )}

            <div className={cn(
              "flex h-full min-h-[74px] flex-col justify-between rounded-[0.85rem] px-2.5 py-2.5 text-primary-foreground transition-colors duration-500",
              isActive ? "bg-black/5" : "bg-black/24 group-hover:bg-black/12"
            )}>
              <div className="relative z-10 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 opacity-70">
                    <span className="truncate text-[0.68rem] uppercase tracking-[0.14em] text-primary-foreground/62">
                      {payload.formatLabel}
                    </span>
                    <div className="h-1.5 w-px bg-card/22" />
                    <span className="truncate text-[0.68rem] uppercase tracking-[0.12em] text-primary-foreground/66">
                      {payload.timeLabel}
                    </span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-[0.84rem] font-medium leading-[1.28] text-primary-foreground/96">
                    {payload.name}
                  </div>
                </div>
                <div className="shrink-0 font-code tabular-nums text-[0.95rem] font-semibold leading-none">
                  {payload.count}
                </div>
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
