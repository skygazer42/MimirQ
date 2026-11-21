'use client'
import { Button } from '@/components/ui/button'
import { ChevronDown, Minus, Plus } from '@/components/icons'
import { randomBase36Id } from '@/lib/secure-random'

export type SelectOption = {
  value: string
  label: string
  kind?: string
  count?: number
}

export type CollectionSelection = {
  rowId: string
  collectionId: string
}

const similaritySelectClass =
  'h-10 w-full appearance-none rounded-md border border-input bg-background px-3 pr-9 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring'
export const similarityFieldClass =
  'h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring'
const similarityIconControlClass =
  'size-10 shrink-0 rounded-md border-border bg-background text-muted-foreground hover:text-foreground'

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
  selections: readonly CollectionSelection[]
  onChange: (next: CollectionSelection[]) => void
  options: SelectOption[]
}>) {
  return (
    <div className="space-y-1.5">
      {showLabel ? (
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-foreground/72">{label}</div>
      ) : null}
      <div className="space-y-1.5">
        {selections.map(({ collectionId, rowId }, index) => (
          <div key={rowId} className="flex items-center gap-1.5">
            <div className="relative flex-1">
              <select
                aria-label={`${label} ${index + 1}`}
                className={similaritySelectClass}
                value={collectionId}
                onChange={(event) => {
                  const collectionId = event.currentTarget.value
                  onChange(
                    selections.map((selection) => (selection.rowId === rowId ? { rowId, collectionId } : selection)),
                  )
                }}
              >
                <option value="">请选择...</option>
                {options.map((opt) => (
                  <option key={opt.value} value={opt.value} disabled={isEmptyCollectionOption(opt)}>
                    {collectionOptionLabel(opt)}
                  </option>
                ))}
              </select>
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-muted-foreground/70">
                <ChevronDown className="size-4" />
              </span>
            </div>

            {index === 0 ? (
              <Button
                type="button"
                variant="outline"
                size="icon"
                title="添加"
                aria-label={`为${label}添加一个 Collection 选择器`}
                className={similarityIconControlClass}
                onClick={() => onChange([...selections, { rowId: randomBase36Id(10), collectionId: '' }])}
              >
                <Plus className="size-4" />
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="icon"
                title="删除"
                aria-label={`删除第 ${index + 1} 个${label}选择器`}
                className={similarityIconControlClass}
                onClick={() => onChange(selections.filter((selection) => selection.rowId !== rowId))}
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
  value: string
  onChange: (next: string) => void
  min: number
  max: number
}>) {
  return (
    <div className="space-y-1.5 block">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[13px] font-medium text-foreground">{label}</div>
        <div className="text-xs text-muted-foreground">
          {min}-{max}
        </div>
      </div>
      <input
        aria-label={label}
        className={similarityFieldClass}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
    </div>
  )
}
