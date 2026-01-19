'use client'

/**
 * RAGFlow 风格的解析器下拉选择组件
 * 带图标、描述和徽章的下拉菜单
 */
import { useState, useRef, useEffect } from 'react'
import {
  Sparkles,
  FileText,
  Cpu,
  LayoutGrid,
  Cloud,
  ScanLine,
  ScanText,
  FileCode,
  Wand2,
  ChevronDown,
  Check,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { PARSER_BACKEND_OPTIONS, getParserOption } from '@/lib/parser-options'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

// 图标映射
const ICON_MAP = {
  auto: Sparkles,
  basic: FileText,
  docling: Cpu,
  layout: LayoutGrid,
  mineru: Cloud,
  deepdoc: ScanLine,
  deepseekocr: ScanText,
  markitdown: FileCode,
  magicpdf: Wand2,
}

// 颜色映射
const COLOR_MAP = {
  auto: { bg: 'bg-sky-100', text: 'text-sky-600' },
  basic: { bg: 'bg-gray-100', text: 'text-gray-600' },
  docling: { bg: 'bg-teal-100', text: 'text-teal-700' },
  layout: { bg: 'bg-emerald-100', text: 'text-emerald-700' },
  mineru: { bg: 'bg-blue-100', text: 'text-blue-600' },
  deepdoc: { bg: 'bg-orange-100', text: 'text-orange-600' },
  deepseekocr: { bg: 'bg-rose-100', text: 'text-rose-700' },
  markitdown: { bg: 'bg-purple-100', text: 'text-purple-600' },
  magicpdf: { bg: 'bg-fuchsia-100', text: 'text-fuchsia-700' },
}

interface ParserDropdownProps {
  value: string
  onChange: (value: string) => void
  className?: string
}

export function ParserDropdown({ value, onChange, className }: ParserDropdownProps) {
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const { capabilities, loading, error, refresh, parserBackendAvailable } = usePipelineCapabilities()

  const normalizeBackendName = (backend?: string) => {
    const raw = (backend || '').toLowerCase().trim()
    const normalized = raw.replace(/_/g, '-')
    if (normalized === 'magic-pdf') return 'magicpdf'
    if (normalized === 'olm-ocr') return 'olmocr'
    if (normalized === 'olmocr-pdf') return 'olmocr'
    if (normalized === 'etl-4llm') return 'etl4llm'
    if (normalized === 'bisheng-unstructured') return 'etl4llm'
    if (normalized === 'bishengunstructured') return 'etl4llm'
    if (normalized === 'bisheng') return 'etl4llm'
    return normalized
  }

  const parserNotesByName = new Map<string, string>()
  for (const info of capabilities?.pdf_backends || []) {
    const key = normalizeBackendName(info.name)
    const notes = (info.notes || '').trim()
    if (key && notes) parserNotesByName.set(key, notes)
  }

  const selectedOption = getParserOption(value)
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
          {(loading || error) && (
            <div className={cn('px-3 py-2 text-xs border-b', error ? 'bg-red-50 text-red-700 border-red-100' : 'bg-gray-50 text-gray-600 border-gray-100')}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  {loading ? '正在加载后端解析器能力…' : '无法获取后端解析器能力，部分选项可能不可用。'}
                </div>
                {error ? (
                  <button
                    type="button"
                    className="flex-shrink-0 text-xs text-red-700 hover:text-red-800 underline underline-offset-2"
                    onClick={() => {
                      void refresh()
                    }}
                  >
                    重试
                  </button>
                ) : null}
              </div>
              {error ? <div className="mt-1 text-[11px] text-red-600/80 truncate" title={error}>{error}</div> : null}
            </div>
          )}
          <div className="py-1">
            {PARSER_BACKEND_OPTIONS.map((option) => {
              const Icon = ICON_MAP[option.icon]
              const color = COLOR_MAP[option.icon]
              const isSelected = option.value === selectedOption.value
              const availability = parserBackendAvailable(option.value)
              const isDisabled = option.value !== 'auto' && option.value !== 'basic' && availability !== true
              const notes = parserNotesByName.get(normalizeBackendName(option.value))
              const disabledTitle = notes || '后端未启用该解析器（可到“设置”开启/配置）'

              return (
                <button
                  key={option.value}
                  type="button"
                  disabled={isDisabled}
                  title={isDisabled ? disabledTitle : undefined}
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
                              : 'bg-gray-100 text-gray-500'
                          )}
                        >
                          {option.badge}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-400 truncate">{option.description}</p>
                  </div>
                  {isDisabled && (
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 flex-shrink-0">
                      未启用
                    </span>
                  )}
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
