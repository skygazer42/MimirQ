"use client"

import * as React from "react"

import {
  applyStoredThemeAppearance,
  SURFACE_THEME_STORAGE_KEY,
  THEME_APPEARANCE_CHANGED_EVENT,
  THEME_COLOR_STORAGE_KEY,
} from "@/lib/theme-surface"

const useIsomorphicLayoutEffect =
  typeof window !== 'undefined' ? React.useLayoutEffect : React.useEffect

export function ThemeAppearanceProvider() {
  useIsomorphicLayoutEffect(() => {
    applyStoredThemeAppearance(window.localStorage, document.documentElement, window, { notify: false })
  }, [])

  React.useEffect(() => {
    const applyStoredAppearance = () => {
      applyStoredThemeAppearance(window.localStorage, document.documentElement, window, { notify: false })
    }

    const handleStorage = (event: StorageEvent) => {
      if (
        event.key &&
        event.key !== SURFACE_THEME_STORAGE_KEY &&
        event.key !== THEME_COLOR_STORAGE_KEY
      ) {
        return
      }
      applyStoredAppearance()
    }

    window.addEventListener('storage', handleStorage)
    window.addEventListener(THEME_APPEARANCE_CHANGED_EVENT, applyStoredAppearance)

    return () => {
      window.removeEventListener('storage', handleStorage)
      window.removeEventListener(THEME_APPEARANCE_CHANGED_EVENT, applyStoredAppearance)
    }
  }, [])

  return null
}
