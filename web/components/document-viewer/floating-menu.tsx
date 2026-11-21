'use client'

import { useEffect, useRef, useState, type RefObject } from 'react'
import { Sparkles, Languages, FileText } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { useRouter } from '@/i18n/navigation'
import { globalEventBus } from '@/lib/event-bus'
import { useDocumentView } from '@/store/document-view'

const SELECTION_ACTIONS = { explain: '解释', translate: '翻译', summarize: '总结' } as const

type DocumentTextSelection = {
  text: string
  documentId: string
  chunkId: string | null
  x: number
  top: number
  bottom: number
}

export function FloatingMenu({ panelRef }: Readonly<{ panelRef: RefObject<HTMLDivElement | null> }>) {
  const router = useRouter()
  const documentId = useDocumentView((state) => state.documentId)
  const chunkId = useDocumentView((state) => state.highlightChunkId)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const [selectedText, setSelectedText] = useState<DocumentTextSelection | null>(null)
  const selection = selectedText?.documentId === documentId ? selectedText : null
  const menuRef = useRef<HTMLDivElement | null>(null)

  const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

  useEffect(() => {
    const handleMouseUp = (event: MouseEvent) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return
      const browserSelection = globalThis.window.getSelection()
      if (documentId === null || browserSelection === null || browserSelection.isCollapsed) {
        setSelectedText(null)
        return
      }

      const range = browserSelection.getRangeAt(0)
      const text = browserSelection.toString().trim()
      if (text === '' || !panelRef.current?.contains(range.commonAncestorContainer)) {
        setSelectedText(null)
        return
      }

      const rect = range.getBoundingClientRect()
      const x = rect.left + rect.width / 2
      setSelectedText({ text, documentId, chunkId, x, top: rect.top, bottom: rect.bottom })
      setPosition({ top: rect.top - 50, left: x })
    }

    document.addEventListener('mouseup', handleMouseUp)
    return () => document.removeEventListener('mouseup', handleMouseUp)
  }, [chunkId, documentId, panelRef])

  useEffect(() => {
    if (selection === null) return
    const raf = globalThis.window.requestAnimationFrame(() => {
      const el = menuRef.current
      if (!el) return

      const menuRect = el.getBoundingClientRect()
      const viewportW = globalThis.window.innerWidth
      const viewportH = globalThis.window.innerHeight

      // Keep a bit of breathing room from the edges (and let CSS safe-area padding handle notches).
      const padding = 10
      const halfW = menuRect.width / 2

      const left = clamp(selection.x, padding + halfW, viewportW - padding - halfW)

      // Prefer above selection; if it doesn't fit, place below.
      const gap = 10
      let top = selection.top - menuRect.height - gap
      if (top < padding) top = selection.bottom + gap
      top = clamp(top, padding, viewportH - padding - menuRect.height)

      setPosition((prev) => {
        if (Math.abs(prev.left - left) < 0.5 && Math.abs(prev.top - top) < 0.5) return prev
        return { top, left }
      })
    })

    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [selection])

  function handleAction(action: keyof typeof SELECTION_ACTIONS) {
    if (selection === null) return
    const prompt = `请${SELECTION_ACTIONS[action]}这段文字：\n> ${selection.text}`

    const handled = globalEventBus.emit('chat:submit', prompt)
    if (handled === 0) {
      const currentParams = new URLSearchParams(globalThis.window.location.search)
      const params = new URLSearchParams()
      const routeConversationId = currentParams.get('id')?.trim()
      const conversationId =
        routeConversationId === '' || routeConversationId === undefined
          ? currentParams.get('conversation')?.trim()
          : routeConversationId
      if (conversationId !== undefined && conversationId !== '') params.set('conversation', conversationId)
      params.set('doc', selection.documentId)
      if (selection.chunkId !== null) params.set('chunk', selection.chunkId)
      params.set('prompt', prompt)
      params.set('autorun', '1')
      router.push(`/?${params.toString()}`)
    }
    setSelectedText(null)
    globalThis.window.getSelection()?.removeAllRanges()
  }

  if (selection === null) return null

  return (
    <div
      ref={menuRef}
      className="fixed z-60 flex gap-1 p-1 bg-popover text-popover-foreground rounded-lg shadow-strong border border-border/40 animate-in fade-in zoom-in-95 duration-200 motion-reduce:animate-none"
      style={{
        top: `max(${position.top}px, calc(env(safe-area-inset-top) + 8px))`,
        left: position.left,
        transform: 'translateX(-50%)',
      }}
    >
      <Button
        variant="ghost"
        size="sm"
        className="h-8 text-xs text-foreground hover:bg-accent/40"
        onClick={() => handleAction('explain')}
      >
        <Sparkles className="size-3 mr-1.5 text-primary" />
        解释
      </Button>
      <div className="w-px bg-border/60 my-1" />
      <Button
        variant="ghost"
        size="sm"
        className="h-8 text-xs text-foreground hover:bg-accent/40"
        onClick={() => handleAction('translate')}
      >
        <Languages className="size-3 mr-1.5 text-info" />
        翻译
      </Button>
      <div className="w-px bg-border/60 my-1" />
      <Button
        variant="ghost"
        size="sm"
        className="h-8 text-xs text-foreground hover:bg-accent/40"
        onClick={() => handleAction('summarize')}
      >
        <FileText className="size-3 mr-1.5 text-warning" />
        摘要
      </Button>
    </div>
  )
}
