'use client'

import { useTheme } from 'next-themes'
import { Toaster } from 'sonner'
import { AlertCircle, CheckCircle2, Info, Loader2 } from '@/components/icons'
import { FEEDBACK_DURATION } from '@/components/feedback-toast'

export function SonnerToaster() {
  const { resolvedTheme } = useTheme()

  // Toast actions must not trigger a dialog's outside-press dismissal.
  return (
    <div onPointerDownCapture={(event) => event.stopPropagation()}>
      <style>{`
        @media (max-width: 640px) {
          body:has([data-sonner-toast][data-visible='true']) {
            --feedback-safe-height: calc(max(8px, env(safe-area-inset-top)) + 64px);
          }
          body:has([data-sonner-toast][data-visible='true']) #main-content {
            padding-top: var(--feedback-safe-height);
          }
          body:has([data-sonner-toast][data-visible='true']) #mimirq-sidebar {
            top: var(--feedback-safe-height);
          }
          body:has([data-sonner-toast][data-visible='true']) [aria-controls='mimirq-sidebar'][aria-expanded='false'] {
            top: calc(var(--feedback-safe-height) + 1rem);
          }
          body:has([data-sonner-toast][data-visible='true']) [role='dialog'][data-state='open'] {
            top: calc(50% + var(--feedback-safe-height) / 2);
            max-height: calc(100dvh - var(--feedback-safe-height) - 32px);
          }
        }
      `}</style>
      <Toaster
        theme={resolvedTheme === 'dark' ? 'dark' : 'light'}
        position="top-center"
        offset={{ top: 'max(12px, env(safe-area-inset-top))' }}
        mobileOffset={{
          top: 'max(8px, env(safe-area-inset-top))',
          right: 16,
          left: 16,
        }}
        duration={FEEDBACK_DURATION}
        visibleToasts={1}
        icons={{
          success: <CheckCircle2 className="size-4 text-success" />,
          error: <AlertCircle className="size-4 text-destructive" />,
          warning: <AlertCircle className="size-4 text-warning" />,
          info: <Info className="size-4 text-info" />,
          loading: <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />,
        }}
        closeButton
        gap={6}
        style={{ pointerEvents: 'none' }}
        toastOptions={{
          className: 'app-feedback-toast',
          classNames: {
            content: 'min-w-0 max-h-10 overflow-y-auto pointer-events-auto',
            closeButton: 'pointer-events-auto',
            actionButton: 'pointer-events-auto',
            cancelButton: 'pointer-events-auto',
          },
          style: {
            pointerEvents: 'none',
            background: 'hsl(var(--popover))',
            color: 'hsl(var(--popover-foreground))',
            border: '1px solid hsl(var(--border))',
            borderRadius: '8px',
            boxShadow: '0 8px 28px hsl(var(--foreground) / 0.12)',
            fontFamily: 'var(--font-sans)',
            fontSize: '13px',
            fontWeight: 450,
            lineHeight: '21px',
            padding: '8px 14px',
            gap: '8px',
          },
        }}
      />
    </div>
  )
}
