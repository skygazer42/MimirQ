"use client"

import { useEffect, useRef, useState } from "react"
import { Sparkles, Languages, FileText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { globalEventBus } from "@/lib/event-bus"

export function FloatingMenu() {
  const [visible, setVisible] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const [selection, setSelection] = useState("")
  const [anchor, setAnchor] = useState<{ x: number; top: number; bottom: number } | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

  useEffect(() => {
    const handleMouseUp = () => {
      const sel = globalThis.window.getSelection()
      if (!sel || sel.isCollapsed) {
        setVisible(false)
        setAnchor(null)
        return
      }

      const text = sel.toString().trim()
      if (!text) {
        setVisible(false)
        setAnchor(null)
        return
      }

      const range = sel.getRangeAt(0)
      const rect = range.getBoundingClientRect()
      
      // Calculate relative to viewport, but we need to handle scroll offsets if inside iframe/div
      // For simplicity, we assume fixed positioning relative to viewport
      const x = rect.left + rect.width / 2
      setAnchor({ x, top: rect.top, bottom: rect.bottom })
      setPosition({ top: rect.top - 50, left: x })
      setSelection(text)
      setVisible(true)
    }

    document.addEventListener("mouseup", handleMouseUp)
    return () => document.removeEventListener("mouseup", handleMouseUp)
  }, [])

  useEffect(() => {
    if (!visible || !anchor) return
    const raf = globalThis.window.requestAnimationFrame(() => {
      const el = menuRef.current
      if (!el) return

      const menuRect = el.getBoundingClientRect()
      const viewportW = globalThis.window.innerWidth
      const viewportH = globalThis.window.innerHeight

      // Keep a bit of breathing room from the edges (and let CSS safe-area padding handle notches).
      const padding = 10
      const halfW = menuRect.width / 2

      const left = clamp(anchor.x, padding + halfW, viewportW - padding - halfW)

      // Prefer above selection; if it doesn't fit, place below.
      const gap = 10
      let top = anchor.top - menuRect.height - gap
      if (top < padding) top = anchor.bottom + gap
      top = clamp(top, padding, viewportH - padding - menuRect.height)

      setPosition((prev) => {
        if (Math.abs(prev.left - left) < 0.5 && Math.abs(prev.top - top) < 0.5) return prev
        return { top, left }
      })
    })

    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [anchor, visible])

  const handleAction = (action: string) => {
    let prompt = ""
    switch (action) {
        case "explain":
            prompt = `请解释这段文字：\n> ${selection}`
            break
        case "translate":
            prompt = `请翻译这段文字：\n> ${selection}`
            break
        case "summarize":
            prompt = `请总结这段文字：\n> ${selection}`
            break
    }
    
    globalEventBus.emit("chat:submit", prompt)
    setVisible(false)
    globalThis.window.getSelection()?.removeAllRanges()
  }

  if (!visible) return null

  return (
    <div
        ref={menuRef}
        className="fixed z-60 flex gap-1 p-1 bg-popover text-popover-foreground rounded-lg shadow-strong border border-border/40 animate-in fade-in zoom-in-95 duration-200 motion-reduce:animate-none"
        style={{
          top: `max(${position.top}px, calc(env(safe-area-inset-top) + 8px))`,
          left: position.left,
          transform: "translateX(-50%)",
        }}
    >
      <Button variant="ghost" size="sm" className="h-8 text-xs text-foreground hover:bg-accent/40" onClick={() => handleAction("explain")}>
        <Sparkles className="size-3 mr-1.5 text-primary" />
        解释
      </Button>
      <div className="w-px bg-border/60 my-1" />
      <Button variant="ghost" size="sm" className="h-8 text-xs text-foreground hover:bg-accent/40" onClick={() => handleAction("translate")}>
        <Languages className="size-3 mr-1.5 text-info" />
        翻译
      </Button>
      <div className="w-px bg-border/60 my-1" />
      <Button variant="ghost" size="sm" className="h-8 text-xs text-foreground hover:bg-accent/40" onClick={() => handleAction("summarize")}>
        <FileText className="size-3 mr-1.5 text-warning" />
        摘要
      </Button>
    </div>
  )
}
