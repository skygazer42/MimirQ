"use client"

import * as React from "react"
import { usePathname, useRouter } from "next/navigation"
import {
  Upload,
  Activity,
  Coins,
  Moon,
  Sun,
  Laptop,
  MessageSquare,
  Database,
  Home,
  FileText,
  History,
  Settings,
  Sparkles,
  Workflow,
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
  CommandShortcut,
  CommandSeparator,
} from "@/components/ui/command"

type SlashCommand = {
  id: string
  label: string
  description: string
  shortcut: string
  keywords: string[]
  icon: React.ComponentType<{ className?: string }>
  run: () => void
}

function buildCurrentViewPrompt(pathname: string): { prompt: string; description: string } {
  if (pathname.startsWith("/graph")) {
    return {
      prompt: "请基于当前图谱视图，总结关键实体、关系模式、异常断点，并给出最值得继续下钻的节点。",
      description: "把当前图谱视图送入对话区，自动生成下钻建议。",
    }
  }

  if (pathname.startsWith("/knowledge")) {
    return {
      prompt: "请基于当前知识库工作台，总结文档状态、导入风险和最值得优先处理的事项。",
      description: "把当前知识库上下文转成一条可直接发起的分析问题。",
    }
  }

  if (pathname.startsWith("/datasets")) {
    return {
      prompt: "请基于当前数据集页面，总结关键质量信号、风险项，以及建议的下一步治理动作。",
      description: "针对当前数据集页面生成一条诊断型提问。",
    }
  }

  if (pathname.startsWith("/settings")) {
    return {
      prompt: "请基于当前系统设置页面，指出高风险配置、建议保守值和需要复核的项。",
      description: "针对当前设置视图生成一条配置审查提问。",
    }
  }

  if (pathname.startsWith("/observability") || pathname.startsWith("/reports")) {
    return {
      prompt: "请基于当前可观测/报表页面，总结异常指标、可能根因和建议的排查顺序。",
      description: "把当前监控视图转成可直接追问的调查提示。",
    }
  }

  return {
    prompt: "请分析我当前所在页面的重点信息、潜在风险，以及建议的下一步操作。",
    description: "将当前视图整理成一条可直接发送的分析问题。",
  }
}

export function CommandMenu() {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState("")
  const [docResults, setDocResults] = React.useState<Document[]>([])
  const [docLoading, setDocLoading] = React.useState(false)
  const requestSeqRef = React.useRef(0)
  const router = useRouter()
  const pathname = usePathname()
  const { setTheme } = useTheme()
  const { openDocument } = useDocumentView()
  const currentViewPrompt = React.useMemo(() => buildCurrentViewPrompt(pathname || "/"), [pathname])
  const isSlashMode = query.trim().startsWith("/")
  const slashNeedle = query.trim().slice(1).toLowerCase()

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
    if (q.length < 2 || q.startsWith("/")) {
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

  const slashCommands = React.useMemo<SlashCommand[]>(
    () => [
      {
        id: "upload",
        label: "上传文档",
        description: "直达知识库工作台，继续上传、整理和查看导入状态。",
        shortcut: "/upload",
        keywords: ["upload", "文档", "知识库", "导入"],
        icon: Upload,
        run: () => router.push("/knowledge"),
      },
      {
        id: "analyze-current-view",
        label: "分析当前视图",
        description: currentViewPrompt.description,
        shortcut: "/analyze",
        keywords: ["analyze", "分析", "当前视图", "总结", "诊断"],
        icon: Sparkles,
        run: () => {
          const params = new URLSearchParams({
            prompt: currentViewPrompt.prompt,
            autorun: "1",
          })
          router.push(`/?${params.toString()}`)
        },
      },
      {
        id: "stats",
        label: "查看统计与诊断",
        description: "打开用量/配额视图，快速查看 tokens、成本和系统诊断入口。",
        shortcut: "/stats",
        keywords: ["stats", "usage", "diagnostics", "quota", "token", "cost", "统计", "诊断", "用量"],
        icon: Coins,
        run: () => router.push("/usage"),
      },
      {
        id: "datasets",
        label: "打开数据集",
        description: "跳到数据集列表，查看质量信号与治理入口。",
        shortcut: "/datasets",
        keywords: ["datasets", "数据集", "质量", "治理"],
        icon: Database,
        run: () => router.push("/datasets"),
      },
      {
        id: "history",
        label: "打开问答历史",
        description: "查看最近问答记录，便于复盘与复用。",
        shortcut: "/history",
        keywords: ["history", "qa", "对话历史", "复盘"],
        icon: History,
        run: () => router.push("/history"),
      },
      {
        id: "graph",
        label: "打开图谱工作台",
        description: "跳到图谱视图，查看实体关系和路径分析。",
        shortcut: "/graph",
        keywords: ["graph", "图谱", "关系", "实体"],
        icon: Workflow,
        run: () => router.push("/graph"),
      },
      {
        id: "diagnostics",
        label: "打开运行诊断",
        description: "进入系统诊断页，查看健康状态、依赖和前端运行信息。",
        shortcut: "/diagnostics",
        keywords: ["diagnostics", "health", "observability", "诊断", "健康检查"],
        icon: Activity,
        run: () => router.push("/diagnostics"),
      },
      {
        id: "settings",
        label: "打开系统设置",
        description: "快速进入模型、RAG 和治理配置。",
        shortcut: "/settings",
        keywords: ["settings", "设置", "rag", "配置"],
        icon: Settings,
        run: () => router.push("/settings"),
      },
    ],
    [currentViewPrompt.description, currentViewPrompt.prompt, router]
  )

  const filteredSlashCommands = React.useMemo(
    () =>
      slashCommands.filter((command) => {
        if (!slashNeedle) return true
        const haystack = [command.shortcut, command.label, command.description, ...command.keywords]
          .join(" ")
          .toLowerCase()
        return haystack.includes(slashNeedle)
      }),
    [slashCommands, slashNeedle]
  )

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <div className="flex items-center justify-between border-b border-border/50 bg-muted/50 px-3 py-2 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground/80">Command Center</span>
        <span>输入 <span className="font-semibold text-foreground">/</span> 查看快捷动作</span>
      </div>
      <CommandInput placeholder="输入命令或搜索..." value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>未找到相关结果</CommandEmpty>

        {isSlashMode ? (
          <>
            <CommandGroup heading="快捷指令">
              {filteredSlashCommands.map((command) => {
                const Icon = command.icon
                return (
                  <CommandItem
                    key={command.id}
                    value={`${command.shortcut} ${command.label} ${command.keywords.join(" ")}`}
                    className="gap-3 rounded-xl px-3 py-3"
                    onSelect={() => runCommand(command.run)}
                  >
                    <div className="flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-foreground">{command.label}</div>
                      <div className="truncate text-xs text-muted-foreground">{command.description}</div>
                    </div>
                    <CommandShortcut>{command.shortcut}</CommandShortcut>
                  </CommandItem>
                )
              })}
            </CommandGroup>
            <CommandSeparator />
          </>
        ) : null}

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

        {query.trim().length >= 2 && !isSlashMode ? (
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
