'use client'

import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'

import { Route } from '@/components/icons'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { PageLoading } from '@/components/ui/page-loading'

function RagTraceDialogLoading() {
  const t = useTranslations('RagTrace')

  return (
    <PageLoading
      message={t('dialog.loadingMessage')}
      srMessage={t('dialog.loadingSrMessage')}
      className="min-h-[50vh]"
    />
  )
}

const RagTracePanel = dynamic(() => import('@/components/rag-trace/rag-trace-panel').then((mod) => mod.RagTracePanel), {
  ssr: false,
  loading: RagTraceDialogLoading,
})

type RagTraceDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  conversationId: string | null
  title?: string | null
}

export function RagTraceDialog({ open, onOpenChange, conversationId, title }: Readonly<RagTraceDialogProps>) {
  const t = useTranslations('RagTrace')

  if (!open) return null

  const traceConversationId = conversationId?.trim()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-describedby={undefined}
        className="flex max-h-[90dvh] max-w-6xl flex-col gap-0 overflow-hidden p-0"
      >
        <DialogHeader className="shrink-0 border-b border-border/60 px-6 py-4 pr-12">
          <DialogTitle className="flex items-center gap-2">
            <Route className="size-5 shrink-0 text-info" aria-hidden="true" />
            <span className="shrink-0">{t('dialog.title')}</span>
            {title ? (
              <span
                className="line-clamp-2 min-w-0 text-sm font-normal text-muted-foreground [overflow-wrap:anywhere]"
                title={title}
              >
                · {title}
              </span>
            ) : null}
          </DialogTitle>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto px-6 py-4">
          {traceConversationId ? (
            <RagTracePanel
              key={traceConversationId}
              conversationId={traceConversationId}
              onCitationOpen={() => onOpenChange(false)}
            />
          ) : (
            <p role="status" className="text-sm text-muted-foreground">
              当前没有可追踪的会话。
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
