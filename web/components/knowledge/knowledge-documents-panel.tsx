'use client'

import type { Document } from '@/types'

import { Eye, Filter, Loader2, Trash2, Upload } from 'lucide-react'

import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SearchInput } from '@/components/ui/search-input'
import { Panel } from '@/components/ui/panel'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { DocumentTags } from '@/components/documents/document-tags'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { getUserTagsFromDocument } from '@/lib/document-user-tags'
import { getFileTypeMeta } from '@/components/knowledge/file-type'

type ViewMode = 'grid' | 'list'
type DocSortKey = 'created_at' | 'filename' | 'file_size'
type DocSortDir = 'asc' | 'desc'

type KnowledgeDocumentsPanelProps = {
  isLoading: boolean
  documents: Document[]
  filteredDocuments: Document[]

  docFilter: string
  setDocFilter: (value: string) => void
  onClearFilters: () => void

  sortKey: DocSortKey
  sortDir: DocSortDir
  setSortKey: (value: DocSortKey) => void
  setSortDir: (value: DocSortDir) => void

  viewMode: ViewMode
  docGridColumns: number
  docGridRowCount: number
  docsGridVirtualizer: any
  docsTableVirtualizer: any

  selectedDocIds: string[]
  setSelectedDocIds: (value: string[]) => void
  selectedSet: Set<string>
  allVisibleSelected: boolean
  toggleSelectAllVisible: () => void
  toggleDocSelection: (docId: string) => void

  batchDeleteOpen: boolean
  setBatchDeleteOpen: (open: boolean) => void
  batchDeleting: boolean
  confirmBatchDelete: () => void | Promise<void>

  batchLifecycleWorking: boolean
  batchReingestWorking: boolean
  runBatchReingest: () => void | Promise<void>
  runBatchLifecycle: (action: 'disable' | 'enable' | 'archive' | 'unarchive') => void | Promise<void>

  anySelectedDisabled: boolean
  anySelectedEnabled: boolean
  anySelectedArchived: boolean
  anySelectedNotArchived: boolean

  deleteDocument: (id: string) => void | Promise<void>
  handleFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void
}

function getStatusBadge(status: string): { status: StatusBadgeStatus; label: string } {
  switch (status) {
    case 'completed':
      return { status: 'completed', label: '已就绪' }
    case 'failed':
      return { status: 'failed', label: '失败' }
    case 'quarantined':
      return { status: 'quarantined', label: '已隔离' }
    case 'processing':
      return { status: 'processing', label: '处理中' }
    case 'pending':
      return { status: 'pending', label: '等待' }
    default:
      return { status: 'pending', label: '等待' }
  }
}

function statusBarClassName(status: StatusBadgeStatus) {
  if (status === 'completed') return 'bg-success'
  if (status === 'failed') return 'bg-destructive'
  if (status === 'quarantined') return 'bg-warning'
  if (status === 'processing') return 'bg-info'
  if (status === 'pending') return 'bg-muted-foreground/40'
  return 'bg-muted-foreground/40'
}

export function KnowledgeDocumentsPanel({
  isLoading,
  documents,
  filteredDocuments,
  docFilter,
  setDocFilter,
  onClearFilters,
  sortKey,
  sortDir,
  setSortKey,
  setSortDir,
  viewMode,
  docGridColumns,
  docGridRowCount,
  docsGridVirtualizer,
  docsTableVirtualizer,
  selectedDocIds,
  setSelectedDocIds,
  selectedSet,
  allVisibleSelected,
  toggleSelectAllVisible,
  toggleDocSelection,
  batchDeleteOpen,
  setBatchDeleteOpen,
  batchDeleting,
  confirmBatchDelete,
  batchLifecycleWorking,
  batchReingestWorking,
  runBatchReingest,
  runBatchLifecycle,
  anySelectedDisabled,
  anySelectedEnabled,
  anySelectedArchived,
  anySelectedNotArchived,
  deleteDocument,
  handleFileUpload,
}: KnowledgeDocumentsPanelProps) {
  const docsGridVirtualRows = docsGridVirtualizer.getVirtualItems()
  const docsTableVirtualRows = docsTableVirtualizer.getVirtualItems()
  const docsTablePaddingTop = docsTableVirtualRows.length ? docsTableVirtualRows[0].start : 0
  const docsTablePaddingBottom = docsTableVirtualRows.length
    ? docsTableVirtualizer.getTotalSize() - docsTableVirtualRows[docsTableVirtualRows.length - 1].end
    : 0

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-300 motion-reduce:animate-none motion-reduce:transition-none">
      {isLoading && documents.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
          <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none mb-3" />
          <p className="text-sm">正在加载文档库...</p>
        </div>
      ) : documents.length === 0 ? (
        <div className="py-10">
          <EmptyState
            icon={Upload}
            title="知识库空空如也"
            description={
              <span className="text-muted-foreground">
                上传您的第一份文档，MimirQ 将自动解析并构建专属知识索引。
                <br />
                支持 PDF, TXT, Markdown, Excel, Word 等常见格式。
              </span>
            }
            className="bg-transparent shadow-none"
          >
            <label>
              <Button size="lg" className="gap-2 rounded-xl shadow-sm" asChild>
                <span>
                  <Upload className="w-5 h-5" />
                  立即上传文档
                </span>
              </Button>
              <input type="file" multiple accept={UPLOAD_ACCEPT} className="hidden" onChange={handleFileUpload} />
            </label>
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="mb-5 flex flex-col lg:flex-row lg:items-center gap-3">
            <div className="flex w-full lg:max-w-2xl flex-col sm:flex-row gap-3">
              <SearchInput
                value={docFilter}
                onValueChange={setDocFilter}
                placeholder="搜索文档名称…"
                containerClassName="w-full"
                inputClassName="h-10 rounded-xl border-border/60 bg-background/60 backdrop-blur-sm placeholder:text-muted-foreground/60 focus:bg-background focus:border-primary/40"
              />

              <Select
                value={`${sortKey}:${sortDir}`}
                onValueChange={(value) => {
                  const [k, d] = String(value || '').split(':')
                  if (k === 'created_at' || k === 'filename' || k === 'file_size') setSortKey(k)
                  if (d === 'asc' || d === 'desc') setSortDir(d)
                }}
              >
                <SelectTrigger
                  className="h-10 w-full sm:w-[200px] rounded-xl border-border/60 bg-background/60 backdrop-blur-sm"
                  aria-label="排序"
                >
                  <SelectValue placeholder="排序" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="created_at:desc">最新上传</SelectItem>
                  <SelectItem value="created_at:asc">最早上传</SelectItem>
                  <SelectItem value="filename:asc">文件名 A-Z</SelectItem>
                  <SelectItem value="filename:desc">文件名 Z-A</SelectItem>
                  <SelectItem value="file_size:desc">大小 从大到小</SelectItem>
                  <SelectItem value="file_size:asc">大小 从小到大</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {selectedDocIds.length > 0 ? (
            <div className="mb-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 rounded-xl border border-border/60 bg-background/60 backdrop-blur-sm px-4 py-3">
              <div className="text-sm text-foreground">
                已选 <span className="font-mono tabular-nums">{selectedDocIds.length}</span> 项
              </div>
              <div className="flex flex-wrap items-center gap-2 justify-end">
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={toggleSelectAllVisible}>
                  {allVisibleSelected ? '取消全选' : '全选当前列表'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => setSelectedDocIds([])}
                >
                  清除选择
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => void runBatchReingest()}
                  disabled={batchDeleting || batchLifecycleWorking || batchReingestWorking}
                >
                  {batchReingestWorking ? '重新入库中…' : '重新入库'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => void runBatchLifecycle('disable')}
                  disabled={batchDeleting || batchLifecycleWorking || !anySelectedEnabled}
                >
                  禁用
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => void runBatchLifecycle('enable')}
                  disabled={batchDeleting || batchLifecycleWorking || !anySelectedDisabled}
                >
                  启用
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => void runBatchLifecycle('archive')}
                  disabled={batchDeleting || batchLifecycleWorking || !anySelectedNotArchived}
                >
                  归档
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => void runBatchLifecycle('unarchive')}
                  disabled={batchDeleting || batchLifecycleWorking || !anySelectedArchived}
                >
                  取消归档
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => setBatchDeleteOpen(true)}
                  disabled={batchDeleting || batchLifecycleWorking}
                >
                  批量删除
                </Button>
              </div>
            </div>
          ) : null}

          <Dialog open={batchDeleteOpen} onOpenChange={setBatchDeleteOpen}>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>确认删除</DialogTitle>
                <DialogDescription>
                  将删除已选中的 <span className="font-mono tabular-nums">{selectedDocIds.length}</span> 份文档，此操作不可撤销。
                </DialogDescription>
              </DialogHeader>
              <div className="flex items-center justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setBatchDeleteOpen(false)} disabled={batchDeleting}>
                  取消
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => void confirmBatchDelete()}
                  disabled={batchDeleting || selectedDocIds.length === 0}
                >
                  {batchDeleting ? '删除中…' : '确认删除'}
                </Button>
              </div>
            </DialogContent>
          </Dialog>

          {filteredDocuments.length === 0 ? (
            <div className="py-10">
              <EmptyState
                icon={Filter}
                title="未找到匹配的文档"
                description={<span className="text-muted-foreground">尝试调整筛选条件，或清空筛选后重新查看全部文档。</span>}
                className="bg-transparent shadow-none"
              >
                <Button type="button" variant="outline" className="rounded-xl" onClick={onClearFilters}>
                  清空筛选
                </Button>
              </EmptyState>
            </div>
          ) : viewMode === 'grid' ? (
            <div
              role="list"
              aria-label="文档列表"
              style={{
                height: `${docsGridVirtualizer.getTotalSize()}px`,
                width: '100%',
                position: 'relative',
              }}
            >
              {docsGridVirtualRows.map((virtualRow: any) => {
                const cols = Math.max(1, docGridColumns)
                const startIndex = virtualRow.index * cols
                const rowDocs = filteredDocuments.slice(startIndex, startIndex + cols)
                const isLastRow = virtualRow.index === docGridRowCount - 1

                return (
                  <div
                    key={virtualRow.key}
                    data-index={virtualRow.index}
                    ref={docsGridVirtualizer.measureElement}
                    role="presentation"
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                    className={isLastRow ? undefined : 'pb-5'}
                  >
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-5">
                      {rowDocs.map((doc) => {
                        const badge = getStatusBadge(doc.status)
                        return (
                          <div key={doc.id} role="listitem">
                            <DocumentCard
                              doc={doc}
                              statusBadge={badge}
                              statusBarClassName={statusBarClassName(badge.status)}
                              onDelete={deleteDocument}
                              selected={selectedSet.has(doc.id)}
                              onToggleSelect={() => toggleDocSelection(doc.id)}
                            />
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <Panel padding="none" className="rounded-xl overflow-hidden">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-muted-foreground uppercase bg-muted/30 border-b border-border/60">
                  <tr>
                    <th className="px-4 py-4 font-medium w-10">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-border/60 text-primary focus-ring"
                        checked={allVisibleSelected}
                        onChange={toggleSelectAllVisible}
                        aria-label="全选当前列表"
                      />
                    </th>
                    <th className="px-6 py-4 font-medium">文档名称</th>
                    <th className="px-6 py-4 font-medium">标签</th>
                    <th className="px-6 py-4 font-medium">状态</th>
                    <th className="px-6 py-4 font-medium">分块</th>
                    <th className="px-6 py-4 font-medium">大小</th>
                    <th className="px-6 py-4 font-medium">上传时间</th>
                    <th className="px-6 py-4 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {docsTablePaddingTop > 0 ? (
                    <tr aria-hidden="true">
                      <td colSpan={8} className="p-0" style={{ height: `${docsTablePaddingTop}px` }} />
                    </tr>
                  ) : null}

                  {docsTableVirtualRows.map((virtualRow: any) => {
                    const doc = filteredDocuments[virtualRow.index]
                    if (!doc) return null
                    const badge = getStatusBadge(doc.status)
                    const fileType = getFileTypeMeta(doc)
                    const TypeIcon = fileType.icon
                    const userTags = getUserTagsFromDocument(doc)
                    return (
                      <tr
                        key={virtualRow.key}
                        data-index={virtualRow.index}
                        ref={docsTableVirtualizer.measureElement}
                        className="hover:bg-muted/20 transition-colors group"
                      >
                        <td className="px-4 py-4 align-top">
                          <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-border/60 text-primary focus-ring"
                            checked={selectedSet.has(doc.id)}
                            onChange={() => toggleDocSelection(doc.id)}
                            aria-label={`选择文档 ${doc.filename}`}
                          />
                        </td>
                        <td className="px-6 py-4 font-medium text-foreground flex items-center gap-3">
                          <div className={cn('p-2 rounded-lg border', fileType.bg, fileType.border, fileType.color)}>
                            <TypeIcon className="w-4 h-4" />
                          </div>
                          <div className="min-w-0 flex items-center gap-2">
                            <span className="truncate max-w-[200px]" title={doc.filename}>
                              {doc.filename}
                            </span>
                            <span
                              className={cn(
                                'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ',
                                fileType.bg,
                                fileType.border,
                                fileType.color
                              )}
                              title={fileType.label}
                            >
                              {fileType.label}
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-4 align-top">
                          {userTags.length ? (
                            <DocumentTags tags={userTags} max={3} dense />
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={badge.status} label={badge.label} />
                        </td>
                        <td className="px-6 py-4 text-muted-foreground">{doc.chunk_count || '-'}</td>
                        <td className="px-6 py-4 text-muted-foreground font-mono text-xs">{formatFileSize(doc.file_size)}</td>
                        <td className="px-6 py-4 text-muted-foreground">{formatDate(doc.created_at)}</td>
                        <td className="px-6 py-4 text-right flex items-center justify-end gap-2">
                          <DocumentDetailDialog
                            document={doc}
                            trigger={
                              <IconButton
                                label="预览内容"
                                variant="ghost"
                                className="h-9 w-9 text-muted-foreground hover:text-primary hover:bg-muted opacity-0 group-hover:opacity-100"
                              >
                                <Eye className="w-4 h-4" />
                              </IconButton>
                            }
                          />
                          <IconButton
                            label="删除文档"
                            variant="ghost"
                            className="h-9 w-9 text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100"
                            onClick={() => void deleteDocument(doc.id)}
                          >
                            <Trash2 className="w-4 h-4" />
                          </IconButton>
                        </td>
                      </tr>
                    )
                  })}

                  {docsTablePaddingBottom > 0 ? (
                    <tr aria-hidden="true">
                      <td colSpan={8} className="p-0" style={{ height: `${docsTablePaddingBottom}px` }} />
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}

function DocumentCard({
  doc,
  statusBadge,
  statusBarClassName,
  onDelete,
  selected,
  onToggleSelect,
}: {
  doc: Document
  statusBadge: { status: StatusBadgeStatus; label: string }
  statusBarClassName: string
  onDelete: (id: string) => void | Promise<void>
  selected: boolean
  onToggleSelect: () => void
}) {
  const parserLabel = doc.metadata?.parser_backend ? getParserLabel(doc.metadata.parser_backend as string) : null
  const userTags = getUserTagsFromDocument(doc)
  const fileType = getFileTypeMeta(doc)
  const TypeIcon = fileType.icon

  return (
    <Panel
      padding="none"
      className="group relative rounded-2xl overflow-hidden hover:shadow-strong/20 hover:border-primary/30 transition-colors transition-shadow duration-200 motion-reduce:transition-none"
    >
      <div className={cn('h-1.5 w-full', statusBarClassName)} />

      <div
        className={cn(
          'absolute top-3 left-3 z-10 rounded-lg border border-border/60 bg-background/70 backdrop-blur-sm p-1 transition-opacity',
          selected ? 'opacity-100' : 'opacity-100 lg:opacity-0 lg:group-hover:opacity-100'
        )}
      >
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-border/60 text-primary focus-ring"
          checked={selected}
          onChange={onToggleSelect}
          aria-label={`选择文档 ${doc.filename}`}
        />
      </div>

      <div className="p-5 flex-1 flex flex-col">
        <div className="flex items-start justify-between mb-4">
          <div className={cn('w-12 h-12 rounded-xl flex items-center justify-center border', fileType.bg, fileType.border, fileType.color)}>
            <TypeIcon className="w-6 h-6" />
          </div>
          <div className="flex items-center gap-2">
            <div className={cn('px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border', fileType.bg, fileType.color, fileType.border)}>
              {fileType.label}
            </div>
            {doc.disabled_at ? (
              <div className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border border-border/60 bg-muted/60 text-muted-foreground">
                Disabled
              </div>
            ) : null}
            {!doc.disabled_at && doc.archived_at ? (
              <div className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border border-border/60 bg-muted/60 text-muted-foreground">
                Archived
              </div>
            ) : null}
            <StatusBadge status={statusBadge.status} label={statusBadge.label} dense />
          </div>
        </div>

        <h3 className="font-semibold text-foreground line-clamp-2 mb-2 min-h-[2.5rem]" title={doc.filename}>
          {doc.filename}
        </h3>

        {userTags.length ? <DocumentTags tags={userTags} max={3} dense className="mb-3" /> : null}

        <div className="space-y-2 mt-auto">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>大小</span>
            <span className="font-mono">{formatFileSize(doc.file_size)}</span>
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>分块</span>
            <span className="font-mono">{doc.chunk_count || '-'}</span>
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>时间</span>
            <span>{formatDate(doc.created_at)}</span>
          </div>
        </div>
      </div>

      <div className="px-5 py-3 border-t border-border/60 bg-muted/20 flex items-center justify-between opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity">
        <span className="text-[10px] text-muted-foreground font-medium truncate max-w-[80px]">{parserLabel || 'Auto'}</span>
        <div className="flex items-center gap-1">
          <DocumentDetailDialog
            document={doc}
            trigger={
              <IconButton
                label="预览内容"
                variant="ghost"
                className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted"
                onClick={(e) => e.stopPropagation()}
              >
                <Eye className="w-4 h-4" />
              </IconButton>
            }
          />
          <IconButton
            label="删除文档"
            variant="ghost"
            className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
            onClick={(e) => {
              e.stopPropagation()
              void onDelete(doc.id)
            }}
          >
            <Trash2 className="w-4 h-4" />
          </IconButton>
        </div>
      </div>

      {statusBadge.status === 'processing' ? (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-muted">
          <div
            className="h-full bg-primary/70 animate-pulse motion-reduce:animate-none"
            style={{ width: `${doc.processing_progress || 60}%` }}
          />
        </div>
      ) : null}
    </Panel>
  )
}

