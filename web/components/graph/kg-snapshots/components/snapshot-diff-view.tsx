'use client'

import { Copy, Download, ChevronLeft, ChevronRight, Loader2, SlidersHorizontal } from '@/components/icons'
import { useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { WorkspaceTableScroll, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { recordSchema } from '@/lib/response-schema'
import { cn } from '@/lib/utils'
import { buildSideBySideDiffRows } from '../json-diff'
import type { SnapshotDiffPayload } from '../types'
import { exactDiffSample, exactDiffTotal, firstDisplayString } from '../utils'
import { JsonDiffCell } from './json-code-pane'

const CHANGE_PAGE_SIZE = 20
const groups = [
  { key: 'nodes_added', kind: '节点', change: '新增', tone: 'text-success' },
  { key: 'nodes_removed', kind: '节点', change: '移除', tone: 'text-destructive' },
  { key: 'nodes_changed', kind: '节点', change: '更新', tone: 'text-warning' },
  { key: 'edges_added', kind: '关系', change: '新增', tone: 'text-success' },
  { key: 'edges_removed', kind: '关系', change: '移除', tone: 'text-destructive' },
  { key: 'edges_changed', kind: '关系', change: '更新', tone: 'text-warning' },
] as const
type ChangeRow = {
  key: string
  id: string
  kind: string
  change: string
  tone: string
  name: string
  item: Record<string, unknown>
}

function changeName(item: Record<string, unknown>): string {
  const before = recordSchema.safeParse(item.before).data
  const after = recordSchema.safeParse(item.after).data
  return firstDisplayString(item.name, item.label, after?.name, after?.label, before?.name, before?.label, item.id)
}

function propertyText(value: unknown) {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export function SnapshotDiffView({
  titleA,
  titleB,
  subtitleA,
  subtitleB,
  leftCode,
  rightCode,
  diff,
  isEmpty,
  emptyState,
  onCopy,
  onDownload,
  onLoadDetails,
  pending = false,
  latencyMs,
}: Readonly<{
  titleA: string
  titleB: string
  subtitleA?: string
  subtitleB?: string
  leftCode: string
  rightCode: string
  diff: SnapshotDiffPayload | null
  isEmpty?: boolean
  emptyState?: ReactNode
  onCopy: () => void
  onDownload: () => void
  onLoadDetails?: () => void
  pending?: boolean
  latencyMs?: number | null
}>) {
  const [view, setView] = useState<'changes' | 'raw'>('changes')
  const [toolsOpen, setToolsOpen] = useState(false)
  const toolsId = useId()
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('全部')
  const [change, setChange] = useState('全部')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<ChangeRow | null>(null)
  const before = recordSchema.safeParse(selected?.item.before).data
  const after = recordSchema.safeParse(selected?.item.after).data
  const beforeProps = recordSchema.safeParse(before?.props).data ?? {}
  const afterProps = recordSchema.safeParse(after?.props).data ?? {}
  const propertyKeys = [...new Set([...Object.keys(beforeProps), ...Object.keys(afterProps)])]
  useEffect(() => {
    setSelected(null)
    setPage(1)
  }, [diff])
  const ready = Boolean(diff) && !isEmpty
  const changes = useMemo(
    () =>
      groups.flatMap((group) =>
        exactDiffSample(diff, group.key).map((item, index) => {
          const id = typeof item.id === 'string' || typeof item.id === 'number' ? String(item.id) : ''
          return {
            key: JSON.stringify([group.key, id, index]),
            id,
            kind: group.kind,
            change: group.change,
            tone: group.tone,
            name: changeName(item),
            item,
          }
        }),
      ),
    [diff],
  )
  const searchTerm = query.trim().toLowerCase()
  const hasFilters = searchTerm !== '' || kind !== '全部' || change !== '全部'
  const filtered = useMemo(
    () =>
      changes.filter(
        (row) =>
          (kind === '全部' || row.kind === kind) &&
          (change === '全部' || row.change === change) &&
          `${row.name} ${row.id}`.toLowerCase().includes(searchTerm),
      ),
    [changes, kind, change, searchTerm],
  )
  const pageCount = Math.max(1, Math.ceil(filtered.length / CHANGE_PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const rawRows = useMemo(
    () => (view === 'raw' && ready ? buildSideBySideDiffRows(leftCode, rightCode) : []),
    [view, ready, leftCode, rightCode],
  )
  const detailed = diff?.node_diff != null || diff?.edge_diff != null || changes.length > 0
  const changeCount = exactDiffTotal(diff)
  const loadDetails =
    onLoadDetails && (!leftCode || !rightCode) ? (
      <Button variant="outline" disabled={pending} onClick={onLoadDetails}>
        读取完整快照
      </Button>
    ) : null
  return (
    <div className="flex h-full min-h-0 flex-col bg-background" aria-busy={pending}>
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2 md:px-6 md:py-3">
        <Button
          variant="outline"
          className="md:hidden"
          aria-label="筛选与视图"
          aria-expanded={toolsOpen}
          aria-controls={toolsId}
          onClick={() => setToolsOpen((open) => !open)}
        >
          <SlidersHorizontal className="size-4" aria-hidden="true" />
          筛选与视图{hasFilters ? ' · 已筛选' : ''}
        </Button>
        <div
          id={toolsId}
          className={cn('min-w-0 flex-wrap items-center gap-2 md:contents', toolsOpen ? 'flex w-full' : 'hidden')}
        >
          <div role="group" aria-label="对比阅读方式" className="flex shrink-0 gap-1">
            <Button
              variant={view === 'changes' ? 'secondary' : 'ghost'}
              aria-pressed={view === 'changes'}
              onClick={() => setView('changes')}
            >
              变更明细
            </Button>
            <Button
              variant={view === 'raw' ? 'secondary' : 'ghost'}
              aria-pressed={view === 'raw'}
              onClick={() => setView('raw')}
            >
              原始对照
            </Button>
          </div>
          {ready && view === 'changes' ? (
            <div className="order-2 grid w-full grid-cols-2 gap-2 min-[375px]:grid-cols-[minmax(0,1fr)_auto_auto] md:order-none md:flex md:w-auto md:flex-1 md:items-center">
              <Input
                aria-label="搜索变更对象"
                className="col-span-2 min-[375px]:col-span-1 md:ml-3 md:w-56"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value)
                  setPage(1)
                }}
                placeholder="搜索变更"
              />
              <select
                aria-label="变更对象类别"
                className="h-11 min-w-0 rounded-md border border-border bg-background px-3 text-sm md:h-9"
                value={kind}
                onChange={(event) => {
                  setKind(event.target.value)
                  setPage(1)
                }}
              >
                <option value="全部">全部类别</option>
                <option>节点</option>
                <option>关系</option>
              </select>
              <select
                aria-label="变更类型"
                className="h-11 min-w-0 rounded-md border border-border bg-background px-3 text-sm md:h-9"
                value={change}
                onChange={(event) => {
                  setChange(event.target.value)
                  setPage(1)
                }}
              >
                <option value="全部">全部变更</option>
                <option>新增</option>
                <option>移除</option>
                <option>更新</option>
              </select>
            </div>
          ) : null}
          <div className="ml-auto flex shrink-0 gap-1">
            <Button variant="ghost" size="icon" aria-label="复制对比结果" onClick={onCopy} disabled={!ready}>
              <Copy />
            </Button>
            <Button variant="ghost" size="icon" aria-label="导出对比结果" onClick={onDownload} disabled={!ready}>
              <Download />
            </Button>
          </div>
        </div>
      </div>
      {!ready ? (
        pending ? (
          <div role="status" className="flex min-h-0 flex-1 items-center justify-center px-6">
            <div className={ws.empty}>
              <Loader2 className="size-5 animate-spin text-muted-foreground motion-reduce:animate-none" />
              <h2>正在读取快照并生成对比</h2>
              <p>完成后将显示节点和关系的变化。</p>
            </div>
          </div>
        ) : (
          emptyState
        )
      ) : view === 'raw' ? (
        <div role="region" aria-label="快照原始对照" tabIndex={0} className="min-h-0 flex-1 overflow-auto">
          {leftCode && rightCode ? (
            <div className="min-w-[980px]">
              <div className="sticky top-0 z-10 grid grid-cols-[48px_minmax(0,1fr)_48px_minmax(0,1fr)] border-b border-border bg-background text-[13px]">
                <span className="p-3 text-right text-muted-foreground">#</span>
                <div className="p-3">
                  <strong>{titleA}</strong>
                  <p className="mt-1 text-xs text-muted-foreground">{subtitleA}</p>
                </div>
                <span className="p-3 text-right text-muted-foreground">#</span>
                <div className="p-3">
                  <strong>{titleB}</strong>
                  <p className="mt-1 text-xs text-muted-foreground">{subtitleB}</p>
                </div>
              </div>
              {rawRows.map((row, index) => (
                <div key={index} className="grid grid-cols-[48px_minmax(0,1fr)_48px_minmax(0,1fr)]">
                  <JsonDiffCell cell={row.left} side="left" />
                  <JsonDiffCell cell={row.right} side="right" />
                </div>
              ))}
            </div>
          ) : (
            <div className="px-6">
              <div className={ws.empty}>
                <h2>尚未读取完整快照内容</h2>
                <p>当前结果可查看数量摘要，读取两份快照后可逐行对照。</p>
                {loadDetails}
              </div>
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-auto px-4 md:px-6">
            {filtered.length ? (
              <WorkspaceTableScroll label="快照变更表格">
                <table className={cn(ws.table, 'min-w-[300px] sm:min-w-[640px]')} aria-label="快照变更明细">
                  <thead>
                    <tr>
                      <th>对象</th>
                      <th className="hidden sm:table-cell">类别</th>
                      <th className="hidden sm:table-cell">变化</th>
                      <th className="hidden sm:table-cell">标识</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.slice((currentPage - 1) * CHANGE_PAGE_SIZE, currentPage * CHANGE_PAGE_SIZE).map((row) => (
                      <tr key={row.key}>
                        <td className="max-w-[140px] sm:max-w-[320px]">
                          <div className="truncate font-medium" title={row.name}>
                            {row.name}
                          </div>
                          <p className="sm:hidden">
                            {row.kind} · <span className={row.tone}>{row.change}</span>
                          </p>
                        </td>
                        <td className="hidden sm:table-cell">{row.kind}</td>
                        <td className="hidden sm:table-cell">
                          <span className={row.tone}>{row.change}</span>
                        </td>
                        <td className="hidden max-w-[240px] truncate font-mono text-xs sm:table-cell" title={row.id}>
                          {row.id === '' ? '—' : row.id}
                        </td>
                        <td>
                          <Button variant="ghost" aria-label={`查看变更 ${row.name}`} onClick={() => setSelected(row)}>
                            查看内容
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </WorkspaceTableScroll>
            ) : (
              <div className={ws.empty}>
                <h2>
                  {hasFilters
                    ? '没有匹配的变更'
                    : detailed && changeCount === 0
                      ? '没有返回节点或关系变更'
                      : '当前结果没有条目明细'}
                </h2>
                <p>
                  {detailed
                    ? '可调整筛选，或切换到原始对照查看快照内容。'
                    : '可在统计页查看数量摘要，或切换到快照 A / B 查看元信息。'}
                </p>
                {hasFilters ? (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setQuery('')
                      setKind('全部')
                      setChange('全部')
                      setPage(1)
                    }}
                  >
                    清除筛选
                  </Button>
                ) : (
                  loadDetails
                )}
              </div>
            )}
          </div>
          {filtered.length ? (
            <div
              data-task-center-dock
              className="flex shrink-0 items-center justify-between gap-3 border-t border-border px-4 py-3 text-[13px] md:px-6"
            >
              <div className="min-w-0 text-muted-foreground">
                <p>
                  {changeCount !== undefined ? `${changeCount} 项变化` : '变更总数未取得'}
                  {changeCount !== changes.length ? ` · 预览 ${changes.length} 项` : ''}
                  {hasFilters ? ` · 匹配 ${filtered.length} 项` : ''}
                </p>
                <p className="text-xs">
                  {CHANGE_PAGE_SIZE} 项/页{latencyMs != null ? ` · ${latencyMs} ms` : ''}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="上一页变更"
                  disabled={currentPage === 1}
                  onClick={() => setPage(currentPage - 1)}
                >
                  <ChevronLeft />
                </Button>
                <span className="whitespace-nowrap tabular-nums">
                  {currentPage} / {pageCount}
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="下一页变更"
                  disabled={currentPage === pageCount}
                  onClick={() => setPage(currentPage + 1)}
                >
                  <ChevronRight />
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}
      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null)
        }}
      >
        <DialogContent className={ws.dialog}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>变更详情</DialogTitle>
            <DialogDescription className="break-all">{selected?.name}</DialogDescription>
          </DialogHeader>
          <div className={ws.dialogBody}>
            {selected ? (
              <>
                <div className="mb-4 flex items-center gap-3 text-sm">
                  <Badge variant="outline">{selected.kind}</Badge>
                  <span className={selected.tone}>{selected.change}</span>
                </div>
                {propertyKeys.length ? (
                  <WorkspaceTableScroll label="变更属性对照">
                    <table className={ws.table} aria-label="变更属性对照">
                      <thead>
                        <tr>
                          <th>属性</th>
                          <th>版本 A</th>
                          <th>版本 B</th>
                        </tr>
                      </thead>
                      <tbody>
                        {propertyKeys.map((key) => (
                          <tr key={key}>
                            <th scope="row">{key}</th>
                            <td className="break-words">
                              {Object.hasOwn(beforeProps, key) ? propertyText(beforeProps[key]) : '未设置'}
                            </td>
                            <td className="break-words">
                              {Object.hasOwn(afterProps, key) ? propertyText(afterProps[key]) : '未设置'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </WorkspaceTableScroll>
                ) : null}
                <details className="mt-5" open={propertyKeys.length ? undefined : true}>
                  <summary className="cursor-pointer text-[13px] font-medium">原始变更数据</summary>
                  <pre className="mt-3 overflow-x-auto whitespace-pre text-[13px] leading-6">
                    {JSON.stringify(selected.item, null, 2)}
                  </pre>
                </details>
              </>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
