'use client'

import { useTheme } from 'next-themes'
import { Toaster } from 'sonner'

export function SonnerToaster() {
  const { theme, systemTheme } = useTheme()
  const resolvedTheme = theme === 'system' ? systemTheme : theme
  const sonnerTheme = resolvedTheme === 'dark' ? 'dark' : 'light'

  return (
    <Toaster
      theme={sonnerTheme}
      position="top-right"
      richColors
      closeButton
    />
  )
}

