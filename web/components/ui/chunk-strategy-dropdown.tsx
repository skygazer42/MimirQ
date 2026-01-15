'use client'

/**
 * 切块策略下拉选择组件
 * 带图标、描述和徽章的下拉菜单
 */
import { useState, useRef, useEffect } from 'react'
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
  CHUNK_STRATEGY_OPTIONS,
  getChunkStrategyOption,
  ChunkStrategyOption,
} from '@/lib/chunk-strategies'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

// 图标映射
const ICON_MAP: Record<ChunkStrategyOption['icon'], any> = {
  recursive: Layers,
  token: Hash,
  sentence: AlignLeft,
  separator: AlignLeft,
  hierarchical: GitBranch,
  ragflow: Layers,
}

// 颜色映射
const COLOR_MAP: Record<
  ChunkStrategyOption['icon'],
  { bg: string; text: string }
> = {
  recursive: { bg: 'bg-sky-100', text: 'text-sky-600' },
  token: { bg: 'bg-amber-100', text: 'text-amber-600' },
  sentence: { bg: 'bg-green-100', text: 'text-green-600' },
  separator: { bg: 'bg-gray-100', text: 'text-gray-600' },
  hierarchical: { bg: 'bg-purple-100', text: 'text-purple-600' },
  ragflow: { bg: 'bg-sky-100', text: 'text-sky-600' },
}

interface ChunkStrategyDropdownProps {
  value: string
  onChange: (value: string) => void
  className?: string
}

export function ChunkStrategyDropdown({ value, onChange, className }: ChunkStrategyDropdownProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [query, setQuery] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const { chunkStrategyAvailable } = usePipelineCapabilities()

  const selectedOption = getChunkStrategyOption(value)
  const SelectedIcon = ICON_MAP[selectedOption.icon]
  const selectedColor = COLOR_MAP[selectedOption.icon]

  // 点击外部关闭
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // 打开时自动聚焦与清理搜索
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => searchRef.current?.focus(), 0)
    } else {
      setQuery('')
    }
  }, [isOpen])

  const normalizedQuery = query.trim().toLowerCase()
  const filteredOptions = normalizedQuery
    ? CHUNK_STRATEGY_OPTIONS.filter((option) => {
        const haystack = `${option.label} ${option.value} ${option.description} ${option.badge || ''}`.toLowerCase()
        return haystack.includes(normalizedQuery)
      })
    : CHUNK_STRATEGY_OPTIONS

  return (
    <div ref={dropdownRef} className={cn('relative', className)}>
      {/* 触发按钮 */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border transition-all',
          'bg-white hover:bg-gray-50',
          isOpen
            ? 'border-sky-300 ring-2 ring-sky-100'
            : 'border-gray-200 hover:border-gray-300'
        )}
      >
        <div className={cn('p-1.5 rounded-lg', selectedColor.bg)}>
          <SelectedIcon className={cn('w-4 h-4', selectedColor.text)} />
        </div>
        <div className="flex-1 text-left min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-900 truncate">
              {selectedOption.label}
            </span>
            {selectedOption.badge && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 bg-sky-100 text-sky-600 rounded">
                {selectedOption.badge}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-400 truncate">{selectedOption.description}</p>
        </div>
        <ChevronDown
          className={cn(
            'w-4 h-4 text-gray-400 transition-transform flex-shrink-0',
            isOpen && 'rotate-180'
          )}
        />
      </button>

      {/* 下拉菜单 */}
      {isOpen && (
        <div className="absolute z-50 w-full mt-2 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-gray-100 bg-white">
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索切块方式..."
              className={cn(
                'w-full rounded-lg border border-gray-200 px-2 py-1.5 text-sm',
                'focus:border-sky-300 focus:outline-none focus:ring-2 focus:ring-sky-100'
              )}
            />
          </div>
          <div className="py-1 max-h-[340px] overflow-auto">
            {filteredOptions.length === 0 && (
              <div className="px-3 py-3 text-xs text-gray-400">没有匹配的切块方式</div>
            )}
            {filteredOptions.map((option) => {
              const Icon = ICON_MAP[option.icon]
              const color = COLOR_MAP[option.icon]
              const isSelected = option.value === value
              const isDisabled = !!option.disabled || chunkStrategyAvailable(option.value) === false

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
                    'w-full flex items-center gap-3 px-3 py-2.5 transition-colors',
                    isSelected ? 'bg-sky-50' : 'hover:bg-gray-50',
                    isDisabled && 'opacity-50 cursor-not-allowed hover:bg-transparent'
                  )}
                >
                  <div className={cn('p-1.5 rounded-lg', color.bg)}>
                    <Icon className={cn('w-4 h-4', color.text)} />
                  </div>
                  <div className="flex-1 text-left min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          'text-sm font-medium truncate',
                          isSelected ? 'text-sky-600' : 'text-gray-900'
                        )}
                      >
                        {option.label}
                      </span>
                      {option.badge && (
                        <span
                          className={cn(
                            'text-[10px] font-medium px-1.5 py-0.5 rounded',
                            isSelected
                              ? 'bg-sky-100 text-sky-600'
                              : option.badge === 'Token'
                              ? 'bg-amber-100 text-amber-600'
                              : 'bg-gray-100 text-gray-500'
                          )}
                        >
                          {option.badge}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-400 truncate">{option.description}</p>
                  </div>
                  {isSelected && (
                    <Check className="w-4 h-4 text-sky-600 flex-shrink-0" />
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
