'use client'

import type { RefObject } from 'react'
import { FileUp, Loader2, Search } from 'lucide-react'

import type { Citation } from '@/types'
import type { RankedEvidenceCitation } from '@/lib/evidence-suggestions'
import { coerceOneOf } from '@/lib/one-of'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

const RETRIEVAL_PROFILE_VALUES = ['recall50', 'coverage80', 'recall20'] as const
const CREATE_ITEM_TAB_VALUES = ['retrieve', 'import'] as const

type RetrievalProfile = (typeof RETRIEVAL_PROFILE_VALUES)[number]
type CreateItemTab = (typeof CREATE_ITEM_TAB_VALUES)[number]

type CreateItemDialogProps = {
  open: boolean
  newQuery: string
  newExpected: string
  newNotes: string
  createItemTab: CreateItemTab
  profile: RetrievalProfile
  retrieving: boolean
  datasetId: string | null
  suggestedRetrieveChunkIds: string[]
  selectedChunkIds: string[]
  retrieveError: string | null
  expectedNeedles: string[]
  hasRetrieveResult: boolean
  retrieveRanked: RankedEvidenceCitation[]
  fileInputRef: RefObject<HTMLInputElement | null>
  hasImportPack: boolean
  importPackVersionLabel: string
  importCitations: Citation[]
  importError: string | null
  importSelectedChunkIds: string[]
  creatingItem: boolean
  selectedSuiteId: string
  onOpenChange: (open: boolean) => void
  onNewQueryChange: (value: string) => void
  onNewExpectedChange: (value: string) => void
  onNewNotesChange: (value: string) => void
  onCreateItemTabChange: (value: CreateItemTab) => void
  onProfileChange: (value: RetrievalProfile) => void
  onRunRetrieve: () => void
  onApplyRetrieveSuggestions: () => void
  onToggleRetrieveChunk: (chunkId: string) => void
  onPickPackFile: (file: File) => void
  onToggleImportChunk: (chunkId: string) => void
  onCreateItem: () => void
}

function citationScoreLabel(citation: Citation): string {
  const raw =
    citation.retrieval_score ?? citation.rerank_score ?? citation.relevance_score ?? citation.vector_score ?? citation.bm25_score ?? 0
  const value = Number(raw)
  if (Number.isFinite(value)) return value.toFixed(4)
  return '0.0000'
}

export function CreateItemDialog({
  open,
  newQuery,
  newExpected,
  newNotes,
  createItemTab,
  profile,
  retrieving,
  datasetId,
  suggestedRetrieveChunkIds,
  selectedChunkIds,
  retrieveError,
  expectedNeedles,
  hasRetrieveResult,
  retrieveRanked,
  fileInputRef,
  hasImportPack,
  importPackVersionLabel,
  importCitations,
  importError,
  importSelectedChunkIds,
  creatingItem,
  selectedSuiteId,
  onOpenChange,
  onNewQueryChange,
  onNewExpectedChange,
  onNewNotesChange,
  onCreateItemTabChange,
  onProfileChange,
  onRunRetrieve,
  onApplyRetrieveSuggestions,
  onToggleRetrieveChunk,
  onPickPackFile,
  onToggleImportChunk,
  onCreateItem,
}: Readonly<CreateItemDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>新建 Evidence Item</DialogTitle>
          <DialogDescription className="text-pretty">
            先用检索找到证据切片，再将选中的引用保存为 <span className="font-mono">reference_sources</span>。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="item-query">Query</Label>
              <Input
                id="item-query"
                value={newQuery}
                onChange={(event) => onNewQueryChange(event.target.value)}
                placeholder="输入要标注/回归的查询…"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="item-expected">Expected Answer（可选）</Label>
              <Input
                id="item-expected"
                value={newExpected}
                onChange={(event) => onNewExpectedChange(event.target.value)}
                placeholder="用于人工对照（可留空）"
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="item-notes">Notes（可选）</Label>
            <Textarea
              id="item-notes"
              value={newNotes}
              onChange={(event) => onNewNotesChange(event.target.value)}
              placeholder="记录为什么这些引用是 Ground Truth / 边界条件 / 预期召回方式…"
              rows={2}
            />
          </div>

          <Tabs
            value={createItemTab}
            onValueChange={(value) => onCreateItemTabChange(coerceOneOf(CREATE_ITEM_TAB_VALUES, value, 'retrieve'))}
          >
            <TabsList>
              <TabsTrigger value="retrieve">检索选择</TabsTrigger>
              <TabsTrigger value="import">导入 Evidence Pack</TabsTrigger>
            </TabsList>

            <TabsContent value="retrieve" className="mt-3 space-y-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-end">
                <div className="w-full md:w-[220px]">
                  <div className="mb-1 text-xs text-muted-foreground">Retrieval Profile</div>
                  <Select value={profile} onValueChange={(value) => onProfileChange(coerceOneOf(RETRIEVAL_PROFILE_VALUES, value, 'recall50'))}>
                    <SelectTrigger className="h-9">
                      <SelectValue placeholder="选择 profile" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="recall50">recall50 (默认)</SelectItem>
                      <SelectItem value="coverage80">coverage80</SelectItem>
                      <SelectItem value="recall20">recall20</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Button className="gap-2" onClick={onRunRetrieve} disabled={retrieving || !newQuery.trim() || !datasetId}>
                  {retrieving ? (
                    <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  ) : (
                    <Search className="size-4" aria-hidden="true" />
                  )}
                  运行检索
                </Button>

                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={onApplyRetrieveSuggestions}
                  disabled={retrieving || !hasRetrieveResult || suggestedRetrieveChunkIds.length === 0}
                >
                  Suggest ({suggestedRetrieveChunkIds.length})
                </Button>

                <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">已选 {selectedChunkIds.length}</div>
              </div>

              {retrieveError ? <div className="text-xs text-destructive text-pretty">{retrieveError}</div> : null}

              {expectedNeedles.length ? (
                <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                  <span className="font-mono">needles:</span>
                  {expectedNeedles.slice(0, 10).map((needle) => (
                    <Badge key={`needle:${needle}`} variant="secondary" className="text-[11px] font-mono">
                      {needle}
                    </Badge>
                  ))}
                </div>
              ) : null}

              <Panel className="p-3">
                <ScrollArea className="h-[320px] pr-2">
                  <div className="space-y-2">
                    {hasRetrieveResult ? (
                      retrieveRanked.length === 0 ? (
                        <div className="text-sm text-muted-foreground text-pretty">无 citations。</div>
                      ) : (
                      retrieveRanked.map((ranked) => {
                        const citation = ranked.citation
                        const assistScore = ranked.score
                        const hits = ranked.hits || []
                        const chunkId = String(citation.chunk_id || '')
                        const checked = !!chunkId && selectedChunkIds.includes(chunkId)
                        return (
                          <div key={chunkId || `${citation.document_id}:${citation.chunk_index}`} className="rounded-lg border border-border/60 p-2">
                            <div className="flex items-start gap-2">
                              <Checkbox
                                checked={checked}
                                onCheckedChange={() => onToggleRetrieveChunk(chunkId)}
                                aria-label="选择该引用"
                                disabled={!chunkId}
                              />
                              <div className="min-w-0 flex-1">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <div className="truncate text-xs font-mono text-foreground">
                                      {citation.document_name || String(citation.document_id).slice(0, 8)}
                                    </div>
                                    <div className="mt-1 text-xs text-muted-foreground font-mono tabular-nums">
                                      score {citationScoreLabel(citation)}
                                      {typeof citation.page_number === 'number' ? ` · P.${citation.page_number}` : null}
                                      {typeof citation.chunk_index === 'number' ? ` · #${citation.chunk_index}` : null}
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {assistScore > 0 ? (
                                      <Badge variant="secondary" className="font-mono text-[11px] tabular-nums">
                                        hit {assistScore}
                                      </Badge>
                                    ) : null}
                                    {chunkId ? (
                                      <Badge variant="outline" className="font-mono text-[11px]">
                                        {chunkId.slice(0, 8)}
                                      </Badge>
                                    ) : (
                                      <Badge variant="destructive" className="font-mono text-[11px]">
                                        missing chunk_id
                                      </Badge>
                                    )}
                                  </div>
                                </div>
                                <div className="mt-2 line-clamp-3 text-xs text-muted-foreground text-pretty">{citation.chunk_content}</div>
                                {hits.length ? (
                                  <div className="mt-2 flex flex-wrap gap-1">
                                    {hits.slice(0, 4).map((hit) => (
                                      <Badge
                                        key={`hit:${chunkId || String(citation.document_id)}:${hit}`}
                                        variant="outline"
                                        className="text-[11px] font-mono"
                                      >
                                        {hit}
                                      </Badge>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            </div>
                          </div>
                        )
                      })
                      )
                    ) : (
                      <div className="text-sm text-muted-foreground text-pretty">运行检索后在此勾选 Ground Truth 引用。</div>
                    )}
                  </div>
                </ScrollArea>
              </Panel>
            </TabsContent>

            <TabsContent value="import" className="mt-3 space-y-3">
              <div className="flex items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/json,.json"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) onPickPackFile(file)
                  }}
                />
                <Button variant="outline" className="gap-2" onClick={() => fileInputRef.current?.click()}>
                  <FileUp className="size-4" aria-hidden="true" />
                  选择 JSON
                </Button>
                {hasImportPack ? (
                  <div className="truncate text-xs text-muted-foreground font-mono">
                    pack version {importPackVersionLabel} · citations {importCitations.length}
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground text-pretty">上传 Evidence Pack（来自检索预览导出）。</div>
                )}

                <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">已选 {importSelectedChunkIds.length}</div>
              </div>

              {importError ? <div className="text-xs text-destructive text-pretty">{importError}</div> : null}

              <Panel className="p-3">
                <ScrollArea className="h-[320px] pr-2">
                  <div className="space-y-2">
                    {hasImportPack ? (
                      importCitations.length === 0 ? (
                        <div className="text-sm text-muted-foreground text-pretty">pack 中没有 citations。</div>
                      ) : (
                      importCitations.map((citation) => {
                        const chunkId = String(citation.chunk_id || '')
                        const checked = !!chunkId && importSelectedChunkIds.includes(chunkId)
                        return (
                          <div key={chunkId || `${citation.document_id}:${citation.chunk_index}`} className="rounded-lg border border-border/60 p-2">
                            <div className="flex items-start gap-2">
                              <Checkbox
                                checked={checked}
                                onCheckedChange={() => onToggleImportChunk(chunkId)}
                                aria-label="选择该引用"
                                disabled={!chunkId}
                              />
                              <div className="min-w-0 flex-1">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <div className="truncate text-xs font-mono text-foreground">
                                      {citation.document_name || String(citation.document_id).slice(0, 8)}
                                    </div>
                                    <div className="mt-1 text-xs text-muted-foreground font-mono tabular-nums">
                                      score {citationScoreLabel(citation)}
                                      {typeof citation.page_number === 'number' ? ` · P.${citation.page_number}` : null}
                                      {typeof citation.chunk_index === 'number' ? ` · #${citation.chunk_index}` : null}
                                    </div>
                                  </div>
                                  {chunkId ? (
                                    <Badge variant="outline" className="font-mono text-[11px]">
                                      {chunkId.slice(0, 8)}
                                    </Badge>
                                  ) : (
                                    <Badge variant="destructive" className="font-mono text-[11px]">
                                      missing chunk_id
                                    </Badge>
                                  )}
                                </div>
                                <div className="mt-2 line-clamp-3 text-xs text-muted-foreground text-pretty">{citation.chunk_content}</div>
                              </div>
                            </div>
                          </div>
                        )
                      })
                      )
                    ) : (
                      <div className="text-sm text-muted-foreground text-pretty">导入后在此勾选 Ground Truth 引用。</div>
                    )}
                  </div>
                </ScrollArea>
              </Panel>
            </TabsContent>
          </Tabs>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={onCreateItem} disabled={creatingItem || !selectedSuiteId || !newQuery.trim()}>
            {creatingItem ? <Loader2 className="mr-2 size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}
            创建 Item（draft）
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
