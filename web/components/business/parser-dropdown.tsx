'use client'

/**
 * Integrated pipeline 风格的解析器下拉选择组件
 * 带图标、描述和徽章的下拉菜单
 */
import { useState, useRef, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
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
import { queryKeys } from '@/lib/query-keys'

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
  auto: { bg: 'bg-primary/10', text: 'text-primary' },
  basic: { bg: 'bg-muted', text: 'text-muted-foreground' },
  docling: { bg: 'bg-info/10', text: 'text-info' },
  layout: { bg: 'bg-success/10', text: 'text-success' },
  mineru: { bg: 'bg-primary/10', text: 'text-primary' },
  deepdoc: { bg: 'bg-warning/10', text: 'text-warning' },
  deepseekocr: { bg: 'bg-destructive/10', text: 'text-destructive' },
  markitdown: { bg: 'bg-accent/10', text: 'text-accent' },
  magicpdf: { bg: 'bg-accent/10', text: 'text-accent' },
}

interface ParserDropdownProps {
  value: string
  onChange: (value: string) => void
  className?: string
  filename?: string
  compact?: boolean
}

type ParserStatusWithHealth = {
  health?: {
    pipeline_version?: unknown
    version?: unknown
  }
}

export function ParserDropdown({ value, onChange, className, filename, compact = false }: Readonly<ParserDropdownProps>) {
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const { capabilities, loading, error, refresh, parserBackendAvailable } = usePipelineCapabilities()
  const isPaddleVlAvailable = parserBackendAvailable('paddle_vl') === true

  const paddleVlStatusQuery = useQuery({
    queryKey: queryKeys.settings.status,
    queryFn: settingsApi.getStatus,
    enabled: isPaddleVlAvailable,
    staleTime: 60_000,
    retry: 1,
  })

  const parserNotesByName = new Map<string, string>()
  for (const info of capabilities?.pdf_backends || []) {
    const key = normalizeParserBackendName(info.name)
    const notes = (info.notes || '').trim()
    if (key && notes) parserNotesByName.set(key, notes)
  }

  const selectedOption = getParserOption(value)
  const SelectedIcon = ICON_MAP[selectedOption.icon]
  const selectedColor = COLOR_MAP[selectedOption.icon]

  const paddleVlVersionBadge = useMemo(() => {
    if (!isPaddleVlAvailable) return null
    const parserStatus = paddleVlStatusQuery.data?.parsers?.paddle_vl as ParserStatusWithHealth | undefined
    const health = parserStatus?.health
    const version =
      typeof health?.pipeline_version === 'string'
        ? health.pipeline_version
        : typeof health?.version === 'string'
          ? health.version
          : ''
    return version ? `PaddleOCR-VL ${version}` : null
  }, [isPaddleVlAvailable, paddleVlStatusQuery.data])

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
          'w-full flex items-center border transition-colors duration-150 motion-reduce:transition-none',
          compact ? 'gap-2 px-2.5 py-1.5 rounded-full' : 'gap-2.5 px-2.5 py-2 rounded-xl',
          'bg-card hover:bg-muted',
          isOpen
            ? 'border-primary/30 ring-2 ring-primary/10'
            : 'border-border hover:border-border'
        )}
      >
        <div className={cn(compact ? 'rounded-md p-1' : 'rounded-md p-1.5', selectedColor.bg)}>
          <SelectedIcon className={cn('size-3.5', selectedColor.text)} />
        </div>
        <div className="flex-1 text-left min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn('font-medium text-foreground truncate', compact ? 'text-xs' : 'text-[13px]')}>
              {selectedOption.label}
            </span>
            {selectedOption.badge && (
              <span className="rounded bg-primary/10 px-1.5 py-px text-[9px] font-medium leading-4 text-primary">
                {selectedOption.badge}
              </span>
            )}
            {selectedOption.value === 'paddle_vl' && paddleVlVersionBadge ? (
              <span className="rounded bg-success/10 px-1.5 py-px text-[9px] font-medium leading-4 text-success">
                {paddleVlVersionBadge}
              </span>
            ) : null}
          </div>
          {!compact && (
            <p className="mt-0.5 truncate text-[11px] leading-4 text-muted-foreground">{selectedOption.description}</p>
          )}
        </div>
        <ChevronDown
          className={cn(
            'size-3.5 text-muted-foreground transition-transform flex-shrink-0',
            isOpen && 'rotate-180'
          )}
        />
      </button>

      {/* 下拉菜单 */}
      {isOpen && (
        <div
          className={cn(
            'absolute z-50 mt-2 max-h-[min(440px,70vh)] overflow-y-auto overscroll-contain rounded-2xl border border-border bg-card shadow-strong no-scrollbar',
            compact ? 'right-0 w-[min(420px,calc(100vw-2rem))]' : 'w-full min-w-[360px]'
          )}
        >
          {(loading || error) && (
            <div
              className={cn(
                'px-3 py-2 text-xs border-b',
                error
                  ? 'bg-destructive/10 text-destructive border-destructive/25'
                  : 'bg-muted text-muted-foreground border-border'
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  {loading ? '正在加载后端解析器能力…' : '无法获取后端解析器能力，部分选项可能不可用'}
                </div>
                {error ? (
                  <button
                    type="button"
                    className="flex-shrink-0 text-xs text-destructive hover:text-destructive/80 underline underline-offset-2"
                    onClick={() => {
                      detachPromise(refresh())
                    }}
                  >
                    重试
                  </button>
                ) : null}
              </div>
              {error ? (
                <div className="mt-1 truncate text-[11px] text-destructive/80" title={error}>
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
              const disabledLabel = isDisabledByFile ? '不适用' : '未启用'

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
                    isSelected ? 'bg-primary/10' : 'hover:bg-muted',
                    isDisabled && 'opacity-50 cursor-not-allowed hover:bg-transparent'
                  )}
                >
                  <div className={cn('p-1.5 rounded-lg', color.bg)}>
                    <Icon className={cn('size-4', color.text)} />
                  </div>
                  <div className="flex-1 text-left min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          'text-sm font-medium truncate',
                          isSelected ? 'text-primary' : 'text-foreground'
                        )}
                      >
                        {option.label}
                      </span>
                      {option.badge && (
                        <span
                          className={cn(
                            'text-[11px] font-medium px-1.5 py-0.5 rounded',
                            isSelected
                              ? 'bg-primary/10 text-primary'
                              : 'bg-muted text-muted-foreground'
                          )}
                        >
                          {option.badge}
                        </span>
                      )}
                      {option.value === 'paddle_vl' && availability === true && paddleVlVersionBadge ? (
                        <span
                          className={cn(
                            'text-[11px] font-medium px-1.5 py-0.5 rounded',
                            isSelected
                              ? 'bg-success/10 text-success'
                              : 'bg-success/8 text-success'
                          )}
                        >
                          {paddleVlVersionBadge}
                        </span>
                      ) : null}
                    </div>
                    <p className="text-xs leading-5 text-muted-foreground">{option.description}</p>
                  </div>
                  {isDisabled && (
                    <span className="text-[11px] font-medium px-1.5 py-0.5 rounded bg-muted text-muted-foreground flex-shrink-0">
                      {disabledLabel}
                    </span>
                  )}
                  {isSelected && (
                    <Check className="size-4 flex-shrink-0 text-primary" />
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
