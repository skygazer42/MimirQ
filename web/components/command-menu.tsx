"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import {
  Upload,
  Moon,
  Sun,
  Laptop,
  MessageSquare,
  Database,
  Home,
  FileText,
  History,
  Settings,
} from "lucide-react"
import { useTheme } from "next-themes"

import type { Document } from "@/types"
import { documentApi } from "@/lib/api"
import { globalEventBus } from "@/lib/event-bus"
import { useDocumentView } from "@/store/document-view"

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command"

export function CommandMenu() {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState("")
  const [docResults, setDocResults] = React.useState<Document[]>([])
  const [docLoading, setDocLoading] = React.useState(false)
  const requestSeqRef = React.useRef(0)
  const router = useRouter()
  const { setTheme } = useTheme()
  const { openDocument } = useDocumentView()

  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((open) => !open)
      }
    }

    document.addEventListener("keydown", down)
    return () => document.removeEventListener("keydown", down)
  }, [])

  React.useEffect(() => {
    const offSetOpen = globalEventBus.on("command-menu:set-open", (payload) => {
      if (typeof payload?.open === "boolean") {
        setOpen(payload.open)
      }
    })
    const offToggle = globalEventBus.on("command-menu:toggle", () => {
      setOpen((current) => !current)
    })

    return () => {
      offSetOpen()
      offToggle()
    }
  }, [])

  // Server-backed document search for large knowledge bases.
  React.useEffect(() => {
    if (!open) {
      setQuery("")
      setDocResults([])
      setDocLoading(false)
      requestSeqRef.current += 1
      return
    }

    const q = query.trim()
    if (q.length < 2) {
      setDocResults([])
      setDocLoading(false)
      requestSeqRef.current += 1
      return
    }

    const seq = ++requestSeqRef.current
    setDocLoading(true)
    const t = globalThis.window.setTimeout(() => {
      documentApi
        .list({ q, limit: 8, order_by: "created_at", order_dir: "desc" })
        .then((res) => {
          if (seq !== requestSeqRef.current) return
          setDocResults(res.items || [])
        })
        .catch(() => {
          if (seq !== requestSeqRef.current) return
          setDocResults([])
        })
        .finally(() => {
          if (seq !== requestSeqRef.current) return
          setDocLoading(false)
        })
    }, 220)

    return () => globalThis.window.clearTimeout(t)
  }, [open, query])

  const runCommand = React.useCallback((command: () => unknown) => {
    setOpen(false)
    command()
  }, [])

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="输入命令或搜索..." value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>未找到相关结果</CommandEmpty>
        
        <CommandGroup heading="导航">
          <CommandItem onSelect={() => runCommand(() => router.push('/'))}>
            <Home className="mr-2 h-4 w-4" />
            <span>对话</span>
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push('/'))}>
            <MessageSquare className="mr-2 h-4 w-4" />
            <span>新对话</span>
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push('/knowledge'))}>
            <Database className="mr-2 h-4 w-4" />
            <span>知识库</span>
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push('/parsing'))}>
            <FileText className="mr-2 h-4 w-4" />
            <span>文档解析</span>
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push('/history'))}>
            <History className="mr-2 h-4 w-4" />
            <span>问答历史</span>
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push('/settings'))}>
            <Settings className="mr-2 h-4 w-4" />
            <span>设置</span>
          </CommandItem>
        </CommandGroup>
        
        <CommandSeparator />

        {query.trim().length >= 2 ? (
          <>
            <CommandGroup heading="文档">
              {(() => {
    if (docLoading) {
        return (<CommandItem disabled value="doc:loading">
                  <FileText className="mr-2 h-4 w-4"/>
                  <span>搜索中…</span>
                </CommandItem>);
    }
    else if (docResults.length) {
            return (docResults.map((doc) => (<CommandItem key={doc.id} value={doc.filename} onSelect={() => runCommand(() => {
                    openDocument(doc.id);
                    router.push("/");
                })}>
                    <FileText className="mr-2 h-4 w-4"/>
                    <span className="truncate">{doc.filename}</span>
                  </CommandItem>)));
        }
        else {
            return (<CommandItem disabled value="doc:empty">
                  <FileText className="mr-2 h-4 w-4"/>
                  <span>未找到文档</span>
                </CommandItem>);
        }
})()}
            </CommandGroup>

            <CommandSeparator />
          </>
        ) : null}

        <CommandGroup heading="操作">
           <CommandItem onSelect={() => runCommand(() => router.push('/knowledge'))}>
            <Upload className="mr-2 h-4 w-4" />
            <span>上传文档</span>
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => router.push('/?rag=1'))}>
            <Settings className="mr-2 h-4 w-4" />
            <span>RAG 设置</span>
          </CommandItem>
        </CommandGroup>
        
        <CommandSeparator />
        
        <CommandGroup heading="主题">
          <CommandItem onSelect={() => runCommand(() => setTheme("light"))}>
            <Sun className="mr-2 h-4 w-4" />
            <span>浅色模式</span>
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => setTheme("dark"))}>
            <Moon className="mr-2 h-4 w-4" />
            <span>深色模式</span>
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => setTheme("system"))}>
            <Laptop className="mr-2 h-4 w-4" />
            <span>跟随系统</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}
