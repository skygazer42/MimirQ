'use client'

import * as React from 'react'
import dynamic from 'next/dynamic'
import { Route } from 'lucide-react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { PageLoading } from '@/components/ui/page-loading'

const RagTracePanel = dynamic(() => import('@/components/rag-trace/rag-trace-panel').then((mod) => mod.RagTracePanel), {
  ssr: false,
  loading: () => <PageLoading message="正在加载 RAG Trace..." srMessage="Loading RAG trace panel" className="min-h-[50vh]" />,
})

type RagTraceDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  conversationId: string | null
  title?: string | null
}

export function RagTraceDialog({ open, onOpenChange, conversationId, title }: Readonly<RagTraceDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Route className="h-5 w-5 text-sky-600 dark:text-sky-400" />
            <span>RAG Trace</span>
            {title ? <span className="text-sm font-normal text-muted-foreground">· {title}</span> : null}
          </DialogTitle>
        </DialogHeader>
        {conversationId ? (
          <div className="min-h-0 overflow-hidden">
            <RagTracePanel conversationId={conversationId} className="min-h-0" />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
