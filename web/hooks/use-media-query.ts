'use client'

import { useEffect, useState } from 'react'

/**
 * Subscribe to a CSS media query and return whether it currently matches.
 * Returns `false` during SSR so the initial server/client render is identical.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    const mql = globalThis.matchMedia(query)
    setMatches(mql.matches)

    const handler = (e: MediaQueryListEvent) => setMatches(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [query])

  return matches
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
