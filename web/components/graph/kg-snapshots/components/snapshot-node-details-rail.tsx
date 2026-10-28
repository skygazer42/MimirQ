'use client'

import { ChevronRight, X } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { SnapshotStudioNode } from '../types'

export function SnapshotNodeDetailsRail({ selectedNode, onClose, onSelectRelationTarget, className, hideHeader = false }: Readonly<{
  selectedNode: SnapshotStudioNode | null
  onClose: () => void
  onSelectRelationTarget: (targetId: string) => void
  className?: string
  hideHeader?: boolean
}>) {
  if (!selectedNode) return null
  return <aside className={cn('flex min-h-0 min-w-0 flex-col', className)}>
    {!hideHeader ? <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-4"><h2 className="text-[15px] font-semibold">节点详情</h2><Button variant="ghost" size="icon" aria-label="收起节点详情" onClick={onClose}><X /></Button></div> : null}
    <div className={cn('min-h-0 flex-1 space-y-5 overflow-y-auto', hideHeader ? '' : 'p-5')}>
      <div><h3 className="break-words text-base font-semibold">{selectedNode.label}</h3><p className="mt-2 break-all font-mono text-xs text-muted-foreground">{selectedNode.id}</p><Badge variant="outline" className="mt-3">{selectedNode.type}</Badge></div>
      <section className="border-t border-border pt-5"><h3 className="text-sm font-semibold">属性</h3><dl className="mt-4 space-y-4 text-[13px] leading-6">{[['名称', selectedNode.label], ['类型', selectedNode.type], ['描述', selectedNode.description || '—']].map(([label, value]) => <div key={label} className="grid grid-cols-[48px_minmax(0,1fr)] gap-3"><dt className="text-muted-foreground">{label}</dt><dd className="break-words">{value}</dd></div>)}</dl></section>
      <section className="border-t border-border pt-5"><h3 className="text-sm font-semibold">预览中关联（{selectedNode.relations.length}）</h3><div className="mt-3 divide-y divide-border">{selectedNode.relations.map(relation => <button key={`${relation.label}:${relation.target}`} type="button" className="flex w-full items-center justify-between gap-3 py-3 text-left text-[13px] hover:text-primary" onClick={() => onSelectRelationTarget(relation.targetId)}><span className="inline-flex items-center gap-1 text-muted-foreground"><ChevronRight className="size-4 shrink-0" />{relation.label}</span><span className="min-w-0 truncate font-medium" title={relation.target}>{relation.target}</span></button>)}{!selectedNode.relations.length ? <p className="py-4 text-[13px] text-muted-foreground">当前预览未返回关联关系</p> : null}</div></section>
    </div>
  </aside>
}
