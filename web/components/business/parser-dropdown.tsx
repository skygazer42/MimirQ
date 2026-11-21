'use client'

import { useState } from 'react'
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
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { pipelinePickerTokens } from '@/components/ui/system-page-tokens'

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

type ParserDropdownProps = {
  value: string
  onChange: (value: string) => void
  filename?: string
  compact?: boolean
  side?: 'bottom' | 'top'
}

export function ParserDropdown({
  value,
  onChange,
  filename,
  compact = false,
  side = 'bottom',
}: Readonly<ParserDropdownProps>) {
  const [isOpen, setIsOpen] = useState(false)
  const { capabilities, loading, error, refresh, parserBackendAvailable } = usePipelineCapabilities()
  const selectedOption = getParserOption(value)
  const isPaddleVlAvailable = parserBackendAvailable('paddle_vl') === true

  const paddleVlStatusQuery = useQuery({
    queryKey: queryKeys.settings.status,
    queryFn: ({ signal }) => settingsApi.getStatus({ signal }),
    enabled: isPaddleVlAvailable && (isOpen || selectedOption.value === 'paddle_vl'),
    staleTime: 60_000,
    retry: 1,
  })
  const health = paddleVlStatusQuery.data?.parsers?.paddle_vl?.health
  const version = typeof health?.pipeline_version === 'string' ? health.pipeline_version : health?.version
  const paddleVlVersionBadge =
    isPaddleVlAvailable && typeof version === 'string' && version.length > 0 ? `PaddleOCR-VL ${version}` : null

  const parserNotesByName = new Map<string, string>()
  if (isOpen && capabilities) {
    for (const info of capabilities.pdf_backends) {
      const notes = info.notes?.trim()
      if (notes !== undefined && notes.length > 0) {
        parserNotesByName.set(normalizeParserBackendName(info.name), notes)
      }
    }
  }

  const SelectedIcon = ICON_MAP[selectedOption.icon]

  return (
    <Popover modal open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'w-full flex items-center border transition-colors duration-150 motion-reduce:transition-none focus-ring',
            compact ? 'gap-2 px-2.5 py-1.5 rounded-full' : 'h-[60px] gap-2.5 rounded-lg px-3 py-2',
            pipelinePickerTokens.trigger,
            isOpen ? 'border-input ring-2 ring-foreground/10' : 'hover:border-border',
          )}
        >
          <span
            className={cn(
              'grid shrink-0 place-items-center rounded-md',
              compact ? 'size-6' : 'size-7',
              pipelinePickerTokens.iconFrame,
            )}
          >
            <SelectedIcon className="size-3.5 text-muted-foreground" />
          </span>
          <span className="min-w-0 flex-1 text-left">
            <span className="flex items-center gap-2">
              <span className={cn('font-medium text-foreground truncate', compact ? 'text-xs' : 'text-[13px]')}>
                {selectedOption.label}
              </span>
              {selectedOption.value === 'paddle_vl' && paddleVlVersionBadge ? (
                <span className="rounded bg-success/10 px-1.5 py-px text-[9px] font-medium leading-4 text-success">
                  {paddleVlVersionBadge}
                </span>
              ) : null}
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
            className={cn('size-3.5 text-muted-foreground transition-transform flex-shrink-0', isOpen && 'rotate-180')}
          />
        </button>
      </PopoverTrigger>

      <PopoverContent
        data-dropdown-menu="parser"
        aria-label="选择解析器"
        align={compact ? 'end' : 'start'}
        side={side}
        sideOffset={8}
        collisionPadding={12}
        className={cn(
          'z-[1000] max-h-[min(440px,var(--radix-popover-content-available-height))] max-w-[var(--radix-popover-content-available-width)] select-none overflow-y-auto overscroll-contain p-0 no-scrollbar',
          compact
            ? 'w-[max(420px,var(--radix-popover-trigger-width))]'
            : 'w-[max(360px,var(--radix-popover-trigger-width))]',
          pipelinePickerTokens.menu,
        )}
      >
        {(loading || error) && (
          <div
            className={cn(
              'px-3 py-2 text-xs border-b',
              error
                ? 'bg-destructive/10 text-destructive border-destructive/25'
                : 'bg-muted text-muted-foreground border-border',
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
            const isSelected = option.value === selectedOption.value
            const availability = parserBackendAvailable(option.value)
            const isDisabledByFile =
              filename !== undefined &&
              filename.length > 0 &&
              option.value !== 'auto' &&
              resolveParserBackendForFilename(filename, option.value).backend !== option.value
            const isDisabledByCapabilities =
              option.value !== 'auto' && option.value !== 'basic' && availability !== true
            const isDisabled = isDisabledByFile || isDisabledByCapabilities
            const notes = parserNotesByName.get(normalizeParserBackendName(option.value))
            const disabledTitle = isDisabledByFile
              ? '该文件类型不支持此解析器'
              : (notes ?? '后端未启用该解析器（可到“设置”开启/配置）')
            const disabledLabel = isDisabledByFile ? '不适用' : '未启用'

            return (
              <button
                key={option.value}
                type="button"
                disabled={isDisabled}
                aria-pressed={isSelected}
                title={isDisabled ? disabledTitle : undefined}
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
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span
                      className={cn(
                        'text-[13px] font-medium leading-5',
                        isDisabled ? 'text-muted-foreground' : 'text-foreground',
                      )}
                    >
                      {option.label}
                    </span>
                    {option.badge && (
                      <span
                        className={cn(
                          'rounded px-1.5 py-px text-[10px] font-medium leading-4',
                          pipelinePickerTokens.badge,
                        )}
                      >
                        {option.badge}
                      </span>
                    )}
                    {option.value === 'paddle_vl' && availability === true && paddleVlVersionBadge ? (
                      <span
                        className={cn(
                          'text-[11px] font-medium px-1.5 py-0.5 rounded',
                          isSelected ? 'bg-success/10 text-success' : 'bg-success/8 text-success',
                        )}
                      >
                        {paddleVlVersionBadge}
                      </span>
                    ) : null}
                  </span>
                  <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">{option.description}</span>
                </span>
                {isDisabled && (
                  <span className="shrink-0 text-[11px] leading-5 text-muted-foreground">{disabledLabel}</span>
                )}
                {isSelected && <Check className="size-4 flex-shrink-0 text-foreground" />}
              </button>
            )
          })}
        </div>
      </PopoverContent>
    </Popover>
  )
}
