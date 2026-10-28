'use client'

import { useTheme } from 'next-themes'
import { Toaster } from 'sonner'
import { AlertCircle, CheckCircle2, Info, Loader2 } from '@/components/icons'
import { FEEDBACK_DURATION } from '@/components/feedback-toast'

export function SonnerToaster() {
  const { theme, systemTheme } = useTheme()
  const resolvedTheme = theme === 'system' ? systemTheme : theme
  const sonnerTheme = resolvedTheme === 'dark' ? 'dark' : 'light'

  return (
    <Toaster
      theme={sonnerTheme}
      position="top-center"
      offset={16}
      mobileOffset={{ top: 72, right: 16, left: 16 }}
      duration={FEEDBACK_DURATION}
      visibleToasts={3}
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
          padding: '11px 14px',
          gap: '8px',
        },
      }}
    />
  )
}
