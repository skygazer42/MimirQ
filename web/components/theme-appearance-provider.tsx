'use client'

import { useLayoutEffect } from 'react'

import { getClientStorage } from '@/lib/client-storage'
import { applyStoredThemeAppearance, SURFACE_THEME_STORAGE_KEY, THEME_COLOR_STORAGE_KEY } from '@/lib/theme-surface'

export function ThemeAppearanceProvider() {
  useLayoutEffect(() => {
    const storage = getClientStorage()
    if (storage === null) return

    const root = document.documentElement
    applyStoredThemeAppearance(storage, root, window, { notify: false })

    const handleStorage = (event: StorageEvent) => {
      if (event.storageArea !== storage) return
      if (event.key !== null && event.key !== SURFACE_THEME_STORAGE_KEY && event.key !== THEME_COLOR_STORAGE_KEY) return
      applyStoredThemeAppearance(storage, root)
    }

    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  return null
}
