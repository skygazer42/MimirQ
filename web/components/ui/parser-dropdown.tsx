'use client'

/**
 * Integrated pipeline 风格的解析器下拉选择组件
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
import { cn, detachPromise } from '@/lib/utils'
import { PARSER_BACKEND_OPTIONS, getParserOption } from '@/lib/parser-options'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { normalizeParserBackendName, resolveParserBackendForFilename } from '@/lib/parser-compat'
import { settingsApi } from '@/lib/api/settings'

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
  auto: { bg: 'bg-sky-100 dark:bg-sky-500/20', text: 'text-sky-600 dark:text-sky-300' },
  basic: { bg: 'bg-muted', text: 'text-muted-foreground' },
  docling: { bg: 'bg-teal-100 dark:bg-teal-500/20', text: 'text-teal-700 dark:text-teal-300' },
  layout: { bg: 'bg-emerald-100 dark:bg-emerald-500/20', text: 'text-emerald-700 dark:text-emerald-300' },
  mineru: { bg: 'bg-blue-100 dark:bg-blue-500/20', text: 'text-blue-600 dark:text-blue-300' },
  deepdoc: { bg: 'bg-orange-100 dark:bg-orange-500/20', text: 'text-orange-600 dark:text-orange-300' },
  deepseekocr: { bg: 'bg-rose-100 dark:bg-rose-500/20', text: 'text-rose-700 dark:text-rose-300' },
  markitdown: { bg: 'bg-purple-100 dark:bg-purple-500/20', text: 'text-purple-600 dark:text-purple-300' },
  magicpdf: { bg: 'bg-fuchsia-100 dark:bg-fuchsia-500/20', text: 'text-fuchsia-700 dark:text-fuchsia-300' },
}

interface ParserDropdownProps {
  value: string
  onChange: (value: string) => void
  className?: string
  filename?: string
  compact?: boolean
}

export function ParserDropdown({ value, onChange, className, filename, compact = false }: Readonly<ParserDropdownProps>) {
  const [isOpen, setIsOpen] = useState(false)
  const [paddleVlVersionBadge, setPaddleVlVersionBadge] = useState<string | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const { capabilities, loading, error, refresh, parserBackendAvailable } = usePipelineCapabilities()

  const parserNotesByName = new Map<string, string>()
  for (const info of capabilities?.pdf_backends || []) {
    const key = normalizeParserBackendName(info.name)
    const notes = (info.notes || '').trim()
    if (key && notes) parserNotesByName.set(key, notes)
  }

  const selectedOption = getParserOption(value)
  const SelectedIcon = ICON_MAP[selectedOption.icon]
  const selectedColor = COLOR_MAP[selectedOption.icon]

  useEffect(() => {
    let cancelled = false

    async function loadPaddleVlHealth() {
      try {
        const status: any = await settingsApi.getStatus()
        const health = status?.parsers?.paddle_vl?.health
        let pv = ''
        if (typeof health?.pipeline_version === 'string') {
          pv = health.pipeline_version
        } else if (typeof health?.version === 'string') {
          pv = health.version
        }
        if (!cancelled) {
          setPaddleVlVersionBadge(pv ? `PaddleOCR-VL ${pv}` : null)
        }
      } catch {
        if (!cancelled) setPaddleVlVersionBadge(null)
      }
    }

    // Only show version badge when the backend considers PaddleOCR-VL available.
    if (parserBackendAvailable('paddle_vl')) {
      loadPaddleVlHealth()
    } else {
      setPaddleVlVersionBadge(null)
    }

    return () => {
      cancelled = true
    }
  }, [parserBackendAvailable])

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
          'w-full flex items-center gap-3 px-3 border transition-colors duration-150 motion-reduce:transition-none',
          compact ? 'py-2 rounded-full' : 'py-2.5 rounded-2xl',
          'bg-card hover:bg-muted',
          isOpen
            ? 'border-sky-300/60 ring-2 ring-sky-500/10'
            : 'border-border hover:border-border'
        )}
      >
        <div className={cn('p-1.5 rounded-lg', selectedColor.bg)}>
          <SelectedIcon className={cn('w-4 h-4', selectedColor.text)} />
        </div>
        <div className="flex-1 text-left min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground truncate">
              {selectedOption.label}
            </span>
            {selectedOption.badge && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 bg-sky-100 text-sky-600 dark:bg-sky-500/20 dark:text-sky-300 rounded">
                {selectedOption.badge}
              </span>
            )}
            {selectedOption.value === 'paddle_vl' && paddleVlVersionBadge ? (
              <span className="text-[10px] font-medium px-1.5 py-0.5 bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300 rounded">
                {paddleVlVersionBadge}
              </span>
            ) : null}
          </div>
          {!compact && (
            <p className="text-xs text-muted-foreground truncate">{selectedOption.description}</p>
          )}
        </div>
        <ChevronDown
          className={cn(
            'w-4 h-4 text-muted-foreground transition-transform flex-shrink-0',
            isOpen && 'rotate-180'
          )}
        />
      </button>

      {/* 下拉菜单 */}
      {isOpen && (
        <div className="absolute z-50 w-full mt-2 bg-card border border-border rounded-2xl shadow-strong overflow-hidden">
          {(loading || error) && (
            <div
              className={cn(
                'px-3 py-2 text-xs border-b',
                error
                  ? 'bg-red-50 text-red-700 border-red-100 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/30'
                  : 'bg-muted text-muted-foreground border-border'
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  {loading ? '正在加载后端解析器能力…' : '无法获取后端解析器能力，部分选项可能不可用。'}
                </div>
                {error ? (
                  <button
                    type="button"
                    className="flex-shrink-0 text-xs text-red-700 hover:text-red-800 dark:text-red-300 dark:hover:text-red-200 underline underline-offset-2"
                    onClick={() => {
                      detachPromise(refresh())
                    }}
                  >
                    重试
                  </button>
                ) : null}
              </div>
              {error ? (
                <div className="mt-1 text-[11px] text-red-600/80 dark:text-red-300/80 truncate" title={error}>
                  {error}
                </div>
              ) : null}
            </div>
          )}
          <div className="py-1">
            {PARSER_BACKEND_OPTIONS.map((option) => {
              const Icon = ICON_MAP[option.icon]
              const color = COLOR_MAP[option.icon]
              const isSelected = option.value === selectedOption.value
              const availability = parserBackendAvailable(option.value)
              const isDisabledByFile =
                Boolean(filename) &&
                option.value !== 'auto' &&
                resolveParserBackendForFilename(filename || '', option.value).backend !== option.value
              const isDisabledByCapabilities = option.value !== 'auto' && option.value !== 'basic' && availability !== true
              const isDisabled = isDisabledByFile || isDisabledByCapabilities
              const notes = parserNotesByName.get(normalizeParserBackendName(option.value))
              const disabledTitle = isDisabledByFile
                ? '该文件类型不支持此解析器'
                : (notes || '后端未启用该解析器（可到“设置”开启/配置）')

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
                    isSelected ? 'bg-sky-500/10 dark:bg-sky-500/20' : 'hover:bg-muted',
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
                          isSelected ? 'text-sky-600 dark:text-sky-300' : 'text-foreground'
                        )}
                      >
                        {option.label}
                      </span>
                      {option.badge && (
                        <span
                          className={cn(
                            'text-[10px] font-medium px-1.5 py-0.5 rounded',
                            isSelected
                              ? 'bg-sky-100 text-sky-600 dark:bg-sky-500/20 dark:text-sky-300'
                              : 'bg-muted text-muted-foreground'
                          )}
                        >
                          {option.badge}
                        </span>
                      )}
                      {option.value === 'paddle_vl' && availability === true && paddleVlVersionBadge ? (
                        <span
                          className={cn(
                            'text-[10px] font-medium px-1.5 py-0.5 rounded',
                            isSelected
                              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                              : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
                          )}
                        >
                          {paddleVlVersionBadge}
                        </span>
                      ) : null}
                    </div>
                    <p className="text-xs text-muted-foreground truncate">{option.description}</p>
                  </div>
                  {isDisabled && (
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-muted text-muted-foreground flex-shrink-0">
                      未启用
                    </span>
                  )}
                  {isSelected && (
                    <Check className="w-4 h-4 text-sky-600 dark:text-sky-300 flex-shrink-0" />
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
