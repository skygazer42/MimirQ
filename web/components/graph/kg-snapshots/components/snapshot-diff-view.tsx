'use client'

import { Copy, Download, ChevronLeft, ChevronRight } from '@/components/icons'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { WorkspaceTableScroll, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { cn } from '@/lib/utils'
import { buildSideBySideDiffRows } from '../json-diff'
import type { SnapshotDiffPayload } from '../types'
import { exactDiffCount, exactDiffSample, firstDisplayString } from '../utils'
import { JsonDiffCell } from './json-code-pane'

const groups = [
  { key: 'nodes_added', kind: '节点', change: '新增', tone: 'text-success' },
  { key: 'nodes_removed', kind: '节点', change: '移除', tone: 'text-destructive' },
  { key: 'nodes_changed', kind: '节点', change: '更新', tone: 'text-warning' },
  { key: 'edges_added', kind: '关系', change: '新增', tone: 'text-success' },
  { key: 'edges_removed', kind: '关系', change: '移除', tone: 'text-destructive' },
  { key: 'edges_changed', kind: '关系', change: '更新', tone: 'text-warning' },
] as const
type ChangeRow = { key: string; kind: string; change: string; tone: string; name: string; item: Record<string, unknown> }

function changeName(item: Record<string, unknown>): string {
  const before = item.before as Record<string, unknown> | undefined
  const after = item.after as Record<string, unknown> | undefined
  return firstDisplayString(item.name, item.label, after?.name, after?.label, before?.name, before?.label, item.id)
}

export function SnapshotDiffView({ titleA, titleB, subtitleA, subtitleB, leftCode, rightCode, diff, isEmpty, emptyState, onCopy, onDownload, onLoadDetails, pending = false }: Readonly<{
  titleA: string; titleB: string; subtitleA?: string; subtitleB?: string
  leftCode: string; rightCode: string; diff: SnapshotDiffPayload | null
  isEmpty?: boolean; emptyState?: ReactNode
  onCopy: () => void; onDownload: () => void; onLoadDetails?: () => void; pending?: boolean
}>) {
  const [view, setView] = useState<'changes' | 'raw'>('changes')
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('全部')
  const [change, setChange] = useState('全部')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<ChangeRow | null>(null)
  useEffect(() => { setSelected(null); setPage(1) }, [diff])
  const ready = Boolean(diff) && !isEmpty
  const changes = useMemo(() => groups.flatMap(group => exactDiffSample(diff, group.key).map((item, index) => ({ key: `${group.key}:${String(item.id)}:${index}`, kind: group.kind, change: group.change, tone: group.tone, name: changeName(item), item }))), [diff])
  const filtered = useMemo(() => changes.filter(row => (kind === '全部' || row.kind === kind) && (change === '全部' || row.change === change) && `${row.name} ${String(row.item.id)}`.toLowerCase().includes(query.trim().toLowerCase())), [changes, kind, change, query])
  const pageCount = Math.max(1, Math.ceil(filtered.length / 20)), currentPage = Math.min(page, pageCount)
  const rawRows = useMemo(() => view === 'raw' && ready ? buildSideBySideDiffRows(leftCode, rightCode) : [], [view, ready, leftCode, rightCode])
  const detailed = Boolean(diff?.node_diff || diff?.edge_diff)
  const changeCount = (['node_diff', 'edge_diff'] as const).reduce((sum, key) => sum + exactDiffCount(diff?.[key], 'added_count') + exactDiffCount(diff?.[key], 'removed_count') + exactDiffCount(diff?.[key], 'changed_count'), 0)
  const loadDetails = onLoadDetails && (!leftCode || !rightCode) ? <Button variant="outline" disabled={pending} onClick={onLoadDetails}>读取完整快照</Button> : null
  return <div className="flex h-full min-h-0 flex-col bg-background">
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 md:px-6"><div role="group" aria-label="对比阅读方式" className="flex gap-1"><Button variant={view === 'changes' ? 'secondary' : 'ghost'} aria-pressed={view === 'changes'} onClick={() => setView('changes')}>变更明细</Button><Button variant={view === 'raw' ? 'secondary' : 'ghost'} aria-pressed={view === 'raw'} onClick={() => setView('raw')}>原始对照</Button></div><div className="flex gap-1"><Button variant="ghost" size="icon" aria-label="复制对比结果" onClick={onCopy} disabled={!ready}><Copy /></Button><Button variant="ghost" size="icon" aria-label="导出对比结果" onClick={onDownload} disabled={!ready}><Download /></Button></div></div>
    {!ready ? emptyState : view === 'raw' ? <div role="region" aria-label="快照原始对照" tabIndex={0} className="min-h-0 flex-1 overflow-auto">{leftCode && rightCode ? <div className="min-w-[980px]"><div className="sticky top-0 z-10 grid grid-cols-[48px_minmax(0,1fr)_48px_minmax(0,1fr)] border-b border-border bg-background text-[13px]"><span className="p-3 text-right text-muted-foreground">#</span><div className="p-3"><strong>{titleA}</strong><p className="mt-1 text-xs text-muted-foreground">{subtitleA}</p></div><span className="p-3 text-right text-muted-foreground">#</span><div className="p-3"><strong>{titleB}</strong><p className="mt-1 text-xs text-muted-foreground">{subtitleB}</p></div></div>{rawRows.map((row, index) => <div key={index} className="grid grid-cols-[48px_minmax(0,1fr)_48px_minmax(0,1fr)]"><JsonDiffCell cell={row.left} side="left" /><JsonDiffCell cell={row.right} side="right" /></div>)}</div> : <div className="px-6"><div className={ws.empty}><h2>尚未读取完整快照内容</h2><p>当前结果可查看数量摘要，读取两份快照后可逐行对照。</p>{loadDetails}</div></div>}</div> : <>
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-4 py-3 md:px-6"><Input aria-label="搜索变更对象" className="w-64 max-w-full" value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} placeholder="搜索对象名称或标识" /><select aria-label="变更对象类别" className="h-10 rounded-md border border-border bg-background px-3 text-sm" value={kind} onChange={event => { setKind(event.target.value); setPage(1) }}><option>全部</option><option>节点</option><option>关系</option></select><select aria-label="变更类型" className="h-10 rounded-md border border-border bg-background px-3 text-sm" value={change} onChange={event => { setChange(event.target.value); setPage(1) }}><option>全部</option><option>新增</option><option>移除</option><option>更新</option></select><span className="ml-auto text-[13px] text-muted-foreground">{detailed ? (changeCount === changes.length ? `${changeCount} 项变化` : `${changeCount} 项变化 · 当前预览 ${changes.length} 项`) : '数量摘要'}</span></div>
      <div className="min-h-0 flex-1 overflow-auto px-4 md:px-6">{filtered.length ? <WorkspaceTableScroll label="快照变更表格" stickyActions><table className={cn(ws.table, 'min-w-[300px] sm:min-w-[640px]')} aria-label="快照变更明细"><thead><tr><th>对象</th><th className="hidden sm:table-cell">类别</th><th className="hidden sm:table-cell">变化</th><th className="hidden sm:table-cell">标识</th><th>操作</th></tr></thead><tbody>{filtered.slice((currentPage - 1) * 20, currentPage * 20).map(row => <tr key={row.key}><td className="max-w-[140px] sm:max-w-[320px]"><div className="truncate font-medium" title={row.name}>{row.name}</div><p className="sm:hidden">{row.kind} · <span className={row.tone}>{row.change}</span></p></td><td className="hidden sm:table-cell">{row.kind}</td><td className="hidden sm:table-cell"><span className={row.tone}>{row.change}</span></td><td className="hidden max-w-[240px] truncate font-mono text-xs sm:table-cell" title={String(row.item.id)}>{String(row.item.id)}</td><td><Button variant="ghost" aria-label={`查看变更 ${row.name}`} onClick={() => setSelected(row)}>查看内容</Button></td></tr>)}</tbody></table></WorkspaceTableScroll> : <div className={ws.empty}><h2>{query || kind !== '全部' || change !== '全部' ? '没有匹配的变更' : detailed && changeCount === 0 ? '没有返回节点或关系变更' : '当前结果没有条目明细'}</h2><p>{detailed ? '可调整筛选，或切换到原始对照查看快照内容。' : '可在统计页查看数量摘要，或切换到快照 A / B 查看元信息。'}</p>{query || kind !== '全部' || change !== '全部' ? <Button variant="outline" onClick={() => { setQuery(''); setKind('全部'); setChange('全部'); setPage(1) }}>清除筛选</Button> : loadDetails}</div>}</div>
      {filtered.length ? <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border px-4 py-3 text-[13px] md:px-6"><span className="text-muted-foreground">匹配 {filtered.length} 项 · 每页 20 项</span><div className="flex items-center gap-3"><Button variant="outline" size="icon" aria-label="上一页变更" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft /></Button><span className="tabular-nums">{currentPage} / {pageCount}</span><Button variant="outline" size="icon" aria-label="下一页变更" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight /></Button></div></div> : null}
    </>}
    <Dialog open={selected !== null} onOpenChange={open => { if (!open) setSelected(null) }}><DialogContent className={ws.dialog}><DialogHeader className={ws.dialogHeader}><DialogTitle>变更详情</DialogTitle><DialogDescription className="break-all">{selected?.name}</DialogDescription></DialogHeader><div className={ws.dialogBody}>{selected ? <><div className="mb-4 flex items-center gap-3 text-sm"><Badge variant="outline">{selected.kind}</Badge><span className={selected.tone}>{selected.change}</span></div><pre className="overflow-x-auto whitespace-pre text-[13px] leading-6">{JSON.stringify(selected.item, null, 2)}</pre></> : null}</div></DialogContent></Dialog>
  </div>
}
