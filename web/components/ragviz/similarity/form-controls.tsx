'use client'

import type { ReactNode } from 'react'
import { useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ChevronDown, Minus, Plus } from 'lucide-react'

export type SelectOption = {
  value: string
  label: string
  kind?: string
  count?: number
}

const similaritySelectClass =
  'h-9 w-full appearance-none rounded-[0.9rem] border border-border/38 bg-background/58 px-3 pr-9 text-[12px] font-medium text-foreground/84 shadow-[inset_0_1px_0_hsl(var(--card)/0.62),0_10px_24px_-22px_hsl(var(--foreground)/0.28)] outline-none transition-[border-color,box-shadow,background-color] hover:border-primary/26 hover:bg-background/76 focus:border-primary/38 focus:shadow-[inset_0_1px_0_hsl(var(--card)/0.72),0_0_0_4px_hsl(var(--primary)/0.10)]'
export const similarityInputClass =
  'h-9 w-full rounded-[0.9rem] border border-border/38 bg-background/58 px-3 text-[12px] font-medium text-foreground/84 shadow-[inset_0_1px_0_hsl(var(--card)/0.62),0_10px_24px_-22px_hsl(var(--foreground)/0.28)] outline-none transition-[border-color,box-shadow,background-color] hover:border-primary/26 hover:bg-background/76 focus:border-primary/38 focus:shadow-[inset_0_1px_0_hsl(var(--card)/0.72),0_0_0_4px_hsl(var(--primary)/0.10)]'
const similarityIconControlClass =
  'h-9 w-9 rounded-[0.9rem] border-border/38 bg-background/58 text-muted-foreground shadow-[inset_0_1px_0_hsl(var(--card)/0.62),0_10px_24px_-22px_hsl(var(--foreground)/0.28)] hover:border-primary/30 hover:bg-background/76 hover:text-primary'
export const similarityNativeSelectClass =
  'h-9 w-full rounded-[0.9rem] border border-border/38 bg-background/58 px-3 text-[12px] font-medium text-foreground/84 shadow-[inset_0_1px_0_hsl(var(--card)/0.62)] outline-none focus:border-primary/38 focus:ring-4 focus:ring-primary/10'

export function isEmptyCollectionOption(option: SelectOption) {
  return typeof option.count === 'number' && option.count <= 0
}

function collectionOptionLabel(option: SelectOption) {
  if (typeof option.count !== 'number') return option.label
  if (option.count <= 0) return `${option.label}（0 项，暂无数据）`
  return `${option.label}（${option.count} 项）`
}

export function AxisConfigCard({
  eyebrow,
  title,
  badge,
  badgeClassName,
  children,
}: Readonly<{
  eyebrow: string
  title: string
  badge: string
  badgeClassName?: string
  children: ReactNode
}>) {
  return (
    <section className="border-b border-border/28 px-3.5 py-3.5 last:border-b-0">
      <div className="mb-2.5 flex items-start justify-between gap-2.5">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/72">
            {eyebrow}
          </div>
          <div className="mt-0.5 text-[13px] font-semibold leading-4 text-foreground/86">
            {title}
          </div>
        </div>
        <span
          className={cn(
            'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-medium',
            badgeClassName
          )}
        >
          {badge}
        </span>
      </div>
      <div className="space-y-2.5">{children}</div>
    </section>
  )
}

export function CollectionSelectorBlock({
  label,
  showLabel = true,
  selections,
  onChange,
  options,
}: Readonly<{
  label: string
  showLabel?: boolean
  selections: string[]
  onChange: (next: string[]) => void
  options: SelectOption[]
}>) {
  const keyedSelections = useMemo(() => {
    const seen = new Map<string, number>()
    return selections.map((value) => {
      const base = value || '__empty__'
      const count = (seen.get(base) ?? 0) + 1
      seen.set(base, count)
      return { value, key: `${base}:${count}` }
    })
  }, [selections])

  return (
    <div className="space-y-1.5">
      {showLabel ? (
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-foreground/72">
          {label}
        </div>
      ) : null}
      <div className="space-y-1.5">
        {keyedSelections.map(({ value, key }, idx) => (
          <div key={key} className="flex items-center gap-1.5">
            <div className="relative flex-1">
              <select
                className={similaritySelectClass}
                value={value}
                onChange={(e) => {
                  const next = [...selections]
                  next[idx] = e.target.value
                  onChange(next)
                }}
              >
                <option value="">请选择...</option>
                {options.map((opt) => (
                  <option
                    key={opt.value}
                    value={opt.value}
                    disabled={isEmptyCollectionOption(opt)}
                  >
                    {collectionOptionLabel(opt)}
                  </option>
                ))}
              </select>
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-muted-foreground/70">
                <ChevronDown className="size-4" />
              </span>
            </div>

            {idx === 0 ? (
              <Button
                type="button"
                variant="outline"
                size="icon"
                title="添加"
                aria-label={`为${label}添加一个 Collection 选择器`}
                className={similarityIconControlClass}
                onClick={() => onChange([...selections, ''])}
              >
                <Plus className="size-4" />
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="icon"
                title="删除"
                aria-label={`删除第 ${idx + 1} 个${label}选择器`}
                className={similarityIconControlClass}
                onClick={() => onChange(selections.filter((_, i) => i !== idx))}
              >
                <Minus className="size-4" />
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
}: Readonly<{
  label: string
  value: number
  onChange: (next: number) => void
  min: number
  max: number
}>) {
  return (
    <div className="space-y-1.5 block">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/60">
          {label}
        </div>
        <div className="text-[10.5px] font-medium text-muted-foreground/58">
          {min}-{max}
        </div>
      </div>
      <input
        aria-label={label}
        className={similarityInputClass}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => {
          const parsed = Number(e.target.value)
          if (!Number.isFinite(parsed)) return
          onChange(parsed)
        }}
      />
    </div>
  )
}
