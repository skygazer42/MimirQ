'use client'

import { useEffect } from 'react'

import { usePathname } from '@/i18n/navigation'

/**
 * The app locks window scrolling and uses an internal PageBody scroll container.
 * On route changes, reset that container to the top so new pages don't appear
 * "half scrolled".
 */
export function RouteScrollReset() {
  const pathname = usePathname()

  useEffect(() => {
    const frameId = globalThis.window.requestAnimationFrame(() => {
      const containers = document.querySelectorAll<HTMLElement>('[data-page-scroll-container="true"]')
      for (const container of containers) {
        container.scrollTo({ top: 0, left: 0, behavior: 'auto' })
      }
    })
    return () => globalThis.window.cancelAnimationFrame(frameId)
  }, [pathname])

  return null
}
