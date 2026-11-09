'use client'

import type { Ref } from 'react'
import { ExternalLink, GitBranch, Loader2, X } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { coerceTrimmedString, getGraphNodeKind, type GraphNodeLike } from '../graph-page-utils'
import { graphTypeLabel } from '../graph-directory-model'
import type { KGEntityDetailResponse, KGEventDetailResponse } from '@/types'
import styles from './graph-workspace.module.css'

type Props = {
  detailsButtonRef?: Ref<HTMLButtonElement>
  node: GraphNodeLike
  count: number
  detail: KGEntityDetailResponse | KGEventDetailResponse | null
  loading: boolean
  onDetails: () => void
  onExpand: () => void
  onSource: () => void
  onClose: () => void
}

export function GraphSelectionSummary({ detailsButtonRef, node, count, detail, loading, onDetails, onExpand, onSource, onClose }: Readonly<Props>) {
  const entity = detail && 'entity' in detail && detail.entity.id === node.id ? detail.entity : null
  const event = detail && 'event' in detail && detail.event.id === node.id ? detail.event : null
  const description = entity?.description || event?.summary || coerceTrimmedString(node.meta?.description)
  const canViewSource = Boolean(event?.document_id || event?.chunk_id || (entity && detail && 'events' in detail && detail.events.some(item => item.document_id || item.chunk_id)) || node.meta?.document_id || node.meta?.chunk_id)
  return <section className={styles.selectionSummary} aria-label="当前实体摘要" data-graph-selection>
    <div className={styles.selectionTitle}><h2 title={node.label || node.id}>{node.label || node.id}</h2><span>{graphTypeLabel(node)}</span><button type="button" className="focus-ring" aria-label="取消实体选择" onClick={onClose}><X /></button></div>
    <div className={styles.selectionMeta}>{loading ? <><Loader2 className="animate-spin motion-reduce:animate-none" />正在读取详情</> : <>{count} 个直接关联{entity?.normalized_name && entity.normalized_name !== node.label ? ` · ${entity.normalized_name}` : ''}</>}</div>
    {description ? <p>{description}</p> : null}
    <div className={styles.selectionActions}><Button ref={detailsButtonRef} variant="ghost" onClick={onDetails}><ExternalLink />查看详情与来源</Button>{canViewSource ? <Button variant="ghost" onClick={onSource}>查看原文</Button> : null}{getGraphNodeKind(node) === 'entity' ? <Button variant="outline" onClick={onExpand} disabled={loading}><GitBranch />展开邻居</Button> : null}</div>
  </section>
}
