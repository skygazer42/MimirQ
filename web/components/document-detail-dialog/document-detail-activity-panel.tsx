'use client'

import { useEffect, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Ban, Calendar, CheckCircle2, Copy, FileText, GitBranch, Loader2, Pencil, RefreshCw, Save, Search, X } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { lineageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, formatDate } from '@/lib/utils'
import type { Document, DocumentChunk, DocumentTimelineItem, DocumentVersionList } from '@/types'

const ACTIVE_PIPELINE_VALUE = '__active__'

type VirtualItemLike = {
  key: string | number | bigint
  index: number
  start: number
}

type VirtualizerLike = {
  getTotalSize: () => number
  getVirtualItems: () => VirtualItemLike[]
  measureElement: (node: Element | null) => void
}

type DocumentDetailActivityPanelProps = Readonly<{
  activeView: 'chunks' | 'timeline'
  onActiveViewChange: (next: 'chunks' | 'timeline') => void
  chunksTabId: string
  timelineTabId: string
  chunksPanelId: string
  timelinePanelId: string
  scrollParentRef: RefObject<HTMLDivElement | null>
  onViewTabKeyDown: (event: ReactKeyboardEvent<HTMLButtonElement>) => void
  chunkQuery: string
  onChunkQueryChange: (next: string) => void
  versions: DocumentVersionList | null
  viewPipelineHash: string
  onViewPipelineHashChange: (next: string) => void
  chunks: DocumentChunk[]
  chunksTotal: number
  isLoadingDoc: boolean
  detail: Document | null
  isLoadingChunks: boolean
  loadError: string | null
  onRetryChunks: () => void
  onClose: () => void
  isSearching: boolean
  chunkError: string | null
  chunkRowVirtualizer: VirtualizerLike
  canMutateChunks: boolean
  chunkOpWorkingId: string | null
  onBeginEditChunk: (chunk: DocumentChunk) => void
  onToggleChunkDisabled: (chunk: DocumentChunk) => void
  onReembedChunk: (chunk: DocumentChunk) => void
  onCopyText: (text: string) => void
  editingChunkId: string | null
  editingChunkContent: string
  onEditingChunkContentChange: (next: string) => void
  onCancelEditChunk: () => void
  onSaveEditChunk: () => void
  canLoadMoreChunks: boolean
  onLoadMoreChunks: () => void
  timelineItems: DocumentTimelineItem[]
  timelineTotal: number
  isLoadingTimeline: boolean
  timelineError: string | null
  docError: string | null
  onLoadTimeline: () => void
  timelineRowVirtualizer: VirtualizerLike
}>

function highlightText(text: string, query: string) {
  const needle = query.trim()
  if (!needle) return text

  const haystackLower = text.toLowerCase()
  const needleLower = needle.toLowerCase()
  const nodes: Array<string | ReactNode> = []
  let cursor = 0

  while (cursor < text.length) {
    const matchAt = haystackLower.indexOf(needleLower, cursor)
    if (matchAt === -1) {
      nodes.push(text.slice(cursor))
      break
    }

    if (matchAt > cursor) {
      nodes.push(text.slice(cursor, matchAt))
    }

    const matched = text.slice(matchAt, matchAt + needle.length)
    nodes.push(
      <mark key={`${matchAt}-${matched.length}`} className="rounded bg-primary/15 px-0.5 text-foreground">
        {matched}
      </mark>
    )

    cursor = matchAt + needle.length
  }

  return nodes
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function ChunkLineageButton({ chunkId }: Readonly<{ chunkId: string }>) {
  const [open, setOpen] = useState(false)
  const lineageQuery = useQuery({
    queryKey: queryKeys.lineage.chunk(chunkId),
    enabled: open,
    queryFn: () => lineageApi.getChunkLineage(chunkId),
  })
  const error = lineageQuery.error
    ? formatApiError(lineageQuery.error, '加载 Chunk 血缘失败')
    : null

  useEffect(() => {
    if (!error) return
    toast.error(error)
  }, [error])

  return (
    <>
      <IconButton
        label="查看 Chunk 血缘"
        variant="ghost"
        className="h-9 w-9 text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(true)}
      >
        {lineageQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <GitBranch className="h-4 w-4" />}
      </IconButton>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-3xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-info" />
              Chunk Lineage
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">chunk_id={chunkId}</DialogDescription>
          </DialogHeader>
          {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null}
          <pre className={cn('max-h-[520px] overflow-auto rounded-lg border border-border/60 bg-muted/20 p-3 text-xs', 'whitespace-pre-wrap break-words')}>
            {lineageQuery.isFetching ? 'Loading...' : prettyJson(lineageQuery.data ?? { message: '暂无 Chunk 血缘数据' })}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function DocumentDetailActivityPanel({
  activeView,
  onActiveViewChange,
  chunksTabId,
  timelineTabId,
  chunksPanelId,
  timelinePanelId,
  scrollParentRef,
  onViewTabKeyDown,
  chunkQuery,
  onChunkQueryChange,
  versions,
  viewPipelineHash,
  onViewPipelineHashChange,
  chunks,
  chunksTotal,
  isLoadingDoc,
  detail,
  isLoadingChunks,
  loadError,
  onRetryChunks,
  onClose,
  isSearching,
  chunkError,
  chunkRowVirtualizer,
  canMutateChunks,
  chunkOpWorkingId,
  onBeginEditChunk,
  onToggleChunkDisabled,
  onReembedChunk,
  onCopyText,
  editingChunkId,
  editingChunkContent,
  onEditingChunkContentChange,
  onCancelEditChunk,
  onSaveEditChunk,
  canLoadMoreChunks,
  onLoadMoreChunks,
  timelineItems,
  timelineTotal,
  isLoadingTimeline,
  timelineError,
  docError,
  onLoadTimeline,
  timelineRowVirtualizer,
}: DocumentDetailActivityPanelProps) {
  const commonT = useTranslations('Common')
  const documentsT = useTranslations('Documents')
  const t = useTranslations('DocumentDetailDialog')

  const renderChunksContent = () => {
    if ((isLoadingDoc && !detail) || (isLoadingChunks && chunks.length === 0)) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
          <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
          <p className="text-sm">{documentsT('loadingChunks')}</p>
        </div>
      )
    }

    if (loadError && chunks.length === 0) {
      return (
        <div className="mx-auto max-w-2xl py-10">
          <Alert variant="destructive">
            <AlertTitle>{t('alerts.loadFailedTitle')}</AlertTitle>
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
          <div className="mt-4 flex items-center justify-end gap-2">
            <Button variant="outline" onClick={onRetryChunks}>
              {commonT('retry')}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              {commonT('close')}
            </Button>
          </div>
        </div>
      )
    }

    if (chunksTotal === 0 && !isSearching) {
      return (
        <EmptyState
          icon={FileText}
          title={documentsT('emptyChunks')}
          description={t('chunks.emptyDescription')}
          className="min-h-[320px]"
        />
      )
    }

    if (chunksTotal === 0 && isSearching) {
      return (
        <EmptyState
          icon={Search}
          title={t('chunks.searchEmptyTitle')}
          description={<span>{t('chunks.searchEmptyDescription')}</span>}
          className="min-h-[320px]"
        >
          <Button variant="outline" onClick={() => onChunkQueryChange('')}>
            {t('chunks.clearFilter')}
          </Button>
        </EmptyState>
      )
    }

    return (
      <div className="pb-6 space-y-3">
        {chunkError && chunks.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>{t('alerts.loadChunksFailedTitle')}</AlertTitle>
            <AlertDescription>{chunkError}</AlertDescription>
          </Alert>
        ) : null}

        <ul
          aria-label={t('chunks.listAriaLabel')}
          className="m-0 list-none p-0"
          style={{ height: `${chunkRowVirtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}
        >
          {chunkRowVirtualizer.getVirtualItems().map((virtualRow) => {
            const chunk = chunks[virtualRow.index]
            if (!chunk) return null

            return (
              <li
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={chunkRowVirtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                className="pb-3"
              >
                <div
                  className={cn(
                    'group rounded-xl border border-border/60 bg-card p-4 transition-colors',
                    'hover:border-primary/25 hover:shadow-soft/30',
                    chunk.disabled_at ? 'opacity-70' : null
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono font-medium text-muted-foreground">
                        #{chunk.chunk_index}
                      </span>
                      {typeof chunk.page_number === 'number' ? (
                        <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
                          P.{chunk.page_number}
                        </span>
                      ) : null}
                      <span className="text-muted-foreground">{t('chunks.charCount', { count: (chunk.content || '').length })}</span>
                      {chunk.disabled_at ? (
                        <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
                          {t('chunks.disabledBadge')}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-1">
                      <IconButton
                        label={canMutateChunks ? t('chunks.actions.edit') : t('chunks.actions.editDisabled')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onBeginEditChunk(chunk)}
                        disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}
                      >
                        <Pencil className="h-4 w-4" />
                      </IconButton>
                      <IconButton
                        label={chunk.disabled_at ? t('chunks.actions.enable') : t('chunks.actions.disable')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onToggleChunkDisabled(chunk)}
                        disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}
                      >
                        {chunk.disabled_at ? <CheckCircle2 className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
                      </IconButton>
                      <IconButton
                        label={chunk.disabled_at ? t('chunks.actions.reembedDisabled') : t('chunks.actions.reembed')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onReembedChunk(chunk)}
                        disabled={!canMutateChunks || Boolean(chunk.disabled_at) || chunkOpWorkingId === chunk.id}
                      >
                        <RefreshCw className="h-4 w-4" />
                      </IconButton>
                      <ChunkLineageButton chunkId={chunk.id} />
                      <IconButton
                        label={t('chunks.actions.copy')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onCopyText(chunk.content || '')}
                        disabled={chunkOpWorkingId === chunk.id}
                      >
                        <Copy className="h-4 w-4" />
                      </IconButton>
                    </div>
                  </div>

                  {editingChunkId === chunk.id ? (
                    <div className="mt-3 space-y-2">
                      <Textarea
                        value={editingChunkContent}
                        onChange={(e) => onEditingChunkContentChange(e.target.value)}
                        className="min-h-[140px] font-mono text-xs"
                        disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}
                      />
                      <div className="flex items-center justify-end gap-2">
                        <Button type="button" variant="outline" size="sm" onClick={onCancelEditChunk} disabled={chunkOpWorkingId === chunk.id}>
                          {commonT('cancel')}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          onClick={onSaveEditChunk}
                          disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}
                          className="gap-2"
                        >
                          {chunkOpWorkingId === chunk.id ? (
                            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                          ) : (
                            <Save className="h-4 w-4" />
                          )}
                          {commonT('save')}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/90">
                      {highlightText(chunk.content || '', chunkQuery)}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ul>

        {canLoadMoreChunks ? (
          <div className="flex justify-center pt-2">
            <Button variant="outline" onClick={onLoadMoreChunks} disabled={isLoadingChunks} className="gap-2">
              {isLoadingChunks ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
              {t('chunks.loadMore')}
            </Button>
          </div>
        ) : null}
      </div>
    )
  }

  const renderTimelineContent = () => {
    if (isLoadingTimeline && timelineItems.length === 0) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
          <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
          <p className="text-sm">{documentsT('loadingTimeline')}</p>
        </div>
      )
    }

    if ((timelineError || docError) && timelineItems.length === 0) {
      return (
        <div className="mx-auto max-w-2xl py-10">
          <Alert variant="destructive">
            <AlertTitle>{t('alerts.loadFailedTitle')}</AlertTitle>
            <AlertDescription>{timelineError || docError}</AlertDescription>
          </Alert>
          <div className="mt-4 flex items-center justify-end gap-2">
            <Button variant="outline" onClick={onLoadTimeline}>
              {commonT('retry')}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              {commonT('close')}
            </Button>
          </div>
        </div>
      )
    }

    if (timelineItems.length === 0) {
      return (
        <EmptyState
          icon={Calendar}
          title={documentsT('emptyTimeline')}
          description={t('timeline.emptyDescription')}
          className="min-h-[320px]"
        />
      )
    }

    return (
      <div className="pb-6 space-y-3">
        {timelineError ? (
          <Alert variant="destructive">
            <AlertTitle>{t('alerts.loadTimelineFailedTitle')}</AlertTitle>
            <AlertDescription>{timelineError}</AlertDescription>
          </Alert>
        ) : null}

        <ul
          aria-label={t('timeline.listAriaLabel')}
          className="m-0 list-none p-0"
          style={{ height: `${timelineRowVirtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}
        >
          {timelineRowVirtualizer.getVirtualItems().map((virtualRow) => {
            const ev = timelineItems[virtualRow.index]
            if (!ev) return null

            const detailPairs = Object.entries(ev.details || {}).slice(0, 12)
            const hasDetails = detailPairs.length > 0

            return (
              <li
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={timelineRowVirtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                className="pb-3"
              >
                <div className={cn('group rounded-xl border border-border/60 bg-card p-4 transition-colors', 'hover:border-primary/25 hover:shadow-soft/30')}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
                          {formatDate(ev.created_at)}
                        </span>
                        <span className="truncate font-mono text-xs text-foreground/90">{ev.action}</span>
                        {ev.source === 'synthetic' ? (
                          <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-xs text-muted-foreground">
                            {t('timeline.synthetic')}
                          </span>
                        ) : null}
                      </div>

                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {ev.stage ? <span>{t('timeline.meta.stage')}: {ev.stage}</span> : null}
                        {ev.status ? <span>{t('timeline.meta.status')}: {ev.status}</span> : null}
                        {typeof ev.progress === 'number' ? <span>{t('timeline.meta.progress')}: {ev.progress}%</span> : null}
                        {ev.request_id ? (
                          <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 font-mono">
                            {t('timeline.meta.requestId')}: {ev.request_id}
                          </span>
                        ) : null}
                        {ev.actor_id ? (
                          <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 font-mono">
                            {t('timeline.meta.actorId')}: {ev.actor_id}
                          </span>
                        ) : null}
                      </div>
                    </div>

                    <IconButton
                      label={t('timeline.actions.copyEvent')}
                      variant="ghost"
                      className="h-9 w-9 text-muted-foreground hover:text-foreground"
                      onClick={() =>
                        onCopyText(
                          JSON.stringify(
                            {
                              id: ev.id,
                              action: ev.action,
                              created_at: ev.created_at,
                              stage: ev.stage,
                              status: ev.status,
                              progress: ev.progress,
                              request_id: ev.request_id,
                              actor_id: ev.actor_id,
                              details: ev.details,
                            },
                            null,
                            2
                          )
                        )
                      }
                    >
                      <Copy className="h-4 w-4" />
                    </IconButton>
                  </div>

                  {hasDetails ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {detailPairs.map(([key, value]) => (
                        <span
                          key={`${ev.id}:${key}`}
                          className="rounded-md border border-border/60 bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground"
                          title={`${key}: ${String(value)}`}
                        >
                          {key}: {String(value)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    )
  }

  return (
    <Panel padding="none" className="flex-1 min-h-0 overflow-hidden rounded-2xl">
      <div className="flex items-center gap-3 border-b border-border/60 bg-background/40 px-4 py-3">
        <div
          className="inline-flex h-10 items-center rounded-md bg-muted p-1 text-muted-foreground"
          role="tablist"
          aria-label={t('views.ariaLabel')}
        >
          <button
            type="button"
            id={chunksTabId}
            role="tab"
            aria-controls={chunksPanelId}
            aria-selected={activeView === 'chunks'}
            tabIndex={activeView === 'chunks' ? 0 : -1}
            className={cn(
              'inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none',
              activeView === 'chunks' ? 'bg-background text-foreground shadow-sm' : 'hover:text-foreground'
            )}
            onClick={() => onActiveViewChange('chunks')}
            onKeyDown={onViewTabKeyDown}
          >
            {t('views.chunks')}
          </button>
          <button
            type="button"
            id={timelineTabId}
            role="tab"
            aria-controls={timelinePanelId}
            aria-selected={activeView === 'timeline'}
            tabIndex={activeView === 'timeline' ? 0 : -1}
            className={cn(
              'inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none',
              activeView === 'timeline' ? 'bg-background text-foreground shadow-sm' : 'hover:text-foreground'
            )}
            onClick={() => onActiveViewChange('timeline')}
            onKeyDown={onViewTabKeyDown}
          >
            {t('views.timeline')}
          </button>
        </div>

        {activeView === 'chunks' ? (
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={chunkQuery}
              onChange={(e) => onChunkQueryChange(e.target.value)}
              placeholder={t('search.placeholder')}
              className="h-10 pl-9"
            />
          </div>
        ) : (
          <div className="flex-1 text-sm text-muted-foreground">{t('timeline.description')}</div>
        )}

        {activeView === 'chunks' && versions?.items?.length ? (
          <Select value={viewPipelineHash} onValueChange={onViewPipelineHashChange}>
            <SelectTrigger className="hidden h-10 w-[220px] sm:flex">
              <SelectValue placeholder={t('versions.selectPlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ACTIVE_PIPELINE_VALUE}>{t('versions.active')}</SelectItem>
              {versions.items.map((version) => (
                <SelectItem key={version.pipeline_hash} value={version.pipeline_hash}>
                  {version.active ? t('versions.activeTag') : t('versions.historyTag')} {version.pipeline_hash.slice(0, 10)}… ·{' '}
                  {t('versions.chunkCount', { count: version.chunk_count })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}

        <span className="hidden sm:inline-flex rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
          {activeView === 'chunks' ? `${chunks.length}/${chunksTotal}` : `${timelineItems.length}/${timelineTotal}`}
        </span>

        {activeView === 'chunks' ? (
          chunkQuery ? (
            <IconButton
              label={t('search.clear')}
              variant="ghost"
              className="h-10 w-10 text-muted-foreground hover:text-foreground"
              onClick={() => onChunkQueryChange('')}
            >
              <X className="h-4 w-4" />
            </IconButton>
          ) : null
        ) : (
          <IconButton
            label={t('timeline.refresh')}
            variant="ghost"
            className="h-10 w-10 text-muted-foreground hover:text-foreground"
            onClick={onLoadTimeline}
            disabled={isLoadingTimeline}
          >
            {isLoadingTimeline ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </IconButton>
        )}
      </div>

      <div
        ref={scrollParentRef}
        id={activeView === 'chunks' ? chunksPanelId : timelinePanelId}
        role="tabpanel"
        aria-labelledby={activeView === 'chunks' ? chunksTabId : timelineTabId}
        className="h-full overflow-y-auto overscroll-contain no-scrollbar p-4"
      >
        {activeView === 'chunks' ? renderChunksContent() : renderTimelineContent()}
      </div>
    </Panel>
  )
}
