'use client'

import { useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'

import { Navbar } from '@/components/navbar'
import { AppBackground } from '@/components/ui/app-background'
import { useIsMobile } from '@/hooks/use-media-query'
import { cn } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'

type AppFrameProps = {
  children: ReactNode
  className?: string
  mainClassName?: string
  rightPanel?: ReactNode
  showBackground?: boolean
  showNavbar?: boolean
  withDocumentViewerPadding?: boolean
  navigationVariant?: 'default' | 'rail'
}

export function AppFrame({
  children,
  className,
  mainClassName,
  rightPanel,
  showBackground = true,
  showNavbar = true,
  withDocumentViewerPadding = false,
  navigationVariant = 'default',
}: Readonly<AppFrameProps>) {
  const t = useTranslations('Layout')
  const isMobile = useIsMobile()
  const [sidebarOpenOverride, setSidebarOpen] = useState<boolean>()
  const sidebarExpanded = showNavbar && navigationVariant === 'default' && (sidebarOpenOverride ?? !isMobile)
  const isSidebarOverlayOpen = isMobile && sidebarExpanded
  const isDocPanelOpen = useDocumentView((state) => state.isOpen)
  const docPanelPadding =
    withDocumentViewerPadding && isDocPanelOpen ? 'mr-0 md:mr-[45vw] lg:mr-[40vw] xl:mr-[35vw]' : undefined

  return (
    <div className={cn('relative h-dvh overflow-hidden bg-background text-foreground', className)}>
      <a
        inert={isSidebarOverlayOpen}
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-60 focus:rounded-lg focus:bg-background focus:px-3 focus:py-2 focus:text-foreground focus:shadow-strong focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
      >
        {t('skipToMainContent')}
      </a>
      {showBackground && <AppBackground />}
      <div className="relative z-10 flex h-full overflow-hidden">
        {showNavbar && (
          <Navbar variant={navigationVariant} isSidebarOpen={sidebarExpanded} setSidebarOpen={setSidebarOpen} />
        )}
        <div inert={isSidebarOverlayOpen} className="flex-1 min-h-0 relative flex overflow-hidden">
          <main
            id="main-content"
            tabIndex={-1}
            className={cn(
              // Avoid animating layout properties like `margin` (baseline-ui).
              'flex-1 min-h-0 relative flex flex-col overflow-hidden',
              docPanelPadding,
              mainClassName,
            )}
          >
            {children}
          </main>
          {rightPanel}
        </div>
      </div>
    </div>
  )
}
