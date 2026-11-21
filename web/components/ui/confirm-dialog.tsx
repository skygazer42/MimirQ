'use client'

import * as React from 'react'
import * as AlertDialogPrimitive from '@radix-ui/react-alert-dialog'
import { useTranslations } from 'next-intl'

import type { ButtonProps } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { formatApiError } from '@/lib/api-errors'

type ConfirmDialogProps = {
  title: React.ReactNode
  description?: React.ReactNode
  confirmLabel?: string
  cancelLabel?: string
  confirmVariant?: ButtonProps['variant']
  confirmDisabled?: boolean
  open?: boolean
  onOpenChange?: (open: boolean) => void
  // 异步操作返回原 Promise；失败抛出，由弹窗保留上下文并显示错误。
  onConfirm: () => void | Promise<void>
  children: React.ReactElement
}

export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel,
  confirmVariant = 'destructive',
  confirmDisabled = false,
  open,
  onOpenChange,
  onConfirm,
  children,
}: Readonly<ConfirmDialogProps>) {
  const t = useTranslations('CommonUi')
  const [internalOpen, setInternalOpen] = React.useState(false)
  const [pending, setPending] = React.useState(false)
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null)
  const pendingRef = React.useRef(false)
  const mountedRef = React.useRef(false)
  React.useLayoutEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])
  const resolvedConfirmLabel = confirmLabel ?? t('confirmDialog.confirm')
  const resolvedCancelLabel = cancelLabel ?? t('confirmDialog.cancel')
  const isOpen = open === undefined ? internalOpen : open
  const hasDescription = description !== undefined && description !== null

  const changeOpen = (next: boolean) => {
    if (open === undefined) setInternalOpen(next)
    if (!next) setErrorMessage(null)
    onOpenChange?.(next)
  }
  const handleConfirm = async (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    if (pendingRef.current) return
    pendingRef.current = true
    setPending(true)
    setErrorMessage(null)
    try {
      await onConfirm()
    } catch (error) {
      if (mountedRef.current) setErrorMessage(formatApiError(error, t('confirmDialog.failed')))
      return
    } finally {
      pendingRef.current = false
      if (mountedRef.current) setPending(false)
    }
    if (mountedRef.current) changeOpen(false)
  }

  return (
    <AlertDialog
      open={isOpen}
      onOpenChange={(next) => {
        if (!pendingRef.current) changeOpen(next)
      }}
    >
      <AlertDialogTrigger asChild>{children}</AlertDialogTrigger>
      <AlertDialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        {...(hasDescription ? {} : { 'aria-describedby': undefined })}
        onEscapeKeyDown={(event) => {
          if (pendingRef.current) event.preventDefault()
        }}
      >
        <AlertDialogHeader className="min-w-0 break-words">
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {hasDescription ? <AlertDialogDescription>{description}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        {errorMessage !== null ? (
          <p role="alert" className="min-w-0 break-words text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{resolvedCancelLabel}</AlertDialogCancel>
          <AlertDialogPrimitive.Action asChild>
            <LoadingButton
              type="button"
              disabled={confirmDisabled}
              loading={pending}
              onClick={handleConfirm}
              variant={confirmVariant}
              size="sm"
            >
              {resolvedConfirmLabel}
            </LoadingButton>
          </AlertDialogPrimitive.Action>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
