'use client'

import { useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GitBranch, Loader2 } from '@/components/icons'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { lineageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'

type AnswerLineageActionProps = Readonly<{
  requestId: string
}>

export function AnswerLineageAction({ requestId }: AnswerLineageActionProps) {
  const [open, setOpen] = useState(false)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 rounded-lg px-2 text-[11px] text-muted-foreground hover:text-foreground"
        >
          <GitBranch className="h-3.5 w-3.5" aria-hidden="true" />
          答案血缘
        </Button>
      </DialogTrigger>

      {open && (
        <DialogContent className="flex max-h-[90dvh] max-w-3xl flex-col overflow-hidden border-border bg-background/95 shadow-strong sm:rounded-2xl">
          <DialogHeader className="min-w-0 shrink-0 pr-8">
            <DialogTitle className="flex items-center gap-2">
              <GitBranch className="size-4 text-info" aria-hidden="true" />
              答案血缘
            </DialogTitle>
            <DialogDescription className="font-mono text-xs [overflow-wrap:anywhere]">
              request_id={requestId}
            </DialogDescription>
          </DialogHeader>

          <AnswerLineageDetails key={requestId} requestId={requestId} />
        </DialogContent>
      )}
    </Dialog>
  )
}

function AnswerLineageDetails({ requestId }: AnswerLineageActionProps) {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const lineageQuery = useQuery({
    queryKey: [...queryKeys.lineage.answer(requestId), sessionKey],
    queryFn: ({ signal }) => lineageApi.getAnswerLineageIfAvailable(requestId, { signal }),
    staleTime: 0,
  })
  const reading = lineageQuery.fetchStatus !== 'idle'
  const lineage = lineageQuery.data

  return (
    <div className="flex min-h-0 min-w-0 flex-col gap-3">
      {reading && (
        <p role="status" className="flex shrink-0 items-center gap-2 text-sm text-muted-foreground">
          {lineageQuery.isFetching && (
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          )}
          {lineageQuery.isPaused ? '血缘读取已暂停' : lineageQuery.isLoading ? '正在读取血缘…' : '正在刷新血缘…'}
        </p>
      )}
      {lineageQuery.isError && !reading && (
        <p role="alert" className="text-sm text-destructive">
          {formatApiError(lineageQuery.error, '加载答案血缘失败')}
        </p>
      )}
      {lineageQuery.isSuccess && !reading && lineage === null && (
        <p className="text-sm text-muted-foreground">该回答暂无血缘数据。</p>
      )}
      {lineage !== undefined && lineage !== null && (
        <pre
          aria-busy={lineageQuery.isFetching}
          className="min-h-0 max-h-[520px] overflow-auto whitespace-pre-wrap rounded-lg border border-border/60 bg-muted/20 p-3 text-xs [overflow-wrap:anywhere]"
        >
          {JSON.stringify(lineage, null, 2)}
        </pre>
      )}
      <Button
        type="button"
        variant="outline"
        className="shrink-0 self-start"
        disabled={reading}
        onClick={() => void lineageQuery.refetch({ cancelRefetch: false })}
      >
        重新读取
      </Button>
    </div>
  )
}
