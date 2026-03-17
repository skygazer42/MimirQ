"use client"

import * as React from "react"

import { Navbar } from "@/components/navbar"
import { cn } from "@/lib/utils"
import { useDocumentView } from "@/store/document-view"

type AppFrameProps = {
  children: React.ReactNode
  className?: string
  mainClassName?: string
  rightPanel?: React.ReactNode
  showBackground?: boolean
  showNavbar?: boolean
  withDocumentViewerPadding?: boolean
}

export function AppFrame({
  children,
  className,
  mainClassName,
  rightPanel,
  showBackground: _showBackground = true,
  showNavbar = true,
  withDocumentViewerPadding = false,
}: Readonly<AppFrameProps>) {
  const [isSidebarOpen, setSidebarOpen] = React.useState(true)
  const skipLinkRef = React.useRef<HTMLAnchorElement | null>(null)
  const appContentRef = React.useRef<HTMLDivElement | null>(null)
  const { isOpen: isDocPanelOpen } = useDocumentView()
  const docPanelPadding =
    withDocumentViewerPadding && isDocPanelOpen
      ? "mr-0 md:mr-[40vw] xl:mr-[40vw] lg:mr-[500px]"
      : undefined

  React.useEffect(() => {
    if (!showNavbar) return
    if (globalThis.window === undefined) return

    let isMobile = false
    try {
      isMobile = globalThis.window.matchMedia("(max-width: 768px)").matches
    } catch {
      isMobile = false
    }

    const shouldInert = Boolean(isMobile && isSidebarOpen)

    const applyInert = (el: HTMLElement | null, inert: boolean) => {
      if (!el) return
      try {
        ;(el as any).inert = inert
      } catch {
        // ignore
      }
      if (inert) el.setAttribute("aria-hidden", "true")
      else el.removeAttribute("aria-hidden")
    }

    const skipEl = skipLinkRef.current
    const contentEl = appContentRef.current

    applyInert(skipEl, shouldInert)
    applyInert(contentEl, shouldInert)

    return () => {
      applyInert(skipEl, false)
      applyInert(contentEl, false)
    }
  }, [isSidebarOpen, showNavbar])

  return (
    <div className={cn("relative h-dvh overflow-hidden bg-background text-foreground", className)}>
      <a
        ref={skipLinkRef}
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-60 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-foreground focus:shadow-strong focus:outline-none focus:ring-2 focus:ring-ring/40"
      >
        跳到主要内容
      </a>
      <div className="relative flex h-full overflow-hidden">
        {showNavbar && <Navbar isSidebarOpen={isSidebarOpen} setSidebarOpen={setSidebarOpen} />}
        <div ref={appContentRef} className="flex-1 min-h-0 relative flex overflow-hidden">
          <main
            id="main-content"
            tabIndex={-1}
            className={cn(
              "flex-1 min-h-0 relative flex flex-col overflow-hidden",
              docPanelPadding,
              mainClassName
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
