'use client'

import { useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from '@/components/icons'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { feedbackApi } from '@/lib/api/feedback'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import styles from './feedback.module.css'

const CANDIDATE_TABS = [
  { id: 'hard', label: '困难负样本' },
  { id: 'triples', label: '训练三元组' },
  { id: 'rules', label: '规则候选' },
] as const
type CandidateTab = (typeof CANDIDATE_TABS)[number]
const CANDIDATE_QUERY = { max_rating: 2, limit: 200, ruleset: 'industrial_control' } as const

export function FeedbackCandidatesDialog({
  open,
  onOpenChange,
}: Readonly<{ open: boolean; onOpenChange: (open: boolean) => void }>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={styles.candidateDialog}>
        <DialogHeader className={styles.candidateHeader}>
          <DialogTitle>反哺候选</DialogTitle>
          <DialogDescription>
            查看不高于 {CANDIDATE_QUERY.max_rating} 分、最多 {CANDIDATE_QUERY.limit} 条反馈生成的候选；规则集为{' '}
            {CANDIDATE_QUERY.ruleset}。
          </DialogDescription>
        </DialogHeader>
        <FeedbackCandidatesContent />
      </DialogContent>
    </Dialog>
  )
}

function FeedbackCandidatesContent() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const [tab, setTab] = useState<CandidateTab>(CANDIDATE_TABS[0])
  const query = useQuery({
    queryKey: ['feedback-loop-candidates', sessionKey, CANDIDATE_QUERY],
    queryFn: ({ signal }) => feedbackApi.loopCandidates(CANDIDATE_QUERY, { signal }),
    staleTime: 15_000,
    retry: false,
  })
  const data = query.data
  const recordsByTab =
    data === undefined
      ? undefined
      : {
          hard: data.hard_negative_records,
          triples: data.training_triples,
          rules: [
            ...data.rules_suggestions.glossary_suggestions,
            ...data.rules_suggestions.pattern_suggestions,
            ...data.rules_suggestions.intent_suggestions,
          ],
        }
  const records = recordsByTab?.[tab.id]
  const occurrences = new Map<string, number>()
  return (
    <>
      <div className={styles.candidateTabs} role="group" aria-label="候选类型">
        {CANDIDATE_TABS.map((item) => (
          <button type="button" key={item.id} aria-pressed={tab.id === item.id} onClick={() => setTab(item)}>
            {item.label}
            {recordsByTab !== undefined && <span>{recordsByTab[item.id].length}</span>}
          </button>
        ))}
      </div>
      <div className={styles.candidateBody} aria-busy={query.isFetching}>
        {query.isFetching && records !== undefined && (
          <p role="status" className={styles.sectionMeta}>
            正在刷新候选…
          </p>
        )}
        {query.isError && (
          <div className={styles.contextError} role="alert">
            <AlertCircle />
            <p>{formatApiError(query.error, '候选加载失败')}</p>
            <Button
              type="button"
              variant="outline"
              disabled={query.isFetching}
              onClick={() => void query.refetch({ cancelRefetch: false })}
            >
              重试
            </Button>
          </div>
        )}
        {records === undefined ? (
          query.isPending && query.isPaused ? (
            <p role="status" className={styles.sectionMeta}>
              等待网络连接
            </p>
          ) : query.isPending ? (
            <div role="status">
              <span className="sr-only">正在读取候选…</span>
              <ol className={styles.candidateList} aria-hidden="true">
                {[0, 1, 2, 3].map((index) => (
                  <li key={index}>
                    <Skeleton className="h-5 w-2/3" />
                    <Skeleton className="mt-3 h-3 w-24" />
                  </li>
                ))}
              </ol>
            </div>
          ) : null
        ) : records.length === 0 ? (
          <div className={styles.queueState}>
            <p>暂无{tab.label}</p>
          </div>
        ) : (
          <ol className={styles.candidateList}>
            {records.map((record, index) => {
              const identity = JSON.stringify(record)
              const occurrence = occurrences.get(identity) ?? 0
              occurrences.set(identity, occurrence + 1)
              const title = [
                record.query,
                record.question,
                record.token,
                record.pattern,
                record.intent,
                record.source_feedback_id,
              ].find((value): value is string => typeof value === 'string')
              return (
                <li key={JSON.stringify([tab.id, identity, occurrence])}>
                  <div className={styles.candidateTitle}>
                    <span>{index + 1}</span>
                    <strong>
                      {title === undefined ? `候选 ${index + 1}` : title.length === 0 ? '候选标题为空' : title}
                    </strong>
                  </div>
                  <details>
                    <summary>查看候选内容</summary>
                    <pre>{JSON.stringify(record, null, 2)}</pre>
                  </details>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </>
  )
}
