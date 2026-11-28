'use client'

import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Layers, Hash, AlignLeft, GitBranch, ChevronDown, Check, type PlatformIcon } from '@/components/icons'
import { cn } from '@/lib/utils'
import {
  buildChunkStrategyCatalog,
  getChunkStrategyOption,
  getChunkStrategyRecommendationLabel,
  type ChunkStrategyOption,
  type ChunkStrategyRecommendation,
} from '@/lib/chunk-strategies'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { pipelinePickerTokens } from '@/components/ui/system-page-tokens'

const ICON_MAP: Record<ChunkStrategyOption['icon'], PlatformIcon> = {
  recursive: Layers,
  token: Hash,
  sentence: AlignLeft,
  separator: AlignLeft,
  hierarchical: GitBranch,
  integrated: Layers,
}

const RECOMMENDATION_SECTIONS: ChunkStrategyRecommendation[] = [
  'mainstream',
  'specialized',
  'experimental',
  'optional',
  'integrated',
]

const ENABLED_OPTION_SELECTOR = 'button[role="menuitemradio"]:not(:disabled)'

type ChunkStrategyDropdownProps = {
  value: string
  onChange: (value: string) => void
  compact?: boolean
  disabled?: boolean
}

export function ChunkStrategyDropdown({
  value,
  onChange,
  compact = false,
  disabled = false,
}: Readonly<ChunkStrategyDropdownProps>) {
  const [isOpen, setIsOpen] = useState(false)
  useEffect(() => {
    if (disabled) setIsOpen(false)
  }, [disabled])
  const focusLastOptionRef = useRef(false)
  const { capabilities } = usePipelineCapabilities()

  const catalog = buildChunkStrategyCatalog(capabilities?.chunk_strategies)
  const normalizedValue = value.trim().toLowerCase()
  const selectedOption = catalog.find((option) => option.value === normalizedValue) ?? getChunkStrategyOption(value)
  const SelectedIcon = ICON_MAP[selectedOption.icon]

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Tab') {
      event.preventDefault()
      setIsOpen(false)
      return
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(ENABLED_OPTION_SELECTOR))
    if (items.length === 0) return
    event.preventDefault()
    const current = items.findIndex((item) => item === document.activeElement)
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? items.length - 1
          : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[next].focus()
  }

  function focusMenuOption(event: Event) {
    const focusLastOption = focusLastOptionRef.current
    focusLastOptionRef.current = false
    const menu = event.currentTarget
    if (!(menu instanceof HTMLElement)) return

    const items = Array.from(menu.querySelectorAll<HTMLButtonElement>(ENABLED_OPTION_SELECTOR))
    const selected = items.find((item) => item.getAttribute('aria-checked') === 'true')
    const focusTarget = selected ?? items.at(focusLastOption ? -1 : 0)
    if (focusTarget) {
      event.preventDefault()
      focusTarget.focus()
    }
  }

  const groupedOptions = RECOMMENDATION_SECTIONS.map((recommendation) => ({
    recommendation,
    items: catalog.filter((option) => option.recommendation === recommendation),
  })).filter((section) => section.items.length > 0)

  const menu = (
    <PopoverContent
      data-dropdown-menu="chunk-strategy"
      role="menu"
      aria-label="切块策略"
      align="start"
      sideOffset={8}
      collisionPadding={12}
      onKeyDown={handleMenuKeyDown}
      onOpenAutoFocus={focusMenuOption}
      className={cn(
        'z-[1000] max-h-[min(420px,var(--radix-popover-content-available-height))] w-[max(360px,var(--radix-popover-trigger-width))] max-w-[var(--radix-popover-content-available-width)] select-none overflow-y-auto overscroll-contain p-1 no-scrollbar',
        pipelinePickerTokens.menu,
      )}
    >
      {groupedOptions.map((section) => {
        const isExperimental = section.recommendation === 'experimental'
        return (
          <div key={section.recommendation} className="py-1">
            <div className="flex items-center justify-between px-3 py-1.5">
              <span className={cn('text-xs font-medium', isExperimental ? 'text-warning' : 'text-muted-foreground')}>
                {getChunkStrategyRecommendationLabel(section.recommendation)}
              </span>
              <span className="text-[10px] text-muted-foreground">{section.items.length}</span>
            </div>
            {section.items.map((option) => {
              const Icon = ICON_MAP[option.icon]
              const isSelected = option.value === normalizedValue
              const isDisabled = option.disabled === true || option.available === false

              return (
                <button
                  key={option.value}
                  type="button"
                  role="menuitemradio"
                  aria-checked={isSelected}
                  data-strategy={option.value}
                  disabled={isDisabled}
                  onClick={() => {
                    onChange(option.value)
                    setIsOpen(false)
                  }}
                  className={cn(
                    pipelinePickerTokens.row,
                    isSelected ? pipelinePickerTokens.selectedRow : !isDisabled && pipelinePickerTokens.idleRow,
                    isDisabled && 'cursor-not-allowed',
                  )}
                >
                  <span
                    className={cn('grid size-7 shrink-0 place-items-center rounded-md', pipelinePickerTokens.iconFrame)}
                  >
                    <Icon className="size-3.5 text-muted-foreground" />
                  </span>
                  <span className="min-w-0 flex-1 text-left">
                    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                      <span
                        className={cn(
                          'text-[13px] font-medium leading-5',
                          isDisabled ? 'text-muted-foreground' : 'text-foreground',
                        )}
                      >
                        {option.label}
                      </span>
                      {option.badge ? (
                        <span
                          className={cn(
                            'shrink-0 rounded px-1.5 py-px text-[10px] font-medium leading-4',
                            isExperimental ? 'bg-warning/10 text-warning' : pipelinePickerTokens.badge,
                          )}
                        >
                          {option.badge}
                        </span>
                      ) : null}
                    </span>
                    <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{option.description}</span>
                  </span>
                  {isDisabled ? (
                    <span className="shrink-0 text-[11px] leading-5 text-muted-foreground">未启用</span>
                  ) : null}
                  {isSelected ? <Check className="size-4 flex-shrink-0 text-foreground" /> : null}
                </button>
              )
            })}
          </div>
        )
      })}
    </PopoverContent>
  )

  return (
    <Popover modal open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={`选择切块策略，${selectedOption.label}`}
          aria-haspopup="menu"
          onKeyDown={(event) => {
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
            event.preventDefault()
            focusLastOptionRef.current = event.key === 'ArrowUp'
            setIsOpen(true)
          }}
          className={cn(
            'w-full flex items-center gap-2.5 border transition-colors duration-150 motion-reduce:transition-none focus-ring disabled:opacity-50',
            compact ? 'h-[34px] rounded-md px-2' : 'h-[60px] rounded-lg px-3',
            pipelinePickerTokens.trigger,
            isOpen ? 'border-input ring-2 ring-foreground/10' : 'hover:border-border',
          )}
        >
          {!compact && (
            <span className={cn('grid size-7 shrink-0 place-items-center rounded-md', pipelinePickerTokens.iconFrame)}>
              <SelectedIcon className="size-3.5 text-muted-foreground" />
            </span>
          )}
          <span className="min-w-0 flex-1 text-left">
            <span className="flex h-5 min-w-0 items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">
                {compact ? selectedOption.label.replace(/^(LangChain|LlamaIndex)\s*/i, '') : selectedOption.label}
              </span>
            </span>
            {!compact && (
              <span
                title={selectedOption.description}
                className="mt-0.5 block truncate text-xs leading-4 text-muted-foreground"
              >
                {selectedOption.description}
              </span>
            )}
          </span>
          <ChevronDown
            className={cn('h-4 w-4 flex-shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-180')}
          />
        </button>
      </PopoverTrigger>
      {menu}
    </Popover>
  )
}
