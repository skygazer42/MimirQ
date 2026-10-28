'use client'
import { useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { ChevronDown, Minus, Plus } from '@/components/icons';

export type SelectOption = {
  value: string
  label: string
  kind?: string
  count?: number
}

const similaritySelectClass =
  'h-10 w-full appearance-none rounded-md border border-input bg-background px-3 pr-9 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring'
export const similarityInputClass =
  'h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring'
const similarityIconControlClass =
  'size-10 shrink-0 rounded-md border-border bg-background text-muted-foreground hover:text-foreground'
export const similarityNativeSelectClass =
  'h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring'

export function isEmptyCollectionOption(option: SelectOption) {
  return typeof option.count === 'number' && option.count <= 0
}

function collectionOptionLabel(option: SelectOption) {
  if (typeof option.count !== 'number') return option.label
  if (option.count <= 0) return `${option.label}（0 项，暂无数据）`
  return `${option.label}（${option.count} 项）`
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
                aria-label={`${label} ${idx + 1}`}
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
        <div className="text-[13px] font-medium text-foreground">
          {label}
        </div>
        <div className="text-xs text-muted-foreground">
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
