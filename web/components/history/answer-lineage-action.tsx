'use client'

import { useState } from 'react'
import { GitBranch, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { lineageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

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
  const [loading, setLoading] = useState(false)
  const [payload, setPayload] = useState<unknown>(null)
  const [error, setError] = useState<string | null>(null)

  async function loadLineage(): Promise<void> {
    setOpen(true)
    setLoading(true)
    setError(null)
    try {
      const next = await lineageApi.getAnswerLineage(requestId)
      setPayload(next)
    } catch (err) {
      const message = formatApiError(err, '加载答案血缘失败')
      setError(message)
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 gap-1.5 rounded-lg px-2 text-[11px] text-muted-foreground hover:text-foreground"
        onClick={() => detachPromise(loadLineage())}
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <GitBranch className="h-3.5 w-3.5" />}
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
            {loading ? 'Loading...' : prettyJson(payload ?? { message: '暂无血缘数据' })}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  )
}
