"use client"

import * as React from "react"

import { Navbar } from "@/components/navbar"
import { AppBackground } from "@/components/ui/app-background"
import { cn } from "@/lib/utils"
import { useDocumentView } from "@/store/document-view"

type AppFrameProps = {
  children: React.ReactNode
  className?: string
  mainClassName?: string
  rightPanel?: React.ReactNode
  showBackground?: boolean
  withDocumentViewerPadding?: boolean
}

export function AppFrame({
  children,
  className,
  mainClassName,
  rightPanel,
  showBackground = true,
  withDocumentViewerPadding = false,
}: AppFrameProps) {
  const { isOpen: isDocPanelOpen } = useDocumentView()
  const docPanelPadding =
    withDocumentViewerPadding && isDocPanelOpen
      ? "mr-0 md:mr-[40vw] xl:mr-[40vw] lg:mr-[500px]"
      : undefined

  return (
    <div className={cn("relative min-h-screen bg-background text-foreground", className)}>
      {showBackground && <AppBackground />}
      <div className="relative z-10 flex min-h-screen overflow-hidden">
        <Navbar />
        <main
          id="main-content"
          tabIndex={-1}
          className={cn(
            "flex-1 min-h-0 relative flex flex-col overflow-hidden transition-[margin] duration-300 ease-in-out",
            docPanelPadding,
            mainClassName
          )}
        >
          {children}
        </main>
        {rightPanel}
      </div>
    </div>
  )
}
