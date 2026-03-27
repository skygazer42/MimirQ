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

import type { Conversation, Dataset, Document } from "@/types"
import { chatApi, datasetApi, documentApi } from "@/lib/api"
import { globalEventBus } from "@/lib/event-bus"
import { useCommandMenuState } from "@/store/command-menu"
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

type KeyChordCommand = {
  key: string
  label: string
  description: string
  run: () => void
}

const KEY_CHORD_TIMEOUT_MS = 1600

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tagName = target.tagName
  return target.isContentEditable || tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT'
}

function normalizeChordKey(key: string): string {
  return String(key || '').trim().toLowerCase()
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

function matchesSearchNeedle(values: Array<string | null | undefined>, needle: string): boolean {
  const normalizedNeedle = String(needle || '').trim().toLowerCase()
  if (!normalizedNeedle) return true

  return values.some((value) => String(value || '').toLowerCase().includes(normalizedNeedle))
}

export function CommandMenu() {
  const [query, setQuery] = React.useState("")
  const [docResults, setDocResults] = React.useState<Document[]>([])
  const [datasetResults, setDatasetResults] = React.useState<Dataset[]>([])
  const [conversationResults, setConversationResults] = React.useState<Conversation[]>([])
  const [docLoading, setDocLoading] = React.useState(false)
  const [datasetLoading, setDatasetLoading] = React.useState(false)
  const [conversationLoading, setConversationLoading] = React.useState(false)
  const [pendingChordPrefix, setPendingChordPrefix] = React.useState<string | null>(null)
  const requestSeqRef = React.useRef(0)
  const chordTimerRef = React.useRef<number | null>(null)
  const router = useRouter()
  const pathname = usePathname()
  const { setTheme } = useTheme()
  const open = useCommandMenuState((state) => state.open)
  const setOpen = useCommandMenuState((state) => state.setOpen)
  const toggleOpen = useCommandMenuState((state) => state.toggle)
  const { openDocument } = useDocumentView()
  const currentViewPrompt = React.useMemo(() => buildCurrentViewPrompt(pathname || "/"), [pathname])
  const isSlashMode = query.trim().startsWith("/")
  const slashNeedle = query.trim().slice(1).toLowerCase()

  const clearPendingChord = React.useCallback(() => {
    setPendingChordPrefix(null)
    if (chordTimerRef.current != null) {
      globalThis.window.clearTimeout(chordTimerRef.current)
      chordTimerRef.current = null
    }
  }, [])

  const armPendingChord = React.useCallback(
    (prefix: string) => {
      setPendingChordPrefix(prefix)
      if (chordTimerRef.current != null) {
        globalThis.window.clearTimeout(chordTimerRef.current)
      }
      chordTimerRef.current = globalThis.window.setTimeout(() => {
        setPendingChordPrefix(null)
        chordTimerRef.current = null
      }, KEY_CHORD_TIMEOUT_MS)
    },
    []
  )

  React.useEffect(() => {
    const offSetOpen = globalEventBus.on("command-menu:set-open", (payload) => {
      if (typeof payload?.open === "boolean") {
        setOpen(payload.open)
      }
    })
    const offToggle = globalEventBus.on("command-menu:toggle", () => {
      toggleOpen()
    })

    return () => {
      offSetOpen()
      offToggle()
    }
  }, [setOpen, toggleOpen])

  // Server-backed document search for large knowledge bases.
  React.useEffect(() => {
    if (!open) {
      setQuery("")
      setDocResults([])
      setDatasetResults([])
      setConversationResults([])
      setDocLoading(false)
      setDatasetLoading(false)
      setConversationLoading(false)
      requestSeqRef.current += 1
      return
    }

    const q = query.trim()
    if (q.length < 2 || q.startsWith("/")) {
      setDocResults([])
      setDatasetResults([])
      setConversationResults([])
      setDocLoading(false)
      setDatasetLoading(false)
      setConversationLoading(false)
      requestSeqRef.current += 1
      return
    }

    const seq = ++requestSeqRef.current
    setDocLoading(true)
    setDatasetLoading(true)
    setConversationLoading(true)
    const t = globalThis.window.setTimeout(() => {
      const needle = q.toLowerCase()

      Promise.allSettled([
        documentApi.list({ q, limit: 8, order_by: "created_at", order_dir: "desc" }),
        datasetApi.list({ limit: 30 }),
        chatApi.listConversations({ limit: 30 }),
      ]).then(([documentsResult, datasetsResult, conversationsResult]) => {
        if (seq !== requestSeqRef.current) return

        if (documentsResult.status === "fulfilled") {
          setDocResults(documentsResult.value.items || [])
        } else {
          setDocResults([])
        }
        setDocLoading(false)

        if (datasetsResult.status === "fulfilled") {
          const items = (datasetsResult.value.items || [])
            .filter((dataset) => matchesSearchNeedle([dataset.name, dataset.description], needle))
            .slice(0, 6)
          setDatasetResults(items)
        } else {
          setDatasetResults([])
        }
        setDatasetLoading(false)

        if (conversationsResult.status === "fulfilled") {
          const items = (conversationsResult.value.items || [])
            .filter((conversation) => matchesSearchNeedle([conversation.title, conversation.last_message], needle))
            .slice(0, 6)
          setConversationResults(items)
        } else {
          setConversationResults([])
        }
        setConversationLoading(false)
      })
    }, 220)

    return () => globalThis.window.clearTimeout(t)
  }, [open, query])

  const runCommand = React.useCallback((command: () => unknown) => {
    setOpen(false)
    command()
  }, [])

  const keyChordCommands = React.useMemo<KeyChordCommand[]>(
    () => [
      {
        key: 'g d',
        label: 'Go to Documents',
        description: '跳到知识库文档工作台。',
        run: () => router.push('/knowledge'),
      },
      {
        key: 'g c',
        label: 'Go to Chat',
        description: '返回主对话视图。',
        run: () => router.push('/'),
      },
      {
        key: 'g g',
        label: 'Go to Graph',
        description: '打开图谱工作台。',
        run: () => router.push('/graph'),
      },
      {
        key: 'f s',
        label: 'Find Slice',
        description: '进入切片工作台，继续检索与诊断。',
        run: () => router.push('/chunk-preview'),
      },
    ],
    [router]
  )
  const chordPrefixes = React.useMemo(
    () => new Set(keyChordCommands.map((command) => command.key.split(' ')[0] || '')),
    [keyChordCommands]
  )
  const keyChordCommandMap = React.useMemo(
    () => new Map(keyChordCommands.map((command) => [command.key, command.run])),
    [keyChordCommands]
  )

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

  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        toggleOpen()
        clearPendingChord()
        return
      }

      if (open || e.metaKey || e.ctrlKey || e.altKey) return
      if (isEditableTarget(e.target)) return

      const key = normalizeChordKey(e.key)
      if (!key || key.length !== 1) {
        if (key === 'escape') clearPendingChord()
        return
      }

      if (pendingChordPrefix) {
        const sequence = `${pendingChordPrefix} ${key}`
        const action = keyChordCommandMap.get(sequence)
        if (action) {
          e.preventDefault()
          clearPendingChord()
          action()
          return
        }
      }

      if (chordPrefixes.has(key)) {
        e.preventDefault()
        armPendingChord(key)
        return
      }

      clearPendingChord()
    }

    document.addEventListener("keydown", down)
    return () => document.removeEventListener("keydown", down)
  }, [armPendingChord, chordPrefixes, clearPendingChord, keyChordCommandMap, open, pendingChordPrefix, toggleOpen])

  React.useEffect(() => {
    if (open) clearPendingChord()
  }, [clearPendingChord, open])

  React.useEffect(
    () => () => {
      if (chordTimerRef.current != null) {
        globalThis.window.clearTimeout(chordTimerRef.current)
      }
    },
    []
  )

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <div
        id="mimirq-command-menu"
        className="flex items-center justify-between border-b border-border/50 bg-muted/50 px-3 py-2 text-[11px] text-muted-foreground"
      >
        <span className="font-medium text-foreground/80">Command Center</span>
        <span>输入 <span className="font-semibold text-foreground">/</span> 查看快捷动作 · 试试 g d / g c / g g / f s</span>
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

        <CommandGroup heading="键盘工作流">
          {keyChordCommands.map((command) => (
            <CommandItem key={command.key} onSelect={() => runCommand(command.run)}>
              <Workflow className="mr-2 h-4 w-4" />
              <div className="flex min-w-0 flex-1 flex-col">
                <span>{command.label}</span>
                <span className="truncate text-xs text-muted-foreground">{command.description}</span>
              </div>
              <CommandShortcut>{command.key}</CommandShortcut>
            </CommandItem>
          ))}
        </CommandGroup>

        <CommandSeparator />

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
            {query.trim().length >= 4 ? (
              <>
                <CommandGroup heading="AI 快捷动作">
                  <CommandItem
                    value={`ai ${query.trim()}`}
                    onSelect={() =>
                      runCommand(() => {
                        const params = new URLSearchParams({
                          prompt: query.trim(),
                          autorun: "1",
                        })
                        router.push(`/?${params.toString()}`)
                      })
                    }
                  >
                    <Sparkles className="mr-2 h-4 w-4" />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span>执行自然语言指令</span>
                      <span className="truncate text-xs text-muted-foreground">
                        直接把当前输入发送给 AI，并立即开始执行。
                      </span>
                    </div>
                  </CommandItem>
                </CommandGroup>

                <CommandSeparator />
              </>
            ) : null}

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

            <CommandGroup heading="数据集">
              {(() => {
    if (datasetLoading) {
        return (<CommandItem disabled value="dataset:loading">
                  <Database className="mr-2 h-4 w-4"/>
                  <span>搜索中…</span>
                </CommandItem>);
    }
    else if (datasetResults.length) {
            return (datasetResults.map((dataset) => (<CommandItem key={dataset.id} value={`${dataset.name} ${dataset.description || ''}`} onSelect={() => runCommand(() => {
                    router.push(`/datasets/${dataset.id}/profile`);
                })}>
                    <Database className="mr-2 h-4 w-4"/>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{dataset.name}</span>
                      {dataset.description ? <span className="truncate text-xs text-muted-foreground">{dataset.description}</span> : null}
                    </div>
                  </CommandItem>)));
        }
        else {
            return (<CommandItem disabled value="dataset:empty">
                  <Database className="mr-2 h-4 w-4"/>
                  <span>未找到数据集</span>
                </CommandItem>);
        }
})()}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading="对话">
              {(() => {
    if (conversationLoading) {
        return (<CommandItem disabled value="conversation:loading">
                  <MessageSquare className="mr-2 h-4 w-4"/>
                  <span>搜索中…</span>
                </CommandItem>);
    }
    else if (conversationResults.length) {
            return (conversationResults.map((conversation) => (<CommandItem key={conversation.id} value={`${conversation.title || ''} ${conversation.last_message || ''}`} onSelect={() => runCommand(() => {
                    router.push(`/history?id=${conversation.id}`);
                })}>
                    <MessageSquare className="mr-2 h-4 w-4"/>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{conversation.title || '未命名对话'}</span>
                      {conversation.last_message ? <span className="truncate text-xs text-muted-foreground">{conversation.last_message}</span> : null}
                    </div>
                  </CommandItem>)));
        }
        else {
            return (<CommandItem disabled value="conversation:empty">
                  <MessageSquare className="mr-2 h-4 w-4"/>
                  <span>未找到对话</span>
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
