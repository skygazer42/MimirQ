'use client'

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GitBranch, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { lineageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

type AnswerLineageActionProps = Readonly<{
  requestId: string
}>

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function AnswerLineageAction({ requestId }: AnswerLineageActionProps) {
  const [open, setOpen] = useState(false)
  const lineageQuery = useQuery({
    queryKey: queryKeys.lineage.answer(requestId),
    enabled: open,
    queryFn: () => lineageApi.getAnswerLineage(requestId),
  })
  const error = lineageQuery.error
    ? formatApiError(lineageQuery.error, '加载答案血缘失败')
    : null

  useEffect(() => {
    if (!error) return
    toast.error(error)
  }, [error])

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 gap-1.5 rounded-lg px-2 text-[11px] text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(true)}
      >
        {lineageQuery.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <GitBranch className="h-3.5 w-3.5" />}
        答案血缘
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-3xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-info" />
              Answer Lineage
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">request_id={requestId}</DialogDescription>
          </DialogHeader>

          {error ? <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null}
          <pre className={cn('max-h-[520px] overflow-auto rounded-lg border border-border/60 bg-muted/20 p-3 text-xs', 'whitespace-pre-wrap break-words')}>
            {lineageQuery.isFetching ? 'Loading...' : prettyJson(lineageQuery.data ?? { message: '暂无血缘数据' })}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  )
}
