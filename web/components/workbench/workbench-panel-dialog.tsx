'use client'

import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

type WorkbenchPanelDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: ReactNode

  className?: string
}

export function WorkbenchPanelDialog({
  open,
  onOpenChange,
  title,
  children,
  className,
}: Readonly<WorkbenchPanelDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-describedby={undefined}
        className={cn(
          'w-[92vw] max-w-[92vw] h-[85vh] max-h-[85vh] p-0 overflow-hidden grid grid-rows-[auto_1fr]',
          className,
        )}
      >
        <DialogHeader className="px-4 pt-4 pb-2">
          <DialogTitle className="text-base">{title}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 overflow-hidden flex flex-col">{children}</div>
      </DialogContent>
    </Dialog>
  )
}
