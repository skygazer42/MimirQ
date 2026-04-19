'use client'

import { ChevronDown, ChevronUp, FileText, X } from 'lucide-react'

import { cn } from '@/lib/utils'

import { getGraphLinkEndpointId, type GraphLinkLike } from '../graph-page-utils'

type GraphLinkDetailPanelProps = Readonly<{
  open: boolean
  selectedLink: GraphLinkLike | null
  graphLinks: GraphLinkLike[]
  selfLoopGroupExpanded: boolean
  onToggleSelfLoopGroup: () => void
  onClose: () => void
}>

function getEndpointLabel(endpoint: GraphLinkLike['source']): string {
  if (typeof endpoint === 'object' && endpoint) {
    return String(endpoint.label ?? endpoint.id ?? '')
  }
  return String(endpoint ?? '')
}

export function GraphLinkDetailPanel({
  open,
  selectedLink,
  graphLinks,
  selfLoopGroupExpanded,
  onToggleSelfLoopGroup,
  onClose,
}: GraphLinkDetailPanelProps) {
  return (
    <div
      className={cn(
        'absolute top-4 right-4 bottom-24 w-80 bg-card rounded-2xl shadow-strong border border-border transform transition-transform duration-200 ease-out z-20 flex flex-col overflow-hidden',
        open && selectedLink ? 'translate-x-0' : 'translate-x-[120%]'
      )}
    >
      {selectedLink ? (
        (() => {
          const srcObj = selectedLink.source
          const tgtObj = selectedLink.target
          const srcLabel = getEndpointLabel(srcObj)
          const tgtLabel = getEndpointLabel(tgtObj)
          const srcId = getGraphLinkEndpointId(srcObj)
          const tgtId = getGraphLinkEndpointId(tgtObj)
          const isSelfLoop = Boolean(srcId) && srcId === tgtId
          const kind = String(selectedLink?.meta?.kind ?? selectedLink?.kind ?? '').trim()
          const predicate = String(selectedLink?.meta?.predicate ?? selectedLink?.predicate ?? selectedLink?.label ?? '').trim()
          const confidence = selectedLink?.meta?.confidence ?? selectedLink?.confidence ?? selectedLink?.weight
          const confNum = Number(confidence)
          const confStr = Number.isFinite(confNum) ? confNum.toFixed(3) : null
          const docId = String(selectedLink?.meta?.document_id ?? '').trim()
          const chunkId = String(selectedLink?.meta?.chunk_id ?? '').trim()
          const eventId = String(selectedLink?.meta?.event_id ?? '').trim()
          const page = String(selectedLink?.meta?.page ?? selectedLink?.meta?.page_number ?? '').trim()
          const sharedEvents = String(selectedLink?.meta?.shared_events ?? '').trim()

          const selfLoopLinks = isSelfLoop
            ? graphLinks.filter((link) => {
                const sourceId = getGraphLinkEndpointId(link?.source)
                const targetId = getGraphLinkEndpointId(link?.target)
                return Boolean(sourceId) && sourceId === targetId && sourceId === srcId
              })
            : []
          const showSelfLoopGroup = isSelfLoop && selfLoopLinks.length > 1

          const kindLabel =
            kind === 'entity_relation'
              ? 'Relation (triple)'
              : kind === 'event_entity'
                ? 'Evidence (event → entity)'
                : kind === 'entity_entity'
                  ? 'Co-occurrence (entity ↔ entity)'
                  : kind || 'Link'

          return (
            <>
              <div className="p-5 border-b border-border flex items-start justify-between bg-card">
                <div className="flex-1 min-w-0">
                  <h2 className="font-bold text-sm text-foreground mb-2">Relationship</h2>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted rounded-lg p-2.5 border border-border">
                    <span className="truncate font-medium text-foreground" title={srcLabel}>
                      {srcLabel}
                    </span>
                    <span className="text-primary font-semibold flex-shrink-0">→</span>
                    <span className="truncate text-primary font-medium" title={predicate}>
                      {predicate || 'RELATED'}
                    </span>
                    <span className="text-primary font-semibold flex-shrink-0">→</span>
                    <span className="truncate font-medium text-foreground" title={tgtLabel}>
                      {tgtLabel}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="关闭边详情面板"
                  className="text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg p-1 transition-colors ml-2 flex-shrink-0"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-5 space-y-4">
                <div className="space-y-3">
                  {showSelfLoopGroup ? (
                    <div className="bg-muted rounded-xl p-3 border border-border">
                      <button
                        type="button"
                        onClick={onToggleSelfLoopGroup}
                        className="w-full flex items-center justify-between gap-2 text-left"
                        aria-expanded={selfLoopGroupExpanded}
                      >
                        <div className="min-w-0">
                          <div className="text-[11px] font-medium text-muted-foreground mb-1">Self-loop Group</div>
                          <div className="text-sm font-medium text-foreground truncate">{srcLabel || srcId}</div>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <span className="text-[11px] font-mono text-muted-foreground">{selfLoopLinks.length}</span>
                          {selfLoopGroupExpanded ? (
                            <ChevronUp className="w-4 h-4 text-muted-foreground" />
                          ) : (
                            <ChevronDown className="w-4 h-4 text-muted-foreground" />
                          )}
                        </div>
                      </button>

                      {selfLoopGroupExpanded ? (
                        <div className="mt-3 space-y-2">
                          {selfLoopLinks.slice(0, 12).map((link, idx) => {
                            const edgeId = String(link?.id ?? link?.meta?.id ?? '').trim()
                            const edgeKind = String(link?.meta?.kind ?? link?.kind ?? '').trim()
                            const edgePredicate = String(link?.meta?.predicate ?? link?.predicate ?? link?.label ?? '').trim()
                            const createdAt = String(link?.meta?.created_at ?? link?.meta?.created ?? '').trim()
                            const episodesRaw = link?.meta?.episodes ?? link?.meta?.episode_ids ?? link?.meta?.episode_count
                            const episodes = Array.isArray(episodesRaw)
                              ? String(episodesRaw.length)
                              : episodesRaw == null
                                ? ''
                                : String(episodesRaw)
                            const fact = String(link?.meta?.fact ?? link?.meta?.quote ?? link?.meta?.text ?? '').trim()
                            const secondary = [edgeKind, edgePredicate].filter(Boolean).join(' · ')

                            return (
                              <div key={edgeId || `${edgePredicate}-${idx}`} className="rounded-lg border border-border bg-background/60 px-3 py-2">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="min-w-0">
                                    <div className="text-xs font-medium text-foreground truncate">
                                      {edgePredicate || edgeKind || 'self-loop'}
                                    </div>
                                    {secondary ? (
                                      <div className="text-[11px] text-muted-foreground truncate">{secondary}</div>
                                    ) : null}
                                  </div>
                                  {edgeId ? (
                                    <div className="text-[11px] font-mono text-muted-foreground">{edgeId.slice(0, 8)}</div>
                                  ) : null}
                                </div>

                                {createdAt || episodes || fact ? (
                                  <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                                    {createdAt ? (
                                      <div className="truncate" title={createdAt}>
                                        <span className="opacity-70">Created</span>: {createdAt}
                                      </div>
                                    ) : null}
                                    {episodes ? (
                                      <div className="truncate" title={episodes}>
                                        <span className="opacity-70">Episodes</span>: {episodes}
                                      </div>
                                    ) : null}
                                    {fact ? (
                                      <div className="col-span-2 truncate" title={fact}>
                                        <span className="opacity-70">Fact</span>: {fact}
                                      </div>
                                    ) : null}
                                  </div>
                                ) : null}
                              </div>
                            )
                          })}

                          {selfLoopLinks.length > 12 ? (
                            <div className="text-[11px] text-muted-foreground">
                              仅显示前 12 条（共 {selfLoopLinks.length} 条）
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="bg-muted rounded-xl p-3 border border-border">
                    <span className="block text-[11px] font-medium text-muted-foreground mb-1">Type</span>
                    <span className="block text-sm text-foreground">{kindLabel}</span>
                  </div>

                  {predicate ? (
                    <div className="bg-muted rounded-xl p-3 border border-border">
                      <span className="block text-[11px] font-medium text-muted-foreground mb-1">Predicate</span>
                      <span className="block text-sm text-foreground">{predicate}</span>
                    </div>
                  ) : null}

                  {confStr ? (
                    <div className="bg-muted rounded-xl p-3 border border-border">
                      <span className="block text-[11px] font-medium text-muted-foreground mb-1">Confidence</span>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.round(confNum * 100)}%`,
                              backgroundColor: confNum >= 0.8 ? '#22c55e' : confNum >= 0.5 ? '#f59e0b' : '#ef4444',
                            }}
                          />
                        </div>
                        <span className="text-xs font-mono text-foreground">{confStr}</span>
                      </div>
                    </div>
                  ) : null}

                  {sharedEvents && sharedEvents !== '0' ? (
                    <div className="bg-muted rounded-xl p-3 border border-border">
                      <span className="block text-[11px] font-medium text-muted-foreground mb-1">Shared Events</span>
                      <span className="block text-sm text-foreground">{sharedEvents}</span>
                    </div>
                  ) : null}
                </div>

                {docId || chunkId || eventId || page ? (
                  <div>
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3 flex items-center gap-2">
                      <FileText className="w-3 h-3" />
                      Provenance
                    </h3>
                    <div className="space-y-3">
                      {docId ? (
                        <div className="bg-muted rounded-xl p-3 border border-border">
                          <span className="block text-[11px] font-medium text-muted-foreground mb-1">Document</span>
                          <span className="block text-xs font-mono text-foreground break-all">{docId}</span>
                        </div>
                      ) : null}
                      {eventId ? (
                        <div className="bg-muted rounded-xl p-3 border border-border">
                          <span className="block text-[11px] font-medium text-muted-foreground mb-1">Event</span>
                          <span className="block text-xs font-mono text-foreground break-all">{eventId}</span>
                        </div>
                      ) : null}
                      {chunkId ? (
                        <div className="bg-muted rounded-xl p-3 border border-border">
                          <span className="block text-[11px] font-medium text-muted-foreground mb-1">Chunk</span>
                          <span className="block text-xs font-mono text-foreground break-all">{chunkId}</span>
                        </div>
                      ) : null}
                      {page ? (
                        <div className="bg-muted rounded-xl p-3 border border-border">
                          <span className="block text-[11px] font-medium text-muted-foreground mb-1">Page</span>
                          <span className="block text-sm text-foreground">{page}</span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          )
        })()
      ) : null}
    </div>
  )
}
