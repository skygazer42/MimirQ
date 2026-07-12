'use client'

import * as React from 'react'
import dynamic from 'next/dynamic'
import { Route } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { PageLoading } from '@/components/ui/page-loading'

function RagTraceDialogLoading() {
  const t = useTranslations('RagTrace')

  return (
    <PageLoading
      message={t("dialog.loadingMessage")}
      srMessage={t("dialog.loadingSrMessage")}
      className="min-h-[50vh]"
    />
  )
}

const RagTracePanel = dynamic(() => import('@/components/rag-trace/rag-trace-panel').then((mod) => mod.RagTracePanel), {
  ssr: false,
  loading: () => <RagTraceDialogLoading />,
})

type RagTraceDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  conversationId: string | null
  title?: string | null
}

export function RagTraceDialog({ open, onOpenChange, conversationId, title }: Readonly<RagTraceDialogProps>) {
  const t = useTranslations('RagTrace')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] max-w-6xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="shrink-0 border-b border-border/60 px-6 py-4 pr-12">
          <DialogTitle className="flex items-center gap-2">
            <Route className="h-5 w-5 text-info" />
            <span>{t("dialog.title")}</span>
            {title ? <span className="text-sm font-normal text-muted-foreground">· {title}</span> : null}
          </DialogTitle>
        </DialogHeader>
        {conversationId ? (
          <div className="min-h-0 overflow-y-auto px-6 py-4">
            <RagTracePanel conversationId={conversationId} className="min-h-0" />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
