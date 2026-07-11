'use client'

import { Code, Copy, Download, Eye, FileStack, FileText } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { ParsingExtractPanel } from '@/components/parsing/parsing-extract-panel'
import { Button } from '@/components/ui/button'
import { buildParsingLayoutEntries, getParsingLayoutMeta } from '@/lib/parsing-layout'
import type { ParsingElement, ParsingExtractEvidence } from '@/lib/api/parsing'
import { cn } from '@/lib/utils'
import type { ParsingBlock } from '@/lib/parsing-positions'

type ParsingMobileInspectorContentProps = {
 documentId?: string | null
 activeMarkdown: string
 rightPanelMode: 'blocks' | 'markdown'
 previewMode: 'raw' | 'rendered'
 activeBlocksWithPositions: ParsingBlock[]
 activeBlockId: string | null
 activeElements: ParsingElement[]
 onRightPanelModeChange: (mode: 'blocks' | 'markdown') => void
 onPreviewModeChange: (mode: 'raw' | 'rendered') => void
 onSelectBlock: (blockId: string) => void
 onSelectElement: (elementId: string) => void
 onSelectEvidence: (payload: { fieldName: string; evidence: ParsingExtractEvidence }) => void
 onCopyMarkdown: () => void
 onDownloadMarkdown: () => void
}

export function ParsingMobileInspectorContent({
 documentId,
 activeMarkdown,
 rightPanelMode,
 previewMode,
 activeBlocksWithPositions,
 activeBlockId,
 activeElements,
 onRightPanelModeChange,
 onPreviewModeChange,
 onSelectBlock,
 onSelectElement,
 onSelectEvidence,
 onCopyMarkdown,
 onDownloadMarkdown,
}: Readonly<ParsingMobileInspectorContentProps>) {
 const t = useTranslations('ParsingWorkbench')
 const layoutEntries = buildParsingLayoutEntries(activeBlocksWithPositions)

 const formatElementPages = (element: ParsingElement): string => {
 const pages = Array.isArray(element.pages)
 ? element.pages.filter((value) => Number.isInteger(value) && value > 0)
 : []
 if (pages.length >= 2) {
 if (pages.length === 2 && pages[1] === pages[0] + 1) {
 return t('mobileInspector.pageLabel', { page: `${pages[0]}-${pages[1]}` })
 }
 return t('mobileInspector.pageLabel', { page: pages.join(',') })
 }
 if (typeof element.page === 'number') {
 return t('mobileInspector.pageLabel', { page: String(element.page) })
 }
 return ''
 }

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
 ? 'border-info bg-info/10 dark:bg-sky-950/30'
 : 'border-border/60 hover:bg-muted/40'
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
 'inline-flex items-center rounded-full border px-1.5 py-0.5 text-[11px] font-medium',
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
 {documentId ? (
 <ParsingExtractPanel
 documentId={documentId}
 activeElements={activeElements}
 onSelectEvidence={onSelectEvidence}
 className="rounded-2xl border border-border/60 bg-card p-0"
 />
 ) : null}
 {activeElements.length > 0 ? (
 <div className="space-y-2">
 <div className="text-xs font-semibold text-muted-foreground">{t('mobileInspector.elements')}</div>
 <div className="rounded-2xl border border-border/60 bg-card p-2">
 <div className="max-h-[32vh] space-y-1 overflow-y-auto overscroll-contain no-scrollbar">
 {activeElements.slice(0, 40).map((element) => (
 <button
 key={String(element.id)}
 type="button"
 onClick={() => onSelectElement(String(element.id))}
 className="w-full rounded-xl border border-border/60 px-3 py-2 text-left text-sm transition-colors hover:bg-muted/40"
 >
 <div className="flex items-center justify-between gap-3">
 <div className="min-w-0">
 <div className="flex flex-wrap items-center gap-1.5">
 <div className="truncate font-medium text-foreground/85">{String(element.kind || 'paragraph')}</div>
 {element.visual_kind ? (
 <span className="inline-flex items-center rounded-full border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
 {element.visual_kind}
 </span>
 ) : null}
 </div>
 {element.text ? <div className="truncate text-xs text-muted-foreground">{String(element.text)}</div> : null}
 </div>
 {formatElementPages(element) ? (
 <div className="font-mono text-[11px] tabular-nums text-muted-foreground">{formatElementPages(element)}</div>
 ) : null}
 </div>
 </button>
 ))}
 </div>
 </div>
 </div>
 ) : null}
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
