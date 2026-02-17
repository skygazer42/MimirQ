'use client'

import type { LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import { IconButton } from '@/components/ui/icon-button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'

type WorkbenchPanelDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: React.ReactNode

  /**
   * Optional trigger. If omitted, provide `triggerIcon` + `triggerLabel`.
   */
  trigger?: React.ReactNode
  triggerIcon?: LucideIcon
  triggerLabel?: string

  className?: string
}

export function WorkbenchPanelDialog({
  open,
  onOpenChange,
  title,
  children,
  trigger,
  triggerIcon: TriggerIcon,
  triggerLabel,
  className,
}: WorkbenchPanelDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {trigger ? (
        <DialogTrigger asChild>{trigger}</DialogTrigger>
      ) : TriggerIcon && triggerLabel ? (
        <DialogTrigger asChild>
          <IconButton label={triggerLabel} variant="ghost">
            <TriggerIcon className="size-4" />
          </IconButton>
        </DialogTrigger>
      ) : null}

      <DialogContent
        className={cn(
          'w-[92vw] max-w-[92vw] h-[85vh] max-h-[85vh] p-0 overflow-hidden grid grid-rows-[auto_1fr]',
          className
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
