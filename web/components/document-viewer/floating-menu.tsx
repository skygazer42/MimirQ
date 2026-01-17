"use client"

import { useEffect, useState } from "react"
import { Sparkles, Languages, FileText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { globalEventBus } from "@/lib/event-bus"

export function FloatingMenu() {
  const [visible, setVisible] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const [selection, setSelection] = useState("")

  useEffect(() => {
    const handleMouseUp = () => {
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed) {
        setVisible(false)
        return
      }

      const text = sel.toString().trim()
      if (!text) {
        setVisible(false)
        return
      }

      const range = sel.getRangeAt(0)
      const rect = range.getBoundingClientRect()
      
      // Calculate relative to viewport, but we need to handle scroll offsets if inside iframe/div
      // For simplicity, we assume fixed positioning relative to viewport
      setPosition({
        top: rect.top - 50, // Above selection
        left: rect.left + rect.width / 2
      })
      setSelection(text)
      setVisible(true)
    }

    document.addEventListener("mouseup", handleMouseUp)
    return () => document.removeEventListener("mouseup", handleMouseUp)
  }, [])

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
    
    globalEventBus.emit("chat:send", prompt)
    setVisible(false)
    window.getSelection()?.removeAllRanges()
  }

  if (!visible) return null

  return (
    <div 
        className="fixed z-[60] flex gap-1 p-1 bg-slate-900/90 backdrop-blur-md rounded-lg shadow-xl border border-slate-700 animate-in fade-in zoom-in-95 duration-200"
        style={{ top: position.top, left: position.left, transform: "translateX(-50%)" }}
    >
      <Button variant="ghost" size="sm" className="h-8 text-xs text-white hover:bg-white/20" onClick={() => handleAction("explain")}>
        <Sparkles className="w-3 h-3 mr-1.5 text-sky-400" />
        解释
      </Button>
      <div className="w-px bg-white/20 my-1" />
      <Button variant="ghost" size="sm" className="h-8 text-xs text-white hover:bg-white/20" onClick={() => handleAction("translate")}>
        <Languages className="w-3 h-3 mr-1.5 text-emerald-400" />
        翻译
      </Button>
      <div className="w-px bg-white/20 my-1" />
      <Button variant="ghost" size="sm" className="h-8 text-xs text-white hover:bg-white/20" onClick={() => handleAction("summarize")}>
        <FileText className="w-3 h-3 mr-1.5 text-amber-400" />
        摘要
      </Button>
    </div>
  )
}
