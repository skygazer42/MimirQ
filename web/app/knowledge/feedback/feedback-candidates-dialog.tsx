'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Loader2 } from '@/components/icons'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { feedbackApi } from '@/lib/api'
import { displayText } from './feedback-inbox-model'
import styles from './feedback.module.css'

type CandidateTab = 'hard' | 'triples' | 'rules'

export function FeedbackCandidatesDialog({ open, onOpenChange }: Readonly<{ open: boolean; onOpenChange: (open: boolean) => void }>) {
  const [tab, setTab] = useState<CandidateTab>('hard')
  const query = useQuery({
    queryKey: ['feedback-loop-candidates'],
    queryFn: ({ signal }) => feedbackApi.loopCandidates({ max_rating: 2, limit: 200, ruleset: 'industrial_control' }, { signal }),
    enabled: open,
    staleTime: 15_000,
    retry: false,
  })
  const data = query.data
  const suggestions = data?.rules_suggestions || {}
  const rules = ['glossary_suggestions', 'pattern_suggestions', 'intent_suggestions'].flatMap(key => Array.isArray(suggestions[key]) ? suggestions[key] as unknown[] : [])
  const records = tab === 'hard' ? data?.hard_negative_records || [] : tab === 'triples' ? data?.training_triples || [] : rules
  const tabs: { id: CandidateTab; label: string; count: number }[] = [{ id: 'hard', label: '困难负样本', count: data?.hard_negative_records.length || 0 }, { id: 'triples', label: '训练三元组', count: data?.training_triples.length || 0 }, { id: 'rules', label: '规则候选', count: rules.length }]

  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className={styles.candidateDialog}>
    <DialogHeader className={styles.candidateHeader}><DialogTitle>反哺候选</DialogTitle><DialogDescription>查看低分反馈生成的训练与规则候选。</DialogDescription></DialogHeader>
    <div className={styles.candidateTabs} role="group" aria-label="候选类型">{tabs.map(item => <button type="button" key={item.id} aria-pressed={tab === item.id} onClick={() => setTab(item.id)}>{item.label}{data && <span>{item.count}</span>}</button>)}</div>
    <div className={styles.candidateBody}>
      {query.isPending ? <div className={styles.queueState} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" />正在读取候选…</div> : query.isError ? <div className={styles.queueState} role="alert"><AlertCircle /><p>候选加载失败</p><Button variant="outline" onClick={() => void query.refetch()}>重试</Button></div> : !records.length ? <div className={styles.queueState}><p>暂无{tabs.find(item => item.id === tab)?.label}</p></div> : <ol className={styles.candidateList}>{records.map((value, index) => {
        const record = value && typeof value === 'object' ? value as Record<string, unknown> : {}
        const title = displayText(record.query, record.question, record.token, record.pattern, record.intent, record.source_feedback_id) || `候选 ${index + 1}`
        return <li key={index}><div className={styles.candidateTitle}><span>{index + 1}</span><strong>{title}</strong></div><details><summary>查看候选内容</summary><pre>{JSON.stringify(value, null, 2)}</pre></details></li>
      })}</ol>}
    </div>
  </DialogContent></Dialog>
}
