'use client'

/**
 * 切块策略下拉选择组件
 * 带图标、描述和徽章的下拉菜单
 */
import { type ReactNode, type KeyboardEvent, useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import {
  Layers,
  Hash,
  AlignLeft,
  GitBranch,
  ChevronDown,
  Check,
} from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import { cn } from '@/lib/utils'
import {
  buildChunkStrategyCatalog,
  getChunkStrategyOption,
  ChunkStrategyOption,
  type ChunkStrategyCatalogItem,
  type ChunkStrategyRecommendation,
} from '@/lib/chunk-strategies'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { useDropdownPlacement, type DropdownSide } from '@/hooks/use-dropdown-placement'
import { pipelinePickerTokens } from '@/components/ui/system-page-tokens'

// 图标映射
const ICON_MAP: Record<ChunkStrategyOption['icon'], PlatformIcon> = {
  recursive: Layers,
  token: Hash,
  sentence: AlignLeft,
  separator: AlignLeft,
  hierarchical: GitBranch,
  integrated: Layers,
}

const RECOMMENDATION_STYLES: Record<
  ChunkStrategyRecommendation,
  { chip: string; section: string }
> = {
  mainstream: {
    chip: pipelinePickerTokens.badge,
    section: 'text-muted-foreground',
  },
  specialized: {
    chip: pipelinePickerTokens.badge,
    section: 'text-muted-foreground',
  },
  experimental: {
    chip: 'bg-warning/10 text-warning',
    section: 'text-warning',
  },
  optional: {
    chip: pipelinePickerTokens.badge,
    section: 'text-muted-foreground',
  },
  integrated: {
    chip: pipelinePickerTokens.badge,
    section: 'text-muted-foreground',
  },
}

const RECOMMENDATION_SECTIONS: ChunkStrategyRecommendation[] = [
  'mainstream',
  'specialized',
  'experimental',
  'optional',
  'integrated',
]

interface ChunkStrategyDropdownProps {
  value: string
  onChange: (value: string) => void
  className?: string
  surface?: 'default' | 'ocean'
  side?: DropdownSide
  compact?: boolean
  disabled?: boolean
}

export function ChunkStrategyDropdown({
  value,
  onChange,
  className,
  surface = 'default',
  side = 'bottom',
  compact = false,
  disabled = false,
}: Readonly<ChunkStrategyDropdownProps>) {
  const [isOpen, setIsOpen] = useState(false)
  useEffect(() => { if (disabled) setIsOpen(false) }, [disabled])
  const dropdownRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const placement = useDropdownPlacement(isOpen, triggerRef, {
    side,
    onOpenChange: setIsOpen,
  })
  const { capabilities, chunkStrategyAvailable } = usePipelineCapabilities()

  const catalog = buildChunkStrategyCatalog(capabilities?.chunk_strategies)
  const selectedCatalogItem =
    catalog.find((option) => option.value === String(value || '').trim().toLowerCase()) || null

  const selectedOption = getChunkStrategyOption(value)
  const selectedRecommendation =
    selectedCatalogItem?.recommendation || 'mainstream'
  const selectedRecommendationLabel =
    selectedCatalogItem?.recommendationLabel || '主流推荐'
  const selectedView: ChunkStrategyCatalogItem = selectedCatalogItem || {
    ...selectedOption,
    recommendation: selectedRecommendation,
    recommendationLabel: selectedRecommendationLabel,
  }
  const SelectedIcon = ICON_MAP[selectedView.icon]
  const resolvedSelectedColor =
    surface === 'ocean'
      ? { bg: 'bg-info/[0.08]', text: 'text-info' }
      : { bg: pipelinePickerTokens.iconFrame, text: 'text-muted-foreground' }
  const resolvedIconFrameSize = surface === 'ocean' ? 'size-6' : 'size-7'
  const normalizedValue = String(value || '').trim().toLowerCase()
  const handleMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = [...(menuRef.current?.querySelectorAll<HTMLButtonElement>('button[role="menuitemradio"]:not(:disabled)') || [])]
    if (event.key === 'Escape' || event.key === 'Tab') {
      if (event.key === 'Escape') event.preventDefault()
      triggerRef.current?.focus()
      setIsOpen(false)
      return
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !items.length) return
    event.preventDefault()
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[next]?.focus()
  }

  // 点击外部关闭
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node
      if (dropdownRef.current?.contains(target)) return
      if (menuRef.current?.contains(target)) return
      setIsOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const groupedOptions = RECOMMENDATION_SECTIONS.map((recommendation) => ({
    recommendation,
    items: catalog.filter((option) => option.recommendation === recommendation),
  })).filter((section) => section.items.length > 0)

  let menu: ReactNode = null
  if (isOpen && placement && typeof document !== 'undefined') {
    menu = createPortal(
        <div
          ref={menuRef}
          data-dropdown-menu="chunk-strategy"
          role="menu"
          aria-label="切块策略"
          onKeyDown={handleMenuKeyDown}
          data-side={placement.side}
          className={cn(
            'fixed z-[1000] select-none overflow-hidden rounded-lg border',
            surface === 'ocean'
              ? 'border-info/30 bg-[linear-gradient(hsl(var(--info)/0.10),hsl(var(--info)/0.10)),linear-gradient(hsl(var(--popover)),hsl(var(--popover)))] text-popover-foreground shadow-strong'
              : pipelinePickerTokens.menu
          )}
          style={placement.style}
        >
          <div
            className="overflow-auto overscroll-contain p-1 no-scrollbar"
            style={{ maxHeight: Math.max(0, placement.maxHeight - 2) }}
          >
            {groupedOptions.map((section) => {
              const sectionStyle = RECOMMENDATION_STYLES[section.recommendation]
              const resolvedSectionStyle =
                surface === 'ocean'
                  ? { chip: 'bg-info/[0.06] text-info', section: 'text-info' }
                  : sectionStyle
              const sectionLabel = section.items[0]?.recommendationLabel || ''
              return (
                <div key={section.recommendation} className="py-1">
                  <div className="flex items-center justify-between px-3 py-1.5">
                    <span className={cn('text-xs font-medium', resolvedSectionStyle.section)}>
                      {sectionLabel}
                    </span>
                    <span className="text-[10px] text-muted-foreground">{section.items.length}</span>
                  </div>
                  {section.items.map((option: ChunkStrategyCatalogItem) => {
                    const Icon = ICON_MAP[option.icon]
                    const resolvedColor =
                      surface === 'ocean'
                        ? { bg: 'bg-info/[0.08]', text: 'text-info' }
                        : { bg: pipelinePickerTokens.iconFrame, text: 'text-muted-foreground' }
                    const isSelected = option.value === normalizedValue
                    const isDisabled = !!option.disabled || chunkStrategyAvailable(option.value) === false
                    const recommendationStyle = RECOMMENDATION_STYLES[option.recommendation]
                    const resolvedRecommendationStyle =
                      surface === 'ocean'
                        ? { chip: 'bg-info/[0.06] text-info', section: 'text-info' }
                        : recommendationStyle

                    return (
                      <button
                        key={option.value}
                        type="button"
                        role="menuitemradio"
                        aria-checked={isSelected}
                        data-strategy={option.value}
                        disabled={isDisabled}
                        onClick={() => {
                          if (isDisabled) return
                          onChange(option.value)
                          setIsOpen(false)
                          triggerRef.current?.focus()
                        }}
                        className={cn(
                          pipelinePickerTokens.row,
                          isSelected
                            ? surface === 'ocean' ? 'bg-info/[0.10]' : pipelinePickerTokens.selectedRow
                            : !isDisabled && (surface === 'ocean' ? 'hover:bg-info/[0.06]' : pipelinePickerTokens.idleRow),
                          isDisabled && 'cursor-not-allowed'
                        )}
                      >
                        <div className={cn('grid shrink-0 place-items-center rounded-md', resolvedIconFrameSize, resolvedColor.bg)}>
                          <Icon className={cn('size-3.5', resolvedColor.text)} />
                        </div>
                        <div className="min-w-0 flex-1 text-left">
                          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                            <span
                              className={cn(
                                'text-[13px] font-medium leading-5',
                                isDisabled ? 'text-muted-foreground' : isSelected && surface === 'ocean' ? 'text-info' : 'text-foreground'
                              )}
                            >
                              {option.label}
                            </span>
                            {option.badge ? (
                              <span className={cn('shrink-0 rounded px-1.5 py-px text-[10px] font-medium leading-4', resolvedRecommendationStyle.chip)}>
                                {option.badge}
                              </span>
                            ) : null}
                          </div>
                          <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{option.description}</p>
                        </div>
                        {isDisabled ? <span className="shrink-0 text-[11px] leading-5 text-muted-foreground">未启用</span> : null}
                        {isSelected ? (
                          <Check
                            className={cn(
                              'size-4 flex-shrink-0',
                              surface === 'ocean' ? 'text-info' : 'text-foreground'
                            )}
                          />
                        ) : null}
                      </button>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>,
        document.body
      )
  }

  return (
    <div ref={dropdownRef} className={cn('relative select-none', className)}>
      {/* 触发按钮 */}
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-label="选择切块策略"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onClick={() => setIsOpen(!isOpen)}
        onKeyDown={event => {
          if (disabled || !['ArrowDown','ArrowUp'].includes(event.key)) return
          event.preventDefault()
          setIsOpen(true)
          requestAnimationFrame(() => {
            const items = menuRef.current?.querySelectorAll<HTMLButtonElement>('button[role="menuitemradio"]:not(:disabled)')
            const selected = menuRef.current?.querySelector<HTMLButtonElement>('button[aria-checked="true"]:not(:disabled)')
            ;(selected || items?.[event.key === 'ArrowUp' ? items.length - 1 : 0])?.focus()
          })
        }}
        className={cn(
          'w-full flex items-center gap-2.5 border transition-colors duration-150 motion-reduce:transition-none focus-ring disabled:opacity-50',
          compact ? 'h-[34px] rounded-md px-2' : 'h-[60px] rounded-lg px-3',
          surface === 'ocean'
            ? 'bg-info/[0.045] hover:bg-info/[0.075]'
            : pipelinePickerTokens.trigger,
          isOpen
            ? surface === 'ocean'
              ? 'border-info/35 ring-2 ring-info/10'
              : 'border-input ring-2 ring-foreground/10'
            : surface === 'ocean'
              ? 'border-info/20 hover:border-info/30'
              : 'hover:border-border'
        )}
      >
        {!compact && <div className={cn('grid shrink-0 place-items-center rounded-md', resolvedIconFrameSize, resolvedSelectedColor.bg)}>
          <SelectedIcon className={cn('size-3.5', resolvedSelectedColor.text)} />
        </div>}
        <div className="min-w-0 flex-1 text-left">
          <div className="flex h-5 min-w-0 items-center gap-2">
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">
              {compact ? selectedView.label.replace(/^(LangChain|LlamaIndex)\s*/i, '') : selectedView.label}
            </span>
          </div>
          {!compact && <p title={selectedView.description} className="mt-0.5 truncate text-xs leading-4 text-muted-foreground">{selectedView.description}</p>}
        </div>
        <ChevronDown
          className={cn(
            'h-4 w-4 flex-shrink-0 text-muted-foreground transition-transform',
            isOpen && 'rotate-180'
          )}
        />
      </button>
      {menu}
    </div>
  )
}
