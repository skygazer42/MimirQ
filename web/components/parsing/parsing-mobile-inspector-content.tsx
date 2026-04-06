'use client'

import { Code, Copy, Download, Eye, FileStack, FileText } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { Button } from '@/components/ui/button'
import { buildParsingLayoutEntries, getParsingLayoutMeta } from '@/lib/parsing-layout'
import { cn } from '@/lib/utils'
import type { ParsingBlock } from '@/lib/parsing-positions'

type ParsingMobileInspectorContentProps = {
  activeMarkdown: string
  rightPanelMode: 'blocks' | 'markdown'
  previewMode: 'raw' | 'rendered'
  activeBlocksWithPositions: ParsingBlock[]
  activeBlockId: string | null
  onRightPanelModeChange: (mode: 'blocks' | 'markdown') => void
  onPreviewModeChange: (mode: 'raw' | 'rendered') => void
  onSelectBlock: (blockId: string) => void
  onCopyMarkdown: () => void
  onDownloadMarkdown: () => void
}

export function ParsingMobileInspectorContent({
  activeMarkdown,
  rightPanelMode,
  previewMode,
  activeBlocksWithPositions,
  activeBlockId,
  onRightPanelModeChange,
  onPreviewModeChange,
  onSelectBlock,
  onCopyMarkdown,
  onDownloadMarkdown,
}: Readonly<ParsingMobileInspectorContentProps>) {
  const t = useTranslations('ParsingWorkbench')
  const layoutEntries = buildParsingLayoutEntries(activeBlocksWithPositions)

  return (
    <div className="flex-1 min-h-0 space-y-5 overflow-y-auto overscroll-contain no-scrollbar bg-muted/10 p-4">
      <div className="space-y-2">
        <div className="text-xs font-semibold text-muted-foreground">{t('mobileInspector.view')}</div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant={rightPanelMode === 'blocks' ? 'default' : 'outline'}
            className="gap-2"
            onClick={() => onRightPanelModeChange('blocks')}
            disabled={activeBlocksWithPositions.length === 0}
          >
            <FileStack className="h-4 w-4" />
            {t('mobileInspector.layout')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={rightPanelMode === 'markdown' ? 'default' : 'outline'}
            className="gap-2"
            onClick={() => onRightPanelModeChange('markdown')}
          >
            <FileText className="h-4 w-4" />
            {t('mobileInspector.markdown')}
          </Button>

          {rightPanelMode === 'markdown' ? (
            <>
              <div className="mx-1 h-5 w-px bg-border/60" aria-hidden="true" />
              <Button
                type="button"
                size="sm"
                variant={previewMode === 'rendered' ? 'default' : 'outline'}
                className="gap-2"
                onClick={() => onPreviewModeChange('rendered')}
              >
                <Eye className="h-4 w-4" />
                {t('mobileInspector.preview')}
              </Button>
              <Button
                type="button"
                size="sm"
                variant={previewMode === 'raw' ? 'default' : 'outline'}
                className="gap-2"
                onClick={() => onPreviewModeChange('raw')}
              >
                <Code className="h-4 w-4" />
                {t('mobileInspector.source')}
              </Button>
            </>
          ) : null}
        </div>
      </div>

      {rightPanelMode === 'blocks' && layoutEntries.length > 0 ? (
        <div className="space-y-2">
          <div className="text-xs font-semibold text-muted-foreground">{t('mobileInspector.blocks')}</div>
          <div className="rounded-2xl border border-border/60 bg-card p-2">
            <div className="max-h-[46vh] space-y-1 overflow-y-auto overscroll-contain no-scrollbar">
              {layoutEntries.slice(0, 80).map((entry, idx) => {
                const layoutMeta = getParsingLayoutMeta(entry.kind)
                const isActive = entry.id === activeBlockId
                return (
                  <button
                    key={entry.id}
                    type="button"
                    onClick={() => onSelectBlock(entry.id)}
                    className={cn(
                      'w-full rounded-xl border px-3 py-2 text-left text-sm transition-colors',
                      isActive
                        ? 'border-sky-400 bg-sky-50 dark:bg-sky-950/30'
                        : 'border-border/50 hover:bg-muted/40'
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0 space-y-1">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className={cn('h-1.5 w-1.5 rounded-full', layoutMeta.dotClassName)} />
                          <div className="truncate font-medium">
                            {t('mobileInspector.blockLabel', { index: String(idx + 1) })}
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span
                            className={cn(
                              'inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium',
                              layoutMeta.chipClassName
                            )}
                          >
                            {layoutMeta.shortLabel}
                          </span>
                        </div>
                      </div>
                      <div className="font-mono text-[11px] tabular-nums text-muted-foreground">
                        {Number.isFinite(entry.pageIndex)
                          ? t('mobileInspector.pageLabel', { page: String(Number(entry.pageIndex) + 1) })
                          : ''}
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      ) : rightPanelMode === 'markdown' ? (
        <div className="space-y-2">
          <div className="text-xs font-semibold text-muted-foreground">{t('mobileInspector.toc')}</div>
          <div className="rounded-2xl border border-border/60 bg-card p-3">
            <MarkdownToc markdown={activeMarkdown} />
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        <div className="text-xs font-semibold text-muted-foreground">{t('mobileInspector.quickActions')}</div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" className="gap-2" onClick={onCopyMarkdown}>
            <Copy className="h-4 w-4" />
            {t('mobileInspector.copyMarkdown')}
          </Button>
          <Button type="button" variant="outline" size="sm" className="gap-2" onClick={onDownloadMarkdown}>
            <Download className="h-4 w-4" />
            {t('mobileInspector.downloadMarkdown')}
          </Button>
        </div>
      </div>
    </div>
  )
}
