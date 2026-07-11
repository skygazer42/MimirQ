'use client'

import { useSyncExternalStore } from 'react'

function getMediaQuerySnapshot(query: string): boolean {
  if (
    typeof globalThis.window === 'undefined' ||
    typeof globalThis.window.matchMedia !== 'function'
  ) {
    return false
  }

  return globalThis.window.matchMedia(query).matches
}

function subscribeToMediaQuery(
  query: string,
  onStoreChange: () => void
): () => void {
  if (
    typeof globalThis.window === 'undefined' ||
    typeof globalThis.window.matchMedia !== 'function'
  ) {
    return () => {}
  }

  const mql = globalThis.window.matchMedia(query)
  const listener = () => onStoreChange()

  if (typeof mql.addEventListener === 'function') {
    mql.addEventListener('change', listener)
    return () => mql.removeEventListener('change', listener)
  }

  mql.addListener(listener)
  return () => mql.removeListener(listener)
}

/**
 * Subscribe to a CSS media query and return whether it currently matches.
 * Returns `false` during SSR so the initial server/client render is identical.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onStoreChange) => subscribeToMediaQuery(query, onStoreChange),
    () => getMediaQuerySnapshot(query),
    () => false
  )
}

/** Viewport narrower than Tailwind `md` (768px). */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 767.98px)')
}

/** Viewport between Tailwind `md` and `lg` (768–1023px). */
export function useIsTablet(): boolean {
  return useMediaQuery('(min-width: 768px) and (max-width: 1023.98px)')
}

/** Viewport at or above Tailwind `lg` (1024px). */
export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 1024px)')
}
