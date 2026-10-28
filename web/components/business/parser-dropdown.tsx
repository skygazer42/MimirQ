'use client'

/**
 * Integrated pipeline 风格的解析器下拉选择组件
 * 带图标、描述和徽章的下拉菜单
 */
import { useState, useRef, useEffect, useMemo, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
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
} from '@/components/icons'
import { cn, detachPromise } from '@/lib/utils'
import { PARSER_BACKEND_OPTIONS, getParserOption } from '@/lib/parser-options'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { normalizeParserBackendName, resolveParserBackendForFilename } from '@/lib/parser-compat'
import { settingsApi } from '@/lib/api/settings'
import { queryKeys } from '@/lib/query-keys'
import { useDropdownPlacement, type DropdownSide } from '@/hooks/use-dropdown-placement'
import { pipelinePickerTokens } from '@/components/ui/system-page-tokens'

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

interface ParserDropdownProps {
  value: string
  onChange: (value: string) => void
  className?: string
  filename?: string
  compact?: boolean
  surface?: 'default' | 'ocean'
  side?: DropdownSide
}

type ParserStatusWithHealth = {
  health?: {
    pipeline_version?: unknown
    version?: unknown
  }
}

export function ParserDropdown({
  value,
  onChange,
  className,
  filename,
  compact = false,
  surface = 'default',
  side = 'bottom',
}: Readonly<ParserDropdownProps>) {
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const placement = useDropdownPlacement(isOpen && side === 'top', triggerRef, {
    side,
    align: compact ? 'end' : 'start',
    minWidth: compact ? 420 : 360,
    maxHeight: 440,
    onOpenChange: setIsOpen,
  })
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
  const resolvedSelectedColor =
    surface === 'ocean'
      ? { bg: 'bg-info/[0.08]', text: 'text-info' }
      : { bg: pipelinePickerTokens.iconFrame, text: 'text-muted-foreground' }

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
      if (!(event.target instanceof Node)) return
      if (dropdownRef.current?.contains(event.target) || menuRef.current?.contains(event.target)) return
      setIsOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // 常规菜单保留在原容器内，兼容对话框的焦点与点击范围。
  const renderMenu = (content: ReactNode) => side === 'top' ? createPortal(content, document.body) : content

  return (
    <div ref={dropdownRef} className={cn('relative select-none', className)}>
      {/* 触发按钮 */}
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'w-full flex items-center border transition-colors duration-150 motion-reduce:transition-none focus-ring',
          compact ? 'gap-2 px-2.5 py-1.5 rounded-full' : 'h-[60px] gap-2.5 rounded-lg px-3 py-2',
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
        <div className={cn('grid shrink-0 place-items-center rounded-md', compact ? 'size-6' : 'size-7', resolvedSelectedColor.bg)}>
          <SelectedIcon className={cn('size-3.5', resolvedSelectedColor.text)} />
        </div>
        <div className="flex-1 text-left min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn('font-medium text-foreground truncate', compact ? 'text-xs' : 'text-[13px]')}>
              {selectedOption.label}
            </span>
            {selectedOption.value === 'paddle_vl' && paddleVlVersionBadge ? (
              <span className="rounded bg-success/10 px-1.5 py-px text-[9px] font-medium leading-4 text-success">
                {paddleVlVersionBadge}
              </span>
            ) : null}
          </div>
          {!compact && (
            <p title={selectedOption.description} className="mt-0.5 truncate text-xs leading-4 text-muted-foreground">{selectedOption.description}</p>
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
      {isOpen && (side === 'bottom' || placement) && renderMenu(
        <div
          ref={menuRef}
          data-dropdown-menu="parser"
          data-side={side === 'top' ? placement?.side : 'bottom'}
          style={side === 'top' ? placement?.style : undefined}
          className={cn(
            'select-none overflow-y-auto overscroll-contain border no-scrollbar',
            side === 'top' ? 'fixed z-[1000]' : 'absolute z-50 mt-2 max-h-[min(440px,70vh)]',
            surface === 'ocean'
              ? 'rounded-lg border-info/30 bg-[linear-gradient(hsl(var(--info)/0.10),hsl(var(--info)/0.10)),linear-gradient(hsl(var(--popover)),hsl(var(--popover)))] text-popover-foreground shadow-strong'
              : pipelinePickerTokens.menu,
            side === 'bottom' && (compact ? 'right-0 w-[min(420px,calc(100vw-2rem))]' : 'w-full min-w-[360px]')
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
          <div className="p-1">
            {PARSER_BACKEND_OPTIONS.map((option) => {
              const Icon = ICON_MAP[option.icon]
              const resolvedColor =
                surface === 'ocean'
                  ? { bg: 'bg-info/[0.08]', text: 'text-info' }
                  : { bg: pipelinePickerTokens.iconFrame, text: 'text-muted-foreground' }
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
                    pipelinePickerTokens.row,
                    isSelected
                      ? surface === 'ocean' ? 'bg-info/[0.10]' : pipelinePickerTokens.selectedRow
                      : !isDisabled && (surface === 'ocean' ? 'hover:bg-info/[0.06]' : pipelinePickerTokens.idleRow),
                    isDisabled && 'cursor-not-allowed'
                  )}
                >
                  <div className={cn('grid size-7 shrink-0 place-items-center rounded-md', resolvedColor.bg)}>
                    <Icon className={cn('size-3.5', resolvedColor.text)} />
                  </div>
                  <div className="flex-1 text-left min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span
                        className={cn(
                          'text-[13px] font-medium leading-5',
                          isDisabled ? 'text-muted-foreground' : isSelected && surface === 'ocean' ? 'text-info' : 'text-foreground'
                        )}
                      >
                        {option.label}
                      </span>
                      {option.badge && (
                        <span
                          className={cn(
                            'rounded px-1.5 py-px text-[10px] font-medium leading-4',
                            surface === 'ocean' ? 'bg-info/[0.08] text-info' : pipelinePickerTokens.badge
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
                    <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{option.description}</p>
                  </div>
                  {isDisabled && (
                    <span className="shrink-0 text-[11px] leading-5 text-muted-foreground">
                      {disabledLabel}
                    </span>
                  )}
                  {isSelected && (
                    <Check
                      className={cn(
                        'size-4 flex-shrink-0',
                        surface === 'ocean' ? 'text-info' : 'text-foreground'
                      )}
                    />
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
