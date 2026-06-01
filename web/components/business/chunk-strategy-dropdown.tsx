'use client'

/**
 * 切块策略下拉选择组件
 * 带图标、描述和徽章的下拉菜单
 */
import { type ReactNode, useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import {
  Layers,
  Hash,
  AlignLeft,
  GitBranch,
  ChevronDown,
  Check,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  buildChunkStrategyCatalog,
  getChunkStrategyOption,
  ChunkStrategyOption,
  type ChunkStrategyCatalogItem,
  type ChunkStrategyRecommendation,
} from '@/lib/chunk-strategies'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

// 图标映射
const ICON_MAP: Record<ChunkStrategyOption['icon'], any> = {
  recursive: Layers,
  token: Hash,
  sentence: AlignLeft,
  separator: AlignLeft,
  hierarchical: GitBranch,
  integrated: Layers,
}

// 颜色映射
const COLOR_MAP: Record<
  ChunkStrategyOption['icon'],
  { bg: string; text: string }
> = {
  recursive: { bg: 'bg-primary/10', text: 'text-primary' },
  token: { bg: 'bg-warning/10', text: 'text-warning' },
  sentence: { bg: 'bg-success/10', text: 'text-success' },
  separator: { bg: 'bg-muted', text: 'text-muted-foreground' },
  hierarchical: { bg: 'bg-accent/10', text: 'text-accent' },
  integrated: { bg: 'bg-primary/10', text: 'text-primary' },
}

const RECOMMENDATION_STYLES: Record<
  ChunkStrategyRecommendation,
  { chip: string; section: string }
> = {
  mainstream: {
    chip: 'bg-primary/10 text-primary',
    section: 'text-primary',
  },
  specialized: {
    chip: 'bg-muted text-muted-foreground',
    section: 'text-muted-foreground',
  },
  experimental: {
    chip: 'bg-warning/10 text-warning',
    section: 'text-warning',
  },
  optional: {
    chip: 'bg-accent/10 text-accent',
    section: 'text-accent',
  },
  integrated: {
    chip: 'bg-info/10 text-info',
    section: 'text-info',
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
}

export function ChunkStrategyDropdown({ value, onChange, className }: Readonly<ChunkStrategyDropdownProps>) {
  const [isOpen, setIsOpen] = useState(false)
  const [openUpward, setOpenUpward] = useState(false)
  const [menuMaxHeight, setMenuMaxHeight] = useState(420)
  const [menuRect, setMenuRect] = useState<{
    left: number
    width: number
    top?: number
    bottom?: number
  } | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const { capabilities, chunkStrategyAvailable } = usePipelineCapabilities()

  const catalog = buildChunkStrategyCatalog(capabilities?.chunk_strategies)
  const selectedCatalogItem =
    catalog.find((option) => option.value === String(value || '').trim().toLowerCase()) || null

  const selectedOption = getChunkStrategyOption(value)
  const selectedRecommendation =
    selectedCatalogItem?.recommendation || 'mainstream'
  const selectedRecommendationLabel =
    selectedCatalogItem?.recommendationLabel || '主流推荐'
  const selectedRecommendationStyle = RECOMMENDATION_STYLES[selectedRecommendation]
  const selectedView: ChunkStrategyCatalogItem = selectedCatalogItem || {
    ...selectedOption,
    recommendation: selectedRecommendation,
    recommendationLabel: selectedRecommendationLabel,
  }
  const SelectedIcon = ICON_MAP[selectedView.icon]
  const selectedColor = COLOR_MAP[selectedView.icon]
  const normalizedValue = String(value || '').trim().toLowerCase()

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

  function updateMenuPlacement() {
    const triggerRect = triggerRef.current?.getBoundingClientRect()
    if (!triggerRect) return

    const viewportHeight = window.innerHeight || document.documentElement.clientHeight
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth
    const spaceBelow = viewportHeight - triggerRect.bottom
    const spaceAbove = triggerRect.top
    const shouldOpenUpward = spaceBelow < 440 && spaceAbove > spaceBelow
    const availableSpace = shouldOpenUpward ? spaceAbove - 16 : spaceBelow - 16
    const menuWidth = Math.min(
      Math.max(triggerRect.width, 360),
      Math.max(240, viewportWidth - 24)
    )
    const menuLeft = Math.min(
      Math.max(12, triggerRect.left),
      Math.max(12, viewportWidth - menuWidth - 12)
    )

    setOpenUpward(shouldOpenUpward)
    setMenuMaxHeight(Math.max(180, Math.min(420, Math.floor(availableSpace))))
    setMenuRect({
      left: menuLeft,
      width: menuWidth,
      ...(shouldOpenUpward
        ? { bottom: viewportHeight - triggerRect.top + 8 }
        : { top: triggerRect.bottom + 8 }),
    })
  }

  useEffect(() => {
    if (!isOpen) return

    updateMenuPlacement()
    window.addEventListener('resize', updateMenuPlacement)
    window.addEventListener('scroll', updateMenuPlacement, true)

    return () => {
      window.removeEventListener('resize', updateMenuPlacement)
      window.removeEventListener('scroll', updateMenuPlacement, true)
    }
  }, [isOpen])

  let menu: ReactNode = null
  if (isOpen && menuRect && typeof document !== 'undefined') {
    const placementStyle = openUpward
      ? { bottom: menuRect.bottom }
      : { top: menuRect.top }

    menu = createPortal(
        <div
          ref={menuRef}
          className="fixed z-[1000] overflow-hidden rounded-lg border border-border bg-card shadow-lg"
          style={{
            left: menuRect.left,
            width: menuRect.width,
            ...placementStyle,
          }}
        >
          <div
            className="overflow-auto overscroll-contain py-1 no-scrollbar"
            style={{ maxHeight: menuMaxHeight }}
          >
            {groupedOptions.map((section) => {
              const sectionStyle = RECOMMENDATION_STYLES[section.recommendation]
              const sectionLabel = section.items[0]?.recommendationLabel || ''
              return (
                <div key={section.recommendation} className="py-1">
                  <div className="flex items-center justify-between px-3 py-1.5">
                    <span className={cn('text-[10px] font-semibold tracking-[0.08em]', sectionStyle.section)}>
                      {sectionLabel}
                    </span>
                    <span className="text-[10px] text-muted-foreground">{section.items.length}</span>
                  </div>
                  {section.items.map((option: ChunkStrategyCatalogItem) => {
                    const Icon = ICON_MAP[option.icon]
                    const color = COLOR_MAP[option.icon]
                    const isSelected = option.value === normalizedValue
                    const isDisabled = !!option.disabled || chunkStrategyAvailable(option.value) === false
                    const recommendationStyle = RECOMMENDATION_STYLES[option.recommendation]

                    return (
                      <button
                        key={option.value}
                        type="button"
                        disabled={isDisabled}
                        onClick={() => {
                          if (isDisabled) return
                          onChange(option.value)
                          setIsOpen(false)
                        }}
                        className={cn(
                          'w-full flex items-center gap-2.5 px-3 py-2 transition-colors',
                          isSelected ? 'bg-primary/10' : 'hover:bg-muted',
                          isDisabled && 'opacity-50 cursor-not-allowed hover:bg-transparent'
                        )}
                      >
                        <div className={cn('rounded-md p-1.5', color.bg)}>
                          <Icon className={cn('size-3.5', color.text)} />
                        </div>
                        <div className="flex-1 min-w-0 text-left">
                          <div className="flex items-center gap-1.5">
                            <span
                              className={cn(
                                'truncate text-[11px] font-medium',
                                isSelected ? 'text-primary' : 'text-foreground'
                              )}
                            >
                              {option.label}
                            </span>
                            <span className={cn('rounded px-1.5 py-0.5 text-[9px] font-medium', recommendationStyle.chip)}>
                              {option.recommendationLabel}
                            </span>
                            {option.badge ? (
                              <span className="rounded px-1.5 py-0.5 text-[9px] font-medium bg-muted text-muted-foreground">
                                {option.badge}
                              </span>
                            ) : null}
                          </div>
                          <p className="truncate text-[11px] text-muted-foreground">{option.description}</p>
                        </div>
                        {isSelected ? (
                          <Check className="size-4 flex-shrink-0 text-primary" />
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
    <div ref={dropdownRef} className={cn('relative', className)}>
      {/* 触发按钮 */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => {
          if (!isOpen) updateMenuPlacement()
          setIsOpen(!isOpen)
        }}
        className={cn(
          'w-full flex items-center gap-2.5 rounded-lg border px-2.5 py-2 transition-colors duration-150 motion-reduce:transition-none',
          'bg-card hover:bg-muted',
          isOpen
            ? 'border-primary/30 ring-2 ring-primary/10'
            : 'border-border hover:border-border'
        )}
      >
        <div className={cn('rounded-md p-1.5', selectedColor.bg)}>
          <SelectedIcon className={cn('size-3.5', selectedColor.text)} />
        </div>
        <div className="flex-1 text-left min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13px] font-medium text-foreground">
              {selectedView.label}
            </span>
            <span
              className={cn(
                'rounded px-1.5 py-px text-[9px] font-medium leading-4',
                selectedRecommendationStyle.chip
              )}
            >
              {selectedRecommendationLabel}
            </span>
            {selectedView.badge && (
              <span className="rounded bg-primary/10 px-1.5 py-px text-[9px] font-medium leading-4 text-primary">
                {selectedView.badge}
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-[11px] leading-4 text-muted-foreground">{selectedView.description}</p>
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
