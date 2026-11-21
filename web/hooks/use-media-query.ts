'use client'

import { useMemo, useSyncExternalStore } from 'react'

/**
 * Subscribe to a CSS media query and return whether it currently matches.
 * Returns `false` during SSR so the initial server/client render is identical.
 */
export function useMediaQuery(query: string): boolean {
  const { subscribe, getSnapshot } = useMemo(() => {
    const mediaQuery = globalThis.window?.matchMedia?.(query)
    return {
      subscribe(onStoreChange: () => void) {
        mediaQuery?.addEventListener('change', onStoreChange)
        return () => mediaQuery?.removeEventListener('change', onStoreChange)
      },
      getSnapshot() {
        return mediaQuery?.matches ?? false
      },
    }
  }, [query])

  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}

/** Viewport below Tailwind `md`. */
export function useIsMobile(): boolean {
  return useMediaQuery('(width < 48rem)')
}
