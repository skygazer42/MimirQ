"use client"

import * as React from "react"

import {
  applyStoredThemeAppearance,
  SURFACE_THEME_STORAGE_KEY,
  THEME_APPEARANCE_CHANGED_EVENT,
  THEME_COLOR_STORAGE_KEY,
} from "@/lib/theme-surface"

const useIsomorphicLayoutEffect =
  globalThis.window === undefined ? React.useEffect : React.useLayoutEffect

export function ThemeAppearanceProvider() {
  useIsomorphicLayoutEffect(() => {
    applyStoredThemeAppearance(globalThis.window.localStorage, globalThis.document.documentElement, globalThis.window, { notify: false })
  }, [])

  React.useEffect(() => {
    const applyStoredAppearance = () => {
      applyStoredThemeAppearance(globalThis.window.localStorage, globalThis.document.documentElement, globalThis.window, { notify: false })
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

    globalThis.window.addEventListener('storage', handleStorage)
    globalThis.window.addEventListener(THEME_APPEARANCE_CHANGED_EVENT, applyStoredAppearance)

    return () => {
      globalThis.window.removeEventListener('storage', handleStorage)
      globalThis.window.removeEventListener(THEME_APPEARANCE_CHANGED_EVENT, applyStoredAppearance)
    }
  }, [])

  return null
}
