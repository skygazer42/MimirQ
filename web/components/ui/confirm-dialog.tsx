/**
 * ConfirmDialog - Baseline UI wrapper for confirmations.
 *
 * Prefer this over native `globalThis.window.confirm` dialogs so we keep:
 * - consistent styling (token-first)
 * - keyboard/focus behavior (Radix)
 * - reduced-motion support
 */
"use client"

import * as React from "react"
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog"
import { useTranslations } from 'next-intl'

import { buttonVariants, type ButtonProps } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { cn, detachPromise } from '@/lib/utils'

type ConfirmDialogProps = {
  title: React.ReactNode
  description?: React.ReactNode
  confirmLabel?: string
  cancelLabel?: string
  confirmVariant?: ButtonProps["variant"]
  confirmDisabled?: boolean
  onConfirm: () => void | Promise<void>
  children: React.ReactNode
}

export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel,
  confirmVariant = "destructive",
  confirmDisabled = false,
  onConfirm,
  children,
}: Readonly<ConfirmDialogProps>) {
  const t = useTranslations('CommonUi')
  const resolvedConfirmLabel = confirmLabel ?? t('confirmDialog.confirm')
  const resolvedCancelLabel = cancelLabel ?? t('confirmDialog.cancel')

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{children}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description ? <AlertDialogDescription>{description}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{resolvedCancelLabel}</AlertDialogCancel>
          <AlertDialogPrimitive.Action
            type="button"
            disabled={confirmDisabled}
            onClick={() => detachPromise(onConfirm())}
            className={cn(buttonVariants({ variant: confirmVariant, size: "sm" }))}
          >
            {resolvedConfirmLabel}
          </AlertDialogPrimitive.Action>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
