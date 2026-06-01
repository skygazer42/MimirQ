'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

type ParsingLeftPanelProps = {
  collapsed: boolean
  onToggleCollapsed: () => void
  children: React.ReactNode
  className?: string
}

const PARSING_LEFT_PANEL_WIDTH_KEY = 'mimirq.parsing.leftPanelWidth'
const DEFAULT_PARSING_LEFT_PANEL_WIDTH = 344
const MIN_PARSING_LEFT_PANEL_WIDTH = 280
const MAX_PARSING_LEFT_PANEL_WIDTH = 460

function clampParsingLeftPanelWidth(width: number) {
  return Math.min(
    MAX_PARSING_LEFT_PANEL_WIDTH,
    Math.max(MIN_PARSING_LEFT_PANEL_WIDTH, Math.round(width))
  )
}

function readStoredParsingLeftPanelWidth() {
  if (globalThis.window === undefined) {
    return DEFAULT_PARSING_LEFT_PANEL_WIDTH
  }

  const storedWidth = Number.parseInt(
    readClientStorage(PARSING_LEFT_PANEL_WIDTH_KEY) || '',
    10
  )
  return Number.isFinite(storedWidth)
    ? clampParsingLeftPanelWidth(storedWidth)
    : DEFAULT_PARSING_LEFT_PANEL_WIDTH
}

export function ParsingLeftPanel({
  collapsed,
  onToggleCollapsed,
  children,
  className,
}: Readonly<ParsingLeftPanelProps>) {
  const t = useTranslations('ParsingWorkbench')
  const [sidebarWidth, setSidebarWidth] = useState(
    DEFAULT_PARSING_LEFT_PANEL_WIDTH
  )
  const resizeStateRef = useRef<{
    currentWidth: number
    startWidth: number
    startX: number
  } | null>(null)

  useEffect(() => {
    setSidebarWidth(readStoredParsingLeftPanelWidth())
  }, [])

  const persistSidebarWidth = useCallback((width: number) => {
    if (globalThis.window === undefined) {
      return
    }

    writeClientStorage(
      PARSING_LEFT_PANEL_WIDTH_KEY,
      String(clampParsingLeftPanelWidth(width))
    )
  }, [])

  const handleResizePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (collapsed) {
        return
      }

      event.preventDefault()
      resizeStateRef.current = {
        currentWidth: sidebarWidth,
        startWidth: sidebarWidth,
        startX: event.clientX,
      }

      const previousCursor = document.body.style.cursor
      const previousUserSelect = document.body.style.userSelect
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'

      const controller = new AbortController()
      const restorePageInteraction = () => {
        document.body.style.cursor = previousCursor
        document.body.style.userSelect = previousUserSelect
        controller.abort()
      }

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const resizeState = resizeStateRef.current
        if (!resizeState) {
          return
        }

        const nextWidth = clampParsingLeftPanelWidth(
          resizeState.startWidth + moveEvent.clientX - resizeState.startX
        )
        resizeState.currentWidth = nextWidth
        setSidebarWidth(nextWidth)
      }

      const handlePointerUp = () => {
        const nextWidth =
          resizeStateRef.current?.currentWidth ?? sidebarWidth
        resizeStateRef.current = null
        persistSidebarWidth(nextWidth)
        restorePageInteraction()
      }

      globalThis.window.addEventListener('pointermove', handlePointerMove, {
        signal: controller.signal,
      })
      globalThis.window.addEventListener('pointerup', handlePointerUp, {
        once: true,
        signal: controller.signal,
      })
      globalThis.window.addEventListener('pointercancel', handlePointerUp, {
        once: true,
        signal: controller.signal,
      })
    },
    [collapsed, persistSidebarWidth, sidebarWidth]
  )

  const handleResizeKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (collapsed) {
        return
      }

      const step = event.shiftKey ? 32 : 16
      const nextWidthByKey: Record<string, number | undefined> = {
        ArrowLeft: sidebarWidth - step,
        ArrowRight: sidebarWidth + step,
        End: MAX_PARSING_LEFT_PANEL_WIDTH,
        Home: MIN_PARSING_LEFT_PANEL_WIDTH,
      }
      const nextWidth = nextWidthByKey[event.key]
      if (typeof nextWidth !== 'number') {
        return
      }

      event.preventDefault()
      const clampedWidth = clampParsingLeftPanelWidth(nextWidth)
      setSidebarWidth(clampedWidth)
      persistSidebarWidth(clampedWidth)
    },
    [collapsed, persistSidebarWidth, sidebarWidth]
  )

  return (
    <aside
      className={cn(
        'group/sidebar relative z-10 flex min-h-0 flex-shrink-0 flex-col overflow-visible rounded-[24px] border border-border/70 bg-card/96 shadow-[0_24px_60px_-46px_rgba(15,23,42,0.42)] backdrop-blur-sm dark:bg-card/95',
        collapsed ? 'w-0 border-0 shadow-none' : '',
        className
      )}
      style={collapsed ? { width: 0 } : { width: sidebarWidth }}
    >
      <Button
        variant="ghost"
        size="icon"
        className={cn(
          'absolute top-2 z-30 h-6 w-6 rounded-lg border border-border/60 bg-card text-muted-foreground shadow-none backdrop-blur-sm transition-[opacity,background-color,color,box-shadow] duration-200 hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-info/35 motion-reduce:transition-none',
          'opacity-0 hover:opacity-100 focus-visible:opacity-100',
          collapsed ? 'right-[-2.25rem]' : 'right-2'
        )}
        onClick={onToggleCollapsed}
        title={
          collapsed
            ? t('leftPanel.expandSidebar')
            : t('leftPanel.collapseSidebar')
        }
        aria-label={
          collapsed
            ? t('leftPanel.expandSidebar')
            : t('leftPanel.collapseSidebar')
        }
      >
        {collapsed ? (
          <PanelRightOpen className="w-3 h-3" />
        ) : (
          <PanelRightClose className="w-3 h-3" />
        )}
      </Button>

      <div
        role="separator"
        aria-label="调整文档列表宽度"
        aria-orientation="vertical"
        aria-valuemax={MAX_PARSING_LEFT_PANEL_WIDTH}
        aria-valuemin={MIN_PARSING_LEFT_PANEL_WIDTH}
        aria-valuenow={sidebarWidth}
        className={cn(
          'absolute inset-y-4 right-[-6px] z-20 w-3 cursor-col-resize rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/35',
          'before:absolute before:inset-y-8 before:left-1/2 before:w-px before:-translate-x-1/2 before:rounded-full before:bg-border/65 before:transition-colors hover:before:bg-info/70 focus-visible:before:bg-info',
          collapsed && 'hidden'
        )}
        onKeyDown={handleResizeKeyDown}
        onPointerDown={handleResizePointerDown}
        tabIndex={collapsed ? -1 : 0}
      />

      <div
        className={cn(
          'flex min-h-0 w-full flex-1 flex-col overflow-hidden',
          collapsed && 'invisible'
        )}
      >
        {children}
      </div>
    </aside>
  )
}
