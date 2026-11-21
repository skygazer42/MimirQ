'use client'

import { workspaceStyles as ws } from '@/components/ui/operational-workspace'
import type { ReactNode, RefObject } from 'react'
import { FileUp, Search } from '@/components/icons'

import { formatEvidenceScore, type EvidenceCitation } from '@/lib/evidence-citations'
import type { RankedEvidenceCitation } from '@/lib/evidence-suggestions'
import { coerceOneOf } from '@/lib/one-of'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { Skeleton } from '@/components/ui/skeleton'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

import { RETRIEVAL_PROFILE_VALUES, type RetrievalProfile } from './evidence-suite-workbench-utils'

const CREATE_ITEM_TAB_VALUES = ['retrieve', 'import'] as const
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
  importingPack: boolean
  importPackVersionLabel: string
  importCitations: readonly EvidenceCitation[]
  importError: string | null
  importSelectedChunkIds: string[]
  creatingItem: boolean
  createItemError: string | null
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

function CitationOption({
  citation,
  selectedChunkIds,
  onToggleChunk,
  disabled,
  hits = [],
}: {
  citation: EvidenceCitation
  selectedChunkIds: readonly string[]
  onToggleChunk: (chunkId: string) => void
  disabled: boolean
  hits?: readonly string[]
}) {
  const chunkId = citation.chunk_id
  const selectable =
    typeof chunkId === 'string' &&
    chunkId.length > 0 &&
    typeof citation.document_id === 'string' &&
    citation.document_id.length > 0
  return (
    <div className="rounded-lg border border-border/60 p-2">
      <div className="flex items-start gap-2">
        <Checkbox
          checked={selectable && selectedChunkIds.includes(chunkId)}
          onCheckedChange={() => {
            if (selectable) onToggleChunk(chunkId)
          }}
          aria-label="选择该引用"
          disabled={disabled || !selectable}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-xs font-mono text-foreground">
                {citation.document_name ?? citation.document_id?.slice(0, 8) ?? '未提供文档名称'}
              </div>
              <div className="mt-1 text-xs text-muted-foreground font-mono tabular-nums">
                score {formatEvidenceScore(citation)}
                {citation.page_number == null ? null : ` · P.${citation.page_number}`}
                {citation.chunk_index == null ? null : ` · #${citation.chunk_index}`}
              </div>
            </div>
            <Badge variant={selectable ? 'outline' : 'destructive'} className="font-mono text-[11px]">
              {selectable ? chunkId.slice(0, 8) : '缺少文档或切片标识'}
            </Badge>
          </div>
          <div className="mt-2 line-clamp-3 text-xs text-muted-foreground text-pretty">{citation.chunk_content}</div>
          {hits.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {hits.slice(0, 4).map((hit) => (
                <Badge key={hit} variant="outline" className="text-[11px] font-mono">
                  {hit}
                </Badge>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
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
  importingPack,
  importPackVersionLabel,
  importCitations,
  importError,
  importSelectedChunkIds,
  creatingItem,
  createItemError,
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
  let retrieveListContent: ReactNode
  if (retrieving && !hasRetrieveResult) {
    retrieveListContent = <Skeleton className="h-24 w-full" aria-label="正在读取引用" />
  } else if (!hasRetrieveResult) {
    retrieveListContent = <p className="text-sm text-muted-foreground">运行检索后勾选引用。</p>
  } else if (retrieveRanked.length === 0) {
    retrieveListContent = <p className="text-sm text-muted-foreground">本次检索没有引用。</p>
  } else {
    retrieveListContent = retrieveRanked.map((ranked) => (
      <CitationOption
        key={ranked.sourceIndex}
        citation={ranked.citation}
        selectedChunkIds={selectedChunkIds}
        onToggleChunk={onToggleRetrieveChunk}
        disabled={creatingItem || retrieving}
        hits={ranked.hits}
      />
    ))
  }

  const importPackSummary = hasImportPack ? (
    <div className="truncate text-xs text-muted-foreground font-mono">
      pack version {importPackVersionLabel} · citations {importCitations.length}
    </div>
  ) : (
    <div className="text-xs text-muted-foreground text-pretty">上传 Evidence Pack（来自检索预览导出）。</div>
  )

  let importListContent: ReactNode
  if (!hasImportPack) {
    importListContent = <p className="text-sm text-muted-foreground">导入后勾选引用。</p>
  } else if (importCitations.length === 0) {
    importListContent = <p className="text-sm text-muted-foreground">证据包中没有引用。</p>
  } else {
    importListContent = importCitations.map((citation, index) => (
      <CitationOption
        key={index}
        citation={citation}
        selectedChunkIds={importSelectedChunkIds}
        onToggleChunk={onToggleImportChunk}
        disabled={creatingItem}
      />
    ))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={ws.dialog}>
        <DialogHeader className={ws.dialogHeader}>
          <DialogTitle>新建 Evidence Item</DialogTitle>
          <DialogDescription className="text-pretty">
            先用检索找到证据切片，再将选中的引用保存为 <span className="font-mono">reference_sources</span>。
          </DialogDescription>
        </DialogHeader>
        <div className={ws.dialogBody}>
          <div className="space-y-4">
            <fieldset disabled={creatingItem || importingPack} className="space-y-4">
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
                      <Select
                        value={profile}
                        onValueChange={(value) =>
                          onProfileChange(coerceOneOf(RETRIEVAL_PROFILE_VALUES, value, 'recall50'))
                        }
                      >
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

                    <LoadingButton
                      loading={retrieving}
                      className="gap-2"
                      onClick={onRunRetrieve}
                      disabled={retrieving || !newQuery.trim() || !datasetId}
                    >
                      <Search className="size-4" aria-hidden="true" />
                      运行检索
                    </LoadingButton>

                    <Button
                      variant="outline"
                      className="gap-2"
                      onClick={onApplyRetrieveSuggestions}
                      disabled={retrieving || !hasRetrieveResult || suggestedRetrieveChunkIds.length === 0}
                    >
                      Suggest ({suggestedRetrieveChunkIds.length})
                    </Button>

                    <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">
                      已选 {selectedChunkIds.length}
                    </div>
                  </div>

                  {retrieveError !== null ? (
                    <p role="alert" className="text-sm text-destructive break-words">
                      {retrieveError}
                    </p>
                  ) : null}

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
                      <div className="space-y-2">{retrieveListContent}</div>
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
                        if (file !== undefined) onPickPackFile(file)
                        event.target.value = ''
                      }}
                    />
                    <LoadingButton
                      loading={importingPack}
                      variant="outline"
                      className="gap-2"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <FileUp className="size-4" aria-hidden="true" />
                      选择 JSON
                    </LoadingButton>
                    {importPackSummary}

                    <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">
                      已选 {importSelectedChunkIds.length}
                    </div>
                  </div>

                  {importError !== null ? (
                    <p role="alert" className="text-sm text-destructive break-words">
                      {importError}
                    </p>
                  ) : null}

                  <Panel className="p-3">
                    <ScrollArea className="h-[320px] pr-2">
                      <div className="space-y-2">{importListContent}</div>
                    </ScrollArea>
                  </Panel>
                </TabsContent>
              </Tabs>
            </fieldset>
          </div>
        </div>
        <DialogFooter className={`${ws.dialogFooter} flex-wrap`}>
          {createItemError !== null ? (
            <p role="alert" className="w-full min-w-0 break-words text-sm text-destructive">
              {createItemError}
            </p>
          ) : null}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <LoadingButton
            loading={creatingItem}
            onClick={onCreateItem}
            disabled={
              retrieving ||
              importingPack ||
              !selectedSuiteId ||
              !newQuery.trim() ||
              (createItemTab === 'retrieve' ? selectedChunkIds.length === 0 : importSelectedChunkIds.length === 0)
            }
          >
            创建 Item（draft）
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
