'use client'

/**
 * 切块策略下拉选择组件
 * 带图标、描述和徽章的下拉菜单
 */
import { useState, useRef, useEffect } from 'react'
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
  recursive: { bg: 'bg-sky-100 dark:bg-sky-500/20', text: 'text-sky-600 dark:text-sky-300' },
  token: { bg: 'bg-amber-100 dark:bg-amber-500/20', text: 'text-amber-600 dark:text-amber-300' },
  sentence: { bg: 'bg-green-100 dark:bg-green-500/20', text: 'text-green-600 dark:text-green-300' },
  separator: { bg: 'bg-muted', text: 'text-muted-foreground' },
  hierarchical: { bg: 'bg-purple-100 dark:bg-purple-500/20', text: 'text-purple-600 dark:text-purple-300' },
  integrated: { bg: 'bg-sky-100 dark:bg-sky-500/20', text: 'text-sky-600 dark:text-sky-300' },
}

const RECOMMENDATION_STYLES: Record<
  ChunkStrategyRecommendation,
  { chip: string; section: string }
> = {
  mainstream: {
    chip: 'bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-300',
    section: 'text-sky-700 dark:text-sky-300',
  },
  specialized: {
    chip: 'bg-slate-100 text-slate-700 dark:bg-slate-500/20 dark:text-slate-200',
    section: 'text-slate-700 dark:text-slate-200',
  },
  experimental: {
    chip: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
    section: 'text-amber-700 dark:text-amber-300',
  },
  optional: {
    chip: 'bg-violet-100 text-violet-700 dark:bg-violet-500/20 dark:text-violet-300',
    section: 'text-violet-700 dark:text-violet-300',
  },
  integrated: {
    chip: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-500/20 dark:text-cyan-300',
    section: 'text-cyan-700 dark:text-cyan-300',
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

  const menu = isOpen && menuRect && typeof document !== 'undefined'
    ? createPortal(
        <div
          ref={menuRef}
          className="fixed z-[1000] overflow-hidden rounded-lg border border-border bg-card shadow-lg"
          style={{
            left: menuRect.left,
            width: menuRect.width,
            ...(openUpward
              ? { bottom: menuRect.bottom }
              : { top: menuRect.top }),
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
                          isSelected ? 'bg-sky-500/10 dark:bg-sky-500/20' : 'hover:bg-muted',
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
                                isSelected ? 'text-sky-600 dark:text-sky-300' : 'text-foreground'
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
                          <Check className="size-4 flex-shrink-0 text-sky-600 dark:text-sky-300" />
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
    : null

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
            ? 'border-sky-300/60 ring-2 ring-sky-500/10'
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
              <span className="rounded bg-sky-100 px-1.5 py-px text-[9px] font-medium leading-4 text-sky-600 dark:bg-sky-500/20 dark:text-sky-300">
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
