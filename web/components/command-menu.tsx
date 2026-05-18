"use client"

import * as React from "react"
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
  RefreshCw,
  Settings,
  Sparkles,
  Workflow,
  Keyboard,
} from "lucide-react"
import { useTheme } from "next-themes"
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'

import type { Conversation, Dataset, Document } from "@/types"
import { chatApi, datasetApi, documentApi } from "@/lib/api"
import { globalEventBus } from "@/lib/event-bus"
import { queryKeys } from '@/lib/query-keys'
import { usePathname, useRouter } from "@/i18n/navigation"
import { useCommandMenuState } from "@/store/command-menu"
import { useDocumentView } from "@/store/document-view"
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { canShowAdminControlledNavigationModule, type AdminControlledNavigationModule } from '@/lib/navigation-visibility'

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

type SlashCommandId =
  | "resume"
  | "upload"
  | "analyze"
  | "report"
  | "stats"
  | "retryFailed"
  | "pauseActive"
  | "precheck"
  | "datasets"
  | "history"
  | "graph"
  | "diagnostics"
  | "settings"
  | "parsing"
  | "reports"
  | "observability"
  | "governance"
  | "accessReview"

type SlashCommand = {
  id: SlashCommandId
  label: string
  description: string
  shortcut: string
  keywords: string[]
  icon: React.ComponentType<{ className?: string }>
  visibilityKey?: AdminControlledNavigationModule
  run: () => void
}

type KeyChordCommandId = "documents" | "chat" | "graph" | "observability" | "slice" | "resume"

type KeyChordCommand = {
  id: KeyChordCommandId
  key: string
  label: string
  description: string
  visibilityKey?: AdminControlledNavigationModule
  run: () => void
}

type ShortcutGuideItem = {
  shortcut: string
  label: string
  description: string
}

type ViewerShortcutId = "resume" | "focusSearch" | "cycleHits" | "find" | "dismiss"

type ShortcutDocItem = {
  key: string
  label: string
  description: string
}

type ModuleWorkbenchId =
  | "knowledge"
  | "graph"
  | "slices"
  | "parsing"
  | "reports"
  | "observability"
  | "governance"
  | "accessReview"

type ModuleWorkbenchItem = {
  id: ModuleWorkbenchId
  label: string
  description: string
  keywords: string[]
  icon: React.ComponentType<{ className?: string }>
  visibilityKey?: AdminControlledNavigationModule
  run: () => void
}

type CommandMenuTranslationGetter = (key: string) => string

const KEY_CHORD_TIMEOUT_MS = 1600
const COMMAND_MENU_SEARCH_DEBOUNCE_MS = 220
const COMMAND_MENU_DOCUMENT_SEARCH_LIMIT = 8
const COMMAND_MENU_DATASET_SEARCH_PARAMS = { limit: 30 }
const COMMAND_MENU_CONVERSATION_SEARCH_PARAMS = { limit: 30 }

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tagName = target.tagName
  return target.isContentEditable || tagName === "INPUT" || tagName === "TEXTAREA" || tagName === "SELECT"
}

function normalizeChordKey(key: string): string {
  return String(key || "").trim().toLowerCase()
}

function buildCurrentViewPrompt(pathname: string, t: CommandMenuTranslationGetter): { prompt: string; description: string } {
  if (pathname.startsWith("/graph")) {
    return {
      prompt: t("currentView.graph.prompt"),
      description: t("currentView.graph.description"),
    }
  }

  if (pathname.startsWith("/knowledge")) {
    return {
      prompt: t("currentView.knowledge.prompt"),
      description: t("currentView.knowledge.description"),
    }
  }

  if (pathname.startsWith("/datasets")) {
    return {
      prompt: t("currentView.datasets.prompt"),
      description: t("currentView.datasets.description"),
    }
  }

  if (pathname.startsWith("/settings")) {
    return {
      prompt: t("currentView.settings.prompt"),
      description: t("currentView.settings.description"),
    }
  }

  if (pathname.startsWith("/observability") || pathname.startsWith("/reports")) {
    return {
      prompt: t("currentView.observability.prompt"),
      description: t("currentView.observability.description"),
    }
  }

  return {
    prompt: t("currentView.default.prompt"),
    description: t("currentView.default.description"),
  }
}

function matchesSearchNeedle(values: Array<string | null | undefined>, needle: string): boolean {
  const normalizedNeedle = String(needle || "").trim().toLowerCase()
  if (!normalizedNeedle) return true

  return values.some((value) => String(value || "").toLowerCase().includes(normalizedNeedle))
}

export function CommandMenu() {
  const [query, setQuery] = React.useState("")
  const [debouncedSearchQuery, setDebouncedSearchQuery] = React.useState("")
  const [pendingChordPrefix, setPendingChordPrefix] = React.useState<string | null>(null)
  const chordTimerRef = React.useRef<number | null>(null)
  const router = useRouter()
  const pathname = usePathname()
  const { setTheme } = useTheme()
  const t = useTranslations('CommandMenu')
  const open = useCommandMenuState((state) => state.open)
  const setOpen = useCommandMenuState((state) => state.setOpen)
  const toggleOpen = useCommandMenuState((state) => state.toggle)
  const { lastOpenedTarget, openDocument, reopenLastDocument } = useDocumentView()
  const tenantAccess = useTenantAccess()
  const currentViewPrompt = React.useMemo(() => buildCurrentViewPrompt(pathname || '/', t), [pathname, t])
  const trimmedQuery = query.trim()
  const isSlashMode = trimmedQuery.startsWith("/")
  const slashNeedle = trimmedQuery.slice(1).toLowerCase()
  const shouldShowShortcutReference = trimmedQuery.length === 0
  const hasTypedSearchQuery = trimmedQuery.length >= 2 && !isSlashMode
  const isTypedSearchActive = open && hasTypedSearchQuery
  const isSearchDebouncing = isTypedSearchActive && debouncedSearchQuery !== trimmedQuery
  const showBaseCommandGroups = !hasTypedSearchQuery && !isSlashMode
  const hasResumeTarget = Boolean(lastOpenedTarget?.documentId)
  const canShowNavigationModule = React.useCallback(
    (moduleKey?: AdminControlledNavigationModule) =>
      canShowAdminControlledNavigationModule(tenantAccess.data, moduleKey),
    [tenantAccess.data]
  )

  const documentSearchParams = React.useMemo(
    () => ({
      q: debouncedSearchQuery,
      limit: COMMAND_MENU_DOCUMENT_SEARCH_LIMIT,
      order_by: "created_at" as const,
      order_dir: "desc" as const,
    }),
    [debouncedSearchQuery]
  )

  const documentSearchQuery = useQuery<Document[]>({
    queryKey: queryKeys.documents.list(documentSearchParams),
    queryFn: async () => {
      const response = await documentApi.list(documentSearchParams)
      return response.items || []
    },
    enabled: Boolean(debouncedSearchQuery),
    staleTime: 30_000,
  })

  const datasetSearchQuery = useQuery<Dataset[]>({
    queryKey: queryKeys.datasets.list(COMMAND_MENU_DATASET_SEARCH_PARAMS),
    queryFn: async () => {
      const response = await datasetApi.list(COMMAND_MENU_DATASET_SEARCH_PARAMS)
      return response.items || []
    },
    enabled: Boolean(debouncedSearchQuery),
    staleTime: 60_000,
  })

  const conversationSearchQuery = useQuery<Conversation[]>({
    queryKey: queryKeys.chat.conversations(COMMAND_MENU_CONVERSATION_SEARCH_PARAMS),
    queryFn: async () => {
      const response = await chatApi.listConversations(COMMAND_MENU_CONVERSATION_SEARCH_PARAMS)
      return response.items || []
    },
    enabled: Boolean(debouncedSearchQuery),
    staleTime: 30_000,
  })

  const searchNeedle = debouncedSearchQuery.toLowerCase()
  const docResults = debouncedSearchQuery ? documentSearchQuery.data || [] : []
  const datasetResults = React.useMemo(() => {
    if (!debouncedSearchQuery) return []
    return (datasetSearchQuery.data || [])
      .filter((dataset) => matchesSearchNeedle([dataset.name, dataset.description], searchNeedle))
      .slice(0, 6)
  }, [datasetSearchQuery.data, debouncedSearchQuery, searchNeedle])
  const conversationResults = React.useMemo(() => {
    if (!debouncedSearchQuery) return []
    return (conversationSearchQuery.data || [])
      .filter((conversation) => matchesSearchNeedle([conversation.title, conversation.last_message], searchNeedle))
      .slice(0, 6)
  }, [conversationSearchQuery.data, debouncedSearchQuery, searchNeedle])
  const docLoading = isSearchDebouncing || (Boolean(debouncedSearchQuery) && documentSearchQuery.isFetching)
  const datasetLoading = isSearchDebouncing || (Boolean(debouncedSearchQuery) && datasetSearchQuery.isFetching)
  const conversationLoading =
    isSearchDebouncing || (Boolean(debouncedSearchQuery) && conversationSearchQuery.isFetching)

  const resumeLastDocumentContext = React.useCallback(() => {
    if (!hasResumeTarget) return
    reopenLastDocument()
    router.push("/")
  }, [hasResumeTarget, reopenLastDocument, router])

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

  React.useEffect(() => {
    if (!open) setQuery("")
  }, [open])

  React.useEffect(() => {
    if (!isTypedSearchActive) {
      setDebouncedSearchQuery("")
      return
    }

    const timeoutId = globalThis.window.setTimeout(() => {
      setDebouncedSearchQuery(trimmedQuery)
    }, COMMAND_MENU_SEARCH_DEBOUNCE_MS)

    return () => globalThis.window.clearTimeout(timeoutId)
  }, [isTypedSearchActive, trimmedQuery])

  const runCommand = React.useCallback(
    (command: () => unknown) => {
      setQuery("")
      setDebouncedSearchQuery("")
      setOpen(false)
      command()
    },
    [setOpen]
  )

  const keyChordCommands = React.useMemo<KeyChordCommand[]>(
    () =>
      ([
        { id: "documents", key: "g d", visibilityKey: undefined, run: () => router.push("/knowledge") },
        { id: "chat", key: "g c", visibilityKey: undefined, run: () => router.push("/") },
        { id: "graph", key: "g g", visibilityKey: 'knowledgeGraph', run: () => router.push("/graph") },
        { id: "observability", key: "g o", visibilityKey: undefined, run: () => router.push("/observability") },
        { id: "slice", key: "f s", visibilityKey: undefined, run: () => router.push("/chunk-preview") },
        { id: "resume", key: "g v", visibilityKey: undefined, run: resumeLastDocumentContext },
      ] as const).filter((command) => canShowNavigationModule(command.visibilityKey)).map(({ id, key, visibilityKey, run }) => ({
        id,
        key,
        visibilityKey,
        label: t(`keyChords.${id}.label`),
        description:
          id === "resume" && !hasResumeTarget
            ? t("keyChords.resume.emptyDescription")
            : t(`keyChords.${id}.description`),
        run,
      })),
    [canShowNavigationModule, hasResumeTarget, resumeLastDocumentContext, router, t]
  )

  const chordPrefixes = React.useMemo(
    () => new Set(keyChordCommands.map((command) => command.key.split(" ")[0] || "")),
    [keyChordCommands]
  )

  const keyChordCommandMap = React.useMemo(
    () => new Map(keyChordCommands.map((command) => [command.key, command.run])),
    [keyChordCommands]
  )

  const shortcutGuideItems = React.useMemo<ShortcutGuideItem[]>(
    () => [
      {
        shortcut: "⌘K / Ctrl+K",
        label: t("shortcutGuide.open.label"),
        description: t("shortcutGuide.open.description"),
      },
      {
        shortcut: "?",
        label: t("shortcutGuide.help.label"),
        description: t("shortcutGuide.help.description"),
      },
      ...keyChordCommands.map((command) => ({
        shortcut: command.key,
        label: command.label,
        description: `${t("shortcutGuide.chordPrefix")} ${command.description}`,
      })),
      {
        shortcut: "h / l",
        label: t("shortcutGuide.stagePrevNext.label"),
        description: t("shortcutGuide.stagePrevNext.description"),
      },
      {
        shortcut: "← / →",
        label: t("shortcutGuide.stageArrows.label"),
        description: t("shortcutGuide.stageArrows.description"),
      },
      {
        shortcut: "j / k",
        label: t("shortcutGuide.sliceFocus.label"),
        description: t("shortcutGuide.sliceFocus.description"),
      },
    ],
    [keyChordCommands, t]
  )

  const slashCommands = React.useMemo<SlashCommand[]>(
    () =>
      ([
        { id: "resume", shortcut: "/resume", icon: FileText, visibilityKey: undefined },
        { id: "upload", shortcut: "/upload", icon: Upload, visibilityKey: undefined },
        { id: "analyze", shortcut: "/analyze", icon: Sparkles, visibilityKey: undefined },
        { id: "report", shortcut: "/report", icon: FileText, visibilityKey: undefined },
        { id: "stats", shortcut: "/stats", icon: Coins, visibilityKey: undefined },
        { id: "retryFailed", shortcut: "/retry-failed", icon: RefreshCw, visibilityKey: undefined },
        { id: "pauseActive", shortcut: "/pause-active", icon: Activity, visibilityKey: undefined },
        { id: "precheck", shortcut: "/precheck", icon: Workflow, visibilityKey: undefined },
        { id: "datasets", shortcut: "/datasets", icon: Database, visibilityKey: undefined },
        { id: "history", shortcut: "/history", icon: History, visibilityKey: undefined },
        { id: "graph", shortcut: "/graph", icon: Workflow, visibilityKey: 'knowledgeGraph' },
        { id: "diagnostics", shortcut: "/diagnostics", icon: Activity, visibilityKey: undefined },
        { id: "settings", shortcut: "/settings", icon: Settings, visibilityKey: undefined },
        { id: "parsing", shortcut: "/parsing", icon: FileText, visibilityKey: undefined },
        { id: "reports", shortcut: "/reports", icon: FileText, visibilityKey: 'reports' },
        { id: "observability", shortcut: "/observability", icon: Activity, visibilityKey: undefined },
        { id: "governance", shortcut: "/governance", icon: Database, visibilityKey: undefined },
        { id: "accessReview", shortcut: "/access", icon: Settings, visibilityKey: undefined },
      ] as const).map(({ id, shortcut, icon, visibilityKey }) => ({
        id,
        visibilityKey,
        label: t(`slash.commands.${id}.label`),
        description:
          id === "analyze"
            ? currentViewPrompt.description
            : id === "resume" && !hasResumeTarget
              ? t("slash.commands.resume.emptyDescription")
              : t(`slash.commands.${id}.description`),
        shortcut,
        keywords: t.raw(`slash.commands.${id}.keywords`) as string[],
        icon,
        run: () => {
          if (id === "resume") {
            resumeLastDocumentContext()
            return
          }

          if (id === "analyze") {
            const params = new URLSearchParams({
              prompt: currentViewPrompt.prompt,
              autorun: "1",
            })
            router.push(`/?${params.toString()}`)
            return
          }

          if (id === "report") {
            if (pathname.startsWith("/knowledge/ingestion")) {
              globalEventBus.emit('ingestion:download-report', undefined)
              return
            }
            router.push("/knowledge/ingestion")
            return
          }

          if (id === "upload") {
            router.push("/knowledge")
            return
          }

          if (id === "stats") {
            router.push("/usage")
            return
          }

          if (id === "retryFailed") {
            if (pathname.startsWith("/knowledge/ingestion")) {
              globalEventBus.emit('ingestion:retry-all-failed', undefined)
              return
            }
            router.push("/knowledge/ingestion")
            return
          }

          if (id === "pauseActive") {
            if (pathname.startsWith("/knowledge/ingestion")) {
              globalEventBus.emit('ingestion:cancel-all-active', undefined)
              return
            }
            router.push("/knowledge/ingestion")
            return
          }

          if (id === "precheck") {
            if (pathname.startsWith("/knowledge/ingestion")) {
              globalEventBus.emit('ingestion:open-precheck', undefined)
              return
            }
            router.push("/datasets")
            return
          }

          if (id === "datasets") {
            router.push("/datasets")
            return
          }

          if (id === "history") {
            router.push("/history")
            return
          }

          if (id === "graph") {
            router.push("/graph")
            return
          }

          if (id === "diagnostics") {
            router.push("/diagnostics")
            return
          }

          if (id === "settings") {
            router.push("/settings")
            return
          }

          if (id === "parsing") {
            router.push("/parsing")
            return
          }

          if (id === "reports") {
            router.push("/reports")
            return
          }

          if (id === "observability") {
            router.push("/observability")
            return
          }

          if (id === "governance") {
            router.push("/data-governance")
            return
          }

          router.push("/access-review")
        },
      })),
    [currentViewPrompt.description, currentViewPrompt.prompt, hasResumeTarget, pathname, resumeLastDocumentContext, router, t]
  )

  const viewerShortcutDocs = React.useMemo<ShortcutDocItem[]>(
    () =>
      ([
        { id: "resume", key: "g v" },
        { id: "focusSearch", key: "/" },
        { id: "cycleHits", key: "j / k" },
        { id: "find", key: "Ctrl/Cmd+F" },
        { id: "dismiss", key: "Esc" },
      ] as const).map(({ id, key }) => ({
        key,
        label: t(`viewerShortcuts.${id}.label`),
        description: t(`viewerShortcuts.${id}.description`),
      })),
    [t]
  )

  const filteredSlashCommands = React.useMemo(
    () =>
      slashCommands.filter((command) => {
        if (!canShowNavigationModule(command.visibilityKey)) return false
        if (!slashNeedle) return true
        const haystack = [command.shortcut, command.label, command.description, ...command.keywords]
          .join(" ")
          .toLowerCase()
        return haystack.includes(slashNeedle)
      }),
    [canShowNavigationModule, slashCommands, slashNeedle]
  )

  const moduleWorkbenchItems = React.useMemo<ModuleWorkbenchItem[]>(
    () =>
      ([
        { id: "knowledge", icon: Database, visibilityKey: undefined, run: () => router.push("/knowledge") },
        { id: "graph", icon: Workflow, visibilityKey: 'knowledgeGraph', run: () => router.push("/graph") },
        { id: "slices", icon: FileText, visibilityKey: undefined, run: () => router.push("/chunk-preview") },
        { id: "parsing", icon: FileText, visibilityKey: undefined, run: () => router.push("/parsing") },
        { id: "reports", icon: FileText, visibilityKey: 'reports', run: () => router.push("/reports") },
        { id: "observability", icon: Activity, visibilityKey: undefined, run: () => router.push("/observability") },
        { id: "governance", icon: Database, visibilityKey: undefined, run: () => router.push("/data-governance") },
        { id: "accessReview", icon: Settings, visibilityKey: undefined, run: () => router.push("/access-review") },
      ] as const)
        .filter((item) => canShowNavigationModule(item.visibilityKey))
        .map(({ id, icon, visibilityKey, run }) => ({
        id,
        visibilityKey,
        label: t(`modules.${id}.label`),
        description: t(`modules.${id}.description`),
        keywords: t.raw(`modules.${id}.keywords`) as string[],
        icon,
        run,
      })),
    [canShowNavigationModule, router, t]
  )

  const moduleWorkbenchResults = React.useMemo(() => {
    if (isSlashMode) return []
    const needle = query.trim().toLowerCase()
    if (needle.length < 2) return []

    return moduleWorkbenchItems.filter((item) =>
      matchesSearchNeedle([item.label, item.description, item.keywords.join(" ")], needle)
    )
  }, [isSlashMode, moduleWorkbenchItems, query])

  const navigationItems = React.useMemo(
    () => [
      { icon: Home, label: t("navigation.home"), run: () => router.push("/") },
      { icon: MessageSquare, label: t("navigation.newConversation"), run: () => router.push("/") },
      { icon: Database, label: t("navigation.knowledge"), run: () => router.push("/knowledge") },
      { icon: FileText, label: t("navigation.parsing"), run: () => router.push("/parsing") },
      { icon: History, label: t("navigation.history"), run: () => router.push("/history") },
      { icon: Settings, label: t("navigation.settings"), run: () => router.push("/settings") },
    ],
    [router, t]
  )

  const actionItems = React.useMemo(
    () => [
      { icon: Upload, label: t("actions.uploadDocument"), run: () => router.push("/knowledge") },
      { icon: Settings, label: t("actions.ragSettings"), run: () => router.push("/?rag=1") },
    ],
    [router, t]
  )

  const themeItems = React.useMemo(
    () => [
      { icon: Sun, label: t("theme.light"), run: () => setTheme("light") },
      { icon: Moon, label: t("theme.dark"), run: () => setTheme("dark") },
      { icon: Laptop, label: t("theme.system"), run: () => setTheme("system") },
    ],
    [setTheme, t]
  )

  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        toggleOpen()
        clearPendingChord()
        return
      }

      if (e.key === "?" && !e.metaKey && !e.ctrlKey && !e.altKey && !isEditableTarget(e.target)) {
        e.preventDefault()
        setOpen(true)
        clearPendingChord()
        return
      }

      if (open || e.metaKey || e.ctrlKey || e.altKey) return
      if (isEditableTarget(e.target)) return

      const key = normalizeChordKey(e.key)
      if (!key || key.length !== 1) {
        if (key === "escape") clearPendingChord()
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
  }, [armPendingChord, chordPrefixes, clearPendingChord, keyChordCommandMap, open, pendingChordPrefix, setOpen, toggleOpen])

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
        className="flex items-center justify-between border-b border-border/50 bg-card/95 px-3 py-2 text-[11px] text-muted-foreground"
      >
        <span className="font-medium text-foreground/80">{t("header.title")}</span>
        <span>{t("header.hint")}</span>
      </div>
      <CommandInput placeholder={t('search.placeholder')} value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>{t('search.empty')}</CommandEmpty>

        {isSlashMode ? (
          <>
            <CommandGroup heading={t('groups.slash')}>
              {filteredSlashCommands.map((command) => {
                const Icon = command.icon
                return (
                  <CommandItem
                    key={command.id}
                    value={`${command.shortcut} ${command.label} ${command.keywords.join(" ")}`}
                    className="gap-3 rounded-lg px-3 py-2.5"
                    onSelect={() => runCommand(command.run)}
                  >
                    <div className="flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      <Icon className="size-4" />
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

        {showBaseCommandGroups ? (
          <>
            <CommandGroup heading={t("groups.keyboardWorkflow")}>
              {keyChordCommands.map((command) => (
                <CommandItem key={command.key} onSelect={() => runCommand(command.run)}>
                  <Workflow className="mr-2 size-4" />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span>{command.label}</span>
                    <span className="truncate text-xs text-muted-foreground">{command.description}</span>
                  </div>
                  <CommandShortcut>{command.key}</CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>

            <CommandSeparator />

            {shouldShowShortcutReference ? (
              <>
                <CommandGroup heading={t('groups.viewerShortcuts')}>
                  {viewerShortcutDocs.map((shortcut) => (
                    <CommandItem key={shortcut.key} value={`viewer-shortcut ${shortcut.key} ${shortcut.label}`} disabled>
                      <FileText className="mr-2 size-4" />
                      <div className="flex min-w-0 flex-1 flex-col">
                        <span>{shortcut.label}</span>
                        <span className="truncate text-xs text-muted-foreground">{shortcut.description}</span>
                      </div>
                      <CommandShortcut>{shortcut.key}</CommandShortcut>
                    </CommandItem>
                  ))}
                </CommandGroup>

                <CommandSeparator />

                <CommandGroup heading={t('groups.shortcutMap')}>
                  {shortcutGuideItems.map((item) => (
                    <CommandItem key={`${item.shortcut}:${item.label}`} disabled value={`${item.shortcut} ${item.label}`}>
                      <Keyboard className="mr-2 size-4" />
                      <div className="flex min-w-0 flex-1 flex-col">
                        <span>{item.label}</span>
                        <span className="truncate text-xs text-muted-foreground">{item.description}</span>
                      </div>
                      <CommandShortcut>{item.shortcut}</CommandShortcut>
                    </CommandItem>
                  ))}
                </CommandGroup>

                <CommandSeparator />
              </>
            ) : null}

            <CommandGroup heading={t('groups.navigation')}>
              {navigationItems.map((item) => (
                <CommandItem key={item.label} onSelect={() => runCommand(item.run)}>
                  <item.icon className="mr-2 size-4" />
                  <span>{item.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>

            <CommandSeparator />
          </>
        ) : null}

        {hasTypedSearchQuery ? (
          <>
            {trimmedQuery.length >= 4 ? (
              <>
                <CommandGroup heading={t('groups.aiActions')}>
                  <CommandItem
                    value={`ai ${trimmedQuery}`}
                    onSelect={() =>
                      runCommand(() => {
                        const params = new URLSearchParams({
                          prompt: trimmedQuery,
                          autorun: "1",
                        })
                        router.push(`/?${params.toString()}`)
                      })
                    }
                  >
                    <Sparkles className="mr-2 size-4" />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span>{t("aiAction.label")}</span>
                      <span className="truncate text-xs text-muted-foreground">{t("aiAction.description")}</span>
                    </div>
                  </CommandItem>
                </CommandGroup>

                <CommandSeparator />
              </>
            ) : null}

            <CommandGroup heading={t('groups.modules')}>
              {moduleWorkbenchResults.length ? (
                moduleWorkbenchResults.map((item) => {
                  const Icon = item.icon
                  return (
                    <CommandItem
                      key={item.id}
                      value={`${item.label} ${item.description} ${item.keywords.join(" ")}`}
                      onSelect={() => runCommand(item.run)}
                    >
                      <Icon className="mr-2 size-4" />
                      <div className="flex min-w-0 flex-1 flex-col">
                        <span>{item.label}</span>
                        <span className="truncate text-xs text-muted-foreground">{item.description}</span>
                      </div>
                    </CommandItem>
                  )
                })
              ) : (
                <CommandItem disabled value="workbench:empty">
                  <Workflow className="mr-2 size-4" />
                  <span>{t("results.modulesEmpty")}</span>
                </CommandItem>
              )}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.documents')}>
              {docLoading ? (
                <CommandItem disabled value="doc:loading">
                  <FileText className="mr-2 size-4" />
                  <span>{t("results.documentsLoading")}</span>
                </CommandItem>
              ) : docResults.length ? (
                docResults.map((doc) => (
                  <CommandItem
                    key={doc.id}
                    value={doc.filename}
                    onSelect={() =>
                      runCommand(() => {
                        openDocument(doc.id)
                        router.push("/")
                      })
                    }
                  >
                    <FileText className="mr-2 size-4" />
                    <span className="truncate">{doc.filename}</span>
                  </CommandItem>
                ))
              ) : (
                <CommandItem disabled value="doc:empty">
                  <FileText className="mr-2 size-4" />
                  <span>{t("results.documentsEmpty")}</span>
                </CommandItem>
              )}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.datasets')}>
              {datasetLoading ? (
                <CommandItem disabled value="dataset:loading">
                  <Database className="mr-2 size-4" />
                  <span>{t("results.datasetsLoading")}</span>
                </CommandItem>
              ) : datasetResults.length ? (
                datasetResults.map((dataset) => (
                  <CommandItem
                    key={dataset.id}
                    value={`${dataset.name} ${dataset.description || ""}`}
                    onSelect={() => runCommand(() => router.push(`/datasets/${dataset.id}/profile`))}
                  >
                    <Database className="mr-2 size-4" />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{dataset.name}</span>
                      {dataset.description ? (
                        <span className="truncate text-xs text-muted-foreground">{dataset.description}</span>
                      ) : null}
                    </div>
                  </CommandItem>
                ))
              ) : (
                <CommandItem disabled value="dataset:empty">
                  <Database className="mr-2 size-4" />
                  <span>{t("results.datasetsEmpty")}</span>
                </CommandItem>
              )}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.conversations')}>
              {conversationLoading ? (
                <CommandItem disabled value="conversation:loading">
                  <MessageSquare className="mr-2 size-4" />
                  <span>{t("results.conversationsLoading")}</span>
                </CommandItem>
              ) : conversationResults.length ? (
                conversationResults.map((conversation) => (
                  <CommandItem
                    key={conversation.id}
                    value={`${conversation.title || ""} ${conversation.last_message || ""}`}
                    onSelect={() => runCommand(() => router.push(`/history?id=${conversation.id}`))}
                  >
                    <MessageSquare className="mr-2 size-4" />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{conversation.title || t("results.untitledConversation")}</span>
                      {conversation.last_message ? (
                        <span className="truncate text-xs text-muted-foreground">{conversation.last_message}</span>
                      ) : null}
                    </div>
                  </CommandItem>
                ))
              ) : (
                <CommandItem disabled value="conversation:empty">
                  <MessageSquare className="mr-2 size-4" />
                  <span>{t("results.conversationsEmpty")}</span>
                </CommandItem>
              )}
            </CommandGroup>

            <CommandSeparator />
          </>
        ) : null}

        {showBaseCommandGroups ? (
          <>
            <CommandGroup heading={t("groups.actions")}>
              {actionItems.map((item) => (
                <CommandItem key={item.label} onSelect={() => runCommand(item.run)}>
                  <item.icon className="mr-2 size-4" />
                  <span>{item.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.theme')}>
              {themeItems.map((item) => (
                <CommandItem key={item.label} onSelect={() => runCommand(item.run)}>
                  <item.icon className="mr-2 size-4" />
                  <span>{item.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        ) : null}
      </CommandList>
    </CommandDialog>
  )
}
