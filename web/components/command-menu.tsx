'use client'

import * as React from 'react'
import type { ComponentType } from 'react'
import {
  Chunking,
  DataGovernance,
  Dataset as DatasetIcon,
  Diagnostics,
  KnowledgeGraph,
  Network,
  Parsing,
  Reports,
  Upload,
  Coins,
  Moon,
  Sun,
  Laptop,
  MessageSquare,
  KnowledgeBase as Database,
  Home,
  FileText,
  History,
  Settings,
  Search,
  Sparkles,
  Workflow,
  Keyboard,
  CornerDownLeft,
} from '@/components/icons'
import { useTheme } from 'next-themes'
import { useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'

import { chatApi } from '@/lib/api/chat'
import { datasetApi } from '@/lib/api/datasets'
import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { AUTH_SCOPE_CHANGED_EVENT } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { usePathname, useRouter } from '@/i18n/navigation'
import { useCommandMenuState } from '@/store/command-menu'
import { useDocumentView } from '@/store/document-view'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { TENANT_PERMISSIONS, tenantAccessAllows } from '@/lib/tenant-permissions'
import {
  canShowAdminControlledNavigationModule,
  type AdminControlledNavigationModule,
} from '@/lib/navigation-visibility'

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
  CommandSeparator,
} from '@/components/ui/command'
import { Button } from '@/components/ui/button'
import { FileTypeIcon } from '@/components/ui/file-type-icon'

type SlashCommandId =
  | 'resume'
  | 'upload'
  | 'analyze'
  | 'report'
  | 'stats'
  | 'precheck'
  | 'datasets'
  | 'history'
  | 'graph'
  | 'diagnostics'
  | 'settings'
  | 'parsing'
  | 'reports'
  | 'observability'
  | 'governance'

type SlashCommand = {
  id: SlashCommandId
  label: string
  description: string
  shortcut: string
  keywords: string[]
  icon: ComponentType<{ className?: string }>
  visibilityKey?: AdminControlledNavigationModule
  run: () => void
}

type KeyChordCommandId = 'documents' | 'chat' | 'graph' | 'observability' | 'slice' | 'resume'

type KeyChordCommand = {
  id: KeyChordCommandId
  key: string
  label: string
  description: string
  icon: ComponentType<{ className?: string }>
  visibilityKey?: AdminControlledNavigationModule
  run: () => void
}

type ShortcutGuideItem = {
  shortcut: string
  label: string
  description: string
}

type ShortcutDocItem = {
  key: string
  label: string
  description: string
}

type ModuleWorkbenchId =
  'knowledge' | 'graph' | 'ontology' | 'slices' | 'parsing' | 'reports' | 'observability' | 'governance'

type ModuleWorkbenchItem = {
  id: ModuleWorkbenchId
  label: string
  description: string
  keywords: string[]
  icon: ComponentType<{ className?: string }>
  visibilityKey?: AdminControlledNavigationModule
  run: () => void
}

type CommandMenuTranslationGetter = (key: string) => string

type CommandAction = {
  disabled?: boolean
  run: () => void
}

function CommandRowText({ label, description }: Readonly<{ label: string; description?: string }>) {
  return (
    <span className="flex min-w-0 flex-1 items-center gap-2.5" title={description}>
      <span className="min-w-0 truncate font-medium">{label}</span>
      {description !== undefined && (
        <span className="hidden min-w-0 flex-1 truncate text-xs text-muted-foreground sm:inline">{description}</span>
      )}
    </span>
  )
}

function CommandKeySequence({ sequence }: Readonly<{ sequence: string }>) {
  const t = useTranslations('CommandMenu')
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1">
      <span className="sr-only">{t('shortcutGuide.chordPrefix')}</span>
      {sequence.split(' ').map((key, index) => (
        <kbd
          key={`${key}:${index}`}
          className="inline-flex min-w-5 justify-center rounded border border-border bg-card px-1.5 py-0.5 font-mono text-[10px] font-medium text-muted-foreground"
        >
          {key.toUpperCase()}
        </kbd>
      ))}
    </span>
  )
}

function CommandShortcutHelp({
  label,
  description,
  shortcut,
}: Readonly<{ label: string; description: string; shortcut: string }>) {
  const sequential = /^[a-z0-9](?: [a-z0-9])+$/i.test(shortcut)
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="flex min-w-0 items-center justify-between gap-3">
        <span className="min-w-0 font-medium">{label}</span>
        {sequential ? (
          <CommandKeySequence sequence={shortcut} />
        ) : (
          <CommandShortcut className="shrink-0 text-[11px] font-normal">{shortcut}</CommandShortcut>
        )}
      </span>
      <span className="whitespace-normal break-words text-xs leading-5 text-muted-foreground">{description}</span>
    </div>
  )
}

const KEY_CHORD_TIMEOUT_MS = 1600
const COMMAND_MENU_SEARCH_DEBOUNCE_MS = 220
const COMMAND_MENU_SEARCH_MAX_LENGTH = 200
const COMMAND_MENU_DOCUMENT_SEARCH_LIMIT = 8
const COMMAND_MENU_ENTITY_SEARCH_LIMIT = 6

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tagName = target.tagName
  return target.isContentEditable || tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT'
}

function normalizeChordKey(key: string): string {
  return key.trim().toLowerCase()
}

function buildCurrentViewPrompt(
  pathname: string,
  t: CommandMenuTranslationGetter,
): { prompt: string; description: string } {
  if (pathname.startsWith('/graph')) {
    return {
      prompt: t('currentView.graph.prompt'),
      description: t('currentView.graph.description'),
    }
  }

  if (pathname.startsWith('/knowledge')) {
    return {
      prompt: t('currentView.knowledge.prompt'),
      description: t('currentView.knowledge.description'),
    }
  }

  if (pathname.startsWith('/datasets')) {
    return {
      prompt: t('currentView.datasets.prompt'),
      description: t('currentView.datasets.description'),
    }
  }

  if (pathname.startsWith('/settings')) {
    return {
      prompt: t('currentView.settings.prompt'),
      description: t('currentView.settings.description'),
    }
  }

  if (pathname.startsWith('/observability') || pathname.startsWith('/reports')) {
    return {
      prompt: t('currentView.observability.prompt'),
      description: t('currentView.observability.description'),
    }
  }

  return {
    prompt: t('currentView.default.prompt'),
    description: t('currentView.default.description'),
  }
}

function matchesSearchNeedle(values: readonly string[], needle: string): boolean {
  return values.some((value) => value.toLowerCase().includes(needle))
}

export function CommandMenu() {
  const [query, setQuery] = React.useState('')
  const [debouncedSearchQuery, setDebouncedSearchQuery] = React.useState('')
  const [pendingChordPrefix, setPendingChordPrefix] = React.useState<string | null>(null)
  const [showShortcutHelp, setShowShortcutHelp] = React.useState(false)
  const chordTimerRef = React.useRef<number | null>(null)
  const router = useRouter()
  const pathname = usePathname()
  const { setTheme } = useTheme()
  const t = useTranslations('CommandMenu')
  const open = useCommandMenuState((state) => state.open)
  const setOpen = useCommandMenuState((state) => state.setOpen)
  const toggleOpen = useCommandMenuState((state) => state.toggle)
  const { lastOpenedTarget, openDocument, reopenLastDocument } = useDocumentView()
  const tenantAccess = useTenantAccess({ enabled: !pathname.startsWith('/auth') })
  const canReadSettings = tenantAccessAllows(tenantAccess.data, TENANT_PERMISSIONS.SETTINGS_READ)
  const canReadObservability = tenantAccessAllows(tenantAccess.data, TENANT_PERMISSIONS.OBSERVABILITY_READ)
  const canReadUsage = tenantAccessAllows(tenantAccess.data, TENANT_PERMISSIONS.USAGE_READ)
  const currentViewPrompt = React.useMemo(() => buildCurrentViewPrompt(pathname, t), [pathname, t])
  const trimmedQuery = query.trim().slice(0, COMMAND_MENU_SEARCH_MAX_LENGTH)
  const isSlashMode = trimmedQuery.startsWith('/')
  const slashNeedle = trimmedQuery.slice(1).toLowerCase()
  const isShortcutHelpQuery = trimmedQuery === '?'
  const shouldShowShortcutReference = (trimmedQuery.length === 0 && showShortcutHelp) || isShortcutHelpQuery
  const hasTypedSearchQuery = trimmedQuery.length >= 2 && !isSlashMode
  const isTypedSearchActive = open && hasTypedSearchQuery
  const isSearchDebouncing = isTypedSearchActive && debouncedSearchQuery !== trimmedQuery
  const showBaseCommandGroups = !hasTypedSearchQuery && !isSlashMode
  const hasResumeTarget = Boolean(lastOpenedTarget?.documentId)
  const canShowNavigationModule = React.useCallback(
    (moduleKey?: AdminControlledNavigationModule) =>
      canShowAdminControlledNavigationModule(tenantAccess.data, moduleKey),
    [tenantAccess.data],
  )

  const documentSearchParams = React.useMemo(
    () => ({
      q: debouncedSearchQuery,
      limit: COMMAND_MENU_DOCUMENT_SEARCH_LIMIT,
      order_by: 'created_at' as const,
      order_dir: 'desc' as const,
    }),
    [debouncedSearchQuery],
  )

  const documentSearchQuery = useQuery({
    queryKey: queryKeys.documents.list(documentSearchParams),
    queryFn: ({ signal }) => documentApi.list(documentSearchParams, { signal }),
    select: (response) => response.items,
    enabled: isTypedSearchActive && Boolean(debouncedSearchQuery),
    staleTime: 30_000,
  })

  const datasetSearchParams = React.useMemo(
    () => ({ q: debouncedSearchQuery, limit: COMMAND_MENU_ENTITY_SEARCH_LIMIT }),
    [debouncedSearchQuery],
  )
  const datasetSearchQuery = useQuery({
    queryKey: queryKeys.datasets.list(datasetSearchParams),
    queryFn: ({ signal }) => datasetApi.list(datasetSearchParams, { signal }),
    select: (response) => response.items,
    enabled: isTypedSearchActive && Boolean(debouncedSearchQuery),
    staleTime: 60_000,
  })

  const conversationSearchParams = React.useMemo(
    () => ({ q: debouncedSearchQuery, limit: COMMAND_MENU_ENTITY_SEARCH_LIMIT }),
    [debouncedSearchQuery],
  )
  const conversationSearchQuery = useQuery({
    queryKey: queryKeys.chat.conversations(conversationSearchParams),
    queryFn: ({ signal }) => chatApi.listConversations(conversationSearchParams, { signal }),
    select: (response) => response.items,
    enabled: isTypedSearchActive && Boolean(debouncedSearchQuery),
    staleTime: 30_000,
  })

  const docResults = debouncedSearchQuery ? (documentSearchQuery.data ?? []) : []
  const datasetResults = debouncedSearchQuery ? (datasetSearchQuery.data ?? []) : []
  const conversationResults = debouncedSearchQuery ? (conversationSearchQuery.data ?? []) : []
  const docLoading = isSearchDebouncing || (Boolean(debouncedSearchQuery) && documentSearchQuery.isFetching)
  const datasetLoading = isSearchDebouncing || (Boolean(debouncedSearchQuery) && datasetSearchQuery.isFetching)
  const conversationLoading =
    isSearchDebouncing || (Boolean(debouncedSearchQuery) && conversationSearchQuery.isFetching)

  const resumeLastDocumentContext = React.useCallback(() => {
    if (!hasResumeTarget) return
    reopenLastDocument()
    router.push('/')
  }, [hasResumeTarget, reopenLastDocument, router])

  const clearPendingChord = React.useCallback(() => {
    setPendingChordPrefix(null)
    if (chordTimerRef.current != null) {
      globalThis.window.clearTimeout(chordTimerRef.current)
      chordTimerRef.current = null
    }
  }, [])

  const armPendingChord = React.useCallback((prefix: string) => {
    setPendingChordPrefix(prefix)
    if (chordTimerRef.current != null) {
      globalThis.window.clearTimeout(chordTimerRef.current)
    }
    chordTimerRef.current = globalThis.window.setTimeout(() => {
      setPendingChordPrefix(null)
      chordTimerRef.current = null
    }, KEY_CHORD_TIMEOUT_MS)
  }, [])

  React.useEffect(() => {
    const closeForAuthScope = () => {
      setOpen(false)
      clearPendingChord()
    }
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, closeForAuthScope)
    return () => window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, closeForAuthScope)
  }, [clearPendingChord, setOpen])

  React.useEffect(() => {
    if (!open) {
      setQuery('')
      setShowShortcutHelp(false)
    }
  }, [open])

  React.useEffect(() => {
    if (!isTypedSearchActive) {
      setDebouncedSearchQuery('')
      return
    }

    const timeoutId = globalThis.window.setTimeout(() => {
      setDebouncedSearchQuery(trimmedQuery)
    }, COMMAND_MENU_SEARCH_DEBOUNCE_MS)

    return () => globalThis.window.clearTimeout(timeoutId)
  }, [isTypedSearchActive, trimmedQuery])

  const runCommand = React.useCallback(
    (command: () => void) => {
      setQuery('')
      setDebouncedSearchQuery('')
      setOpen(false)
      command()
    },
    [setOpen],
  )

  const keyChordCommands = React.useMemo<KeyChordCommand[]>(
    () =>
      (
        [
          {
            id: 'documents',
            key: 'g d',
            icon: FileText,
            visibilityKey: undefined,
            run: () => router.push('/knowledge'),
          },
          { id: 'chat', key: 'g c', icon: MessageSquare, visibilityKey: undefined, run: () => router.push('/') },
          {
            id: 'graph',
            key: 'g g',
            icon: KnowledgeGraph,
            visibilityKey: 'knowledgeGraph',
            run: () => router.push('/graph'),
          },
          {
            id: 'observability',
            key: 'g o',
            icon: Diagnostics,
            visibilityKey: undefined,
            run: () => router.push('/observability'),
          },
          { id: 'slice', key: 'f s', icon: Search, visibilityKey: undefined, run: () => router.push('/chunk-preview') },
          { id: 'resume', key: 'g v', icon: History, visibilityKey: undefined, run: resumeLastDocumentContext },
        ] as const
      )
        .filter(
          (command) =>
            canShowNavigationModule(command.visibilityKey) && (command.id !== 'observability' || canReadObservability),
        )
        .map(({ id, key, icon, visibilityKey, run }) => ({
          id,
          key,
          icon,
          visibilityKey,
          label: t(`keyChords.${id}.label`),
          description:
            id === 'resume' && !hasResumeTarget
              ? t('keyChords.resume.emptyDescription')
              : t(`keyChords.${id}.description`),
          run,
        })),
    [canReadObservability, canShowNavigationModule, hasResumeTarget, resumeLastDocumentContext, router, t],
  )

  const chordPrefixes = React.useMemo(
    () => new Set(keyChordCommands.map((command) => command.key.split(' ')[0])),
    [keyChordCommands],
  )

  const keyChordCommandMap = React.useMemo(
    () => new Map(keyChordCommands.map((command) => [command.key, command.run])),
    [keyChordCommands],
  )

  const shortcutGuideItems = React.useMemo<ShortcutGuideItem[]>(
    () => [
      {
        shortcut: '⌘K / Ctrl+K',
        label: t('shortcutGuide.open.label'),
        description: t('shortcutGuide.open.description'),
      },
      {
        shortcut: '?',
        label: t('shortcutGuide.help.label'),
        description: t('shortcutGuide.help.description'),
      },
      ...keyChordCommands.map((command) => ({
        shortcut: command.key,
        label: command.label,
        description: `${t('shortcutGuide.chordPrefix')} ${command.description}`,
      })),
      {
        shortcut: 'h / l',
        label: t('shortcutGuide.stagePrevNext.label'),
        description: t('shortcutGuide.stagePrevNext.description'),
      },
      {
        shortcut: '← / →',
        label: t('shortcutGuide.stageArrows.label'),
        description: t('shortcutGuide.stageArrows.description'),
      },
      {
        shortcut: 'j / k',
        label: t('shortcutGuide.sliceFocus.label'),
        description: t('shortcutGuide.sliceFocus.description'),
      },
    ],
    [keyChordCommands, t],
  )

  const slashCommands = React.useMemo<SlashCommand[]>(
    () =>
      (
        [
          { id: 'resume', shortcut: '/resume', icon: FileText, visibilityKey: undefined },
          { id: 'upload', shortcut: '/upload', icon: Upload, visibilityKey: undefined },
          { id: 'analyze', shortcut: '/analyze', icon: Sparkles, visibilityKey: undefined },
          { id: 'report', shortcut: '/report', icon: Reports, visibilityKey: undefined },
          { id: 'stats', shortcut: '/stats', icon: Coins, visibilityKey: undefined },
          { id: 'precheck', shortcut: '/precheck', icon: Workflow, visibilityKey: undefined },
          { id: 'datasets', shortcut: '/datasets', icon: DatasetIcon, visibilityKey: undefined },
          { id: 'history', shortcut: '/history', icon: History, visibilityKey: undefined },
          { id: 'graph', shortcut: '/graph', icon: KnowledgeGraph, visibilityKey: 'knowledgeGraph' },
          { id: 'diagnostics', shortcut: '/diagnostics', icon: Diagnostics, visibilityKey: undefined },
          { id: 'settings', shortcut: '/settings', icon: Settings, visibilityKey: undefined },
          { id: 'parsing', shortcut: '/parsing', icon: Parsing, visibilityKey: undefined },
          { id: 'reports', shortcut: '/reports', icon: Reports, visibilityKey: 'reports' },
          { id: 'observability', shortcut: '/observability', icon: Diagnostics, visibilityKey: undefined },
          { id: 'governance', shortcut: '/governance', icon: DataGovernance, visibilityKey: undefined },
        ] as const
      ).map(({ id, shortcut, icon, visibilityKey }) => ({
        id,
        visibilityKey,
        label: t(`slash.commands.${id}.label`),
        description:
          id === 'analyze'
            ? currentViewPrompt.description
            : id === 'resume' && !hasResumeTarget
              ? t('slash.commands.resume.emptyDescription')
              : t(`slash.commands.${id}.description`),
        shortcut,
        keywords: t.raw(`slash.commands.${id}.keywords`) as string[],
        icon,
        run: () => {
          if (id === 'resume') {
            resumeLastDocumentContext()
            return
          }

          if (id === 'analyze') {
            const params = new URLSearchParams({
              prompt: currentViewPrompt.prompt,
              autorun: '1',
            })
            router.push(`/?${params.toString()}`)
            return
          }

          if (id === 'report') {
            router.push('/datasets')
            return
          }

          if (id === 'upload') {
            router.push('/knowledge')
            return
          }

          if (id === 'stats') {
            router.push('/usage')
            return
          }

          if (id === 'precheck') {
            router.push('/datasets')
            return
          }

          if (id === 'datasets') {
            router.push('/datasets')
            return
          }

          if (id === 'history') {
            router.push('/history')
            return
          }

          if (id === 'graph') {
            router.push('/graph')
            return
          }

          if (id === 'diagnostics') {
            router.push('/diagnostics')
            return
          }

          if (id === 'settings') {
            router.push('/settings')
            return
          }

          if (id === 'parsing') {
            router.push('/parsing')
            return
          }

          if (id === 'reports') {
            router.push('/reports')
            return
          }

          if (id === 'observability') {
            router.push('/observability')
            return
          }

          if (id === 'governance') {
            router.push('/data-governance')
          }
        },
      })),
    [currentViewPrompt.description, currentViewPrompt.prompt, hasResumeTarget, resumeLastDocumentContext, router, t],
  )

  const viewerShortcutDocs = React.useMemo<ShortcutDocItem[]>(
    () =>
      (
        [
          { id: 'resume', key: 'g v' },
          { id: 'focusSearch', key: '/' },
          { id: 'cycleHits', key: 'j / k' },
          { id: 'find', key: 'Ctrl/Cmd+F' },
          { id: 'dismiss', key: 'Esc' },
        ] as const
      ).map(({ id, key }) => ({
        key,
        label: t(`viewerShortcuts.${id}.label`),
        description: t(`viewerShortcuts.${id}.description`),
      })),
    [t],
  )

  const filteredSlashCommands = React.useMemo(
    () =>
      slashCommands.filter((command) => {
        if (!canShowNavigationModule(command.visibilityKey)) return false
        if (command.id === 'settings' && !canReadSettings) return false
        if (command.id === 'stats' && !canReadUsage) return false
        if ((command.id === 'diagnostics' || command.id === 'observability') && !canReadObservability) return false
        if (!slashNeedle) return true
        const haystack = [command.shortcut, command.label, command.description, ...command.keywords]
          .join(' ')
          .toLowerCase()
        return haystack.includes(slashNeedle)
      }),
    [canReadObservability, canReadSettings, canReadUsage, canShowNavigationModule, slashCommands, slashNeedle],
  )

  const moduleWorkbenchItems = React.useMemo<ModuleWorkbenchItem[]>(
    () =>
      (
        [
          { id: 'knowledge', icon: Database, visibilityKey: undefined, run: () => router.push('/knowledge') },
          { id: 'graph', icon: KnowledgeGraph, visibilityKey: 'knowledgeGraph', run: () => router.push('/graph') },
          { id: 'ontology', icon: Network, visibilityKey: undefined, run: () => router.push('/ontology') },
          { id: 'slices', icon: Chunking, visibilityKey: undefined, run: () => router.push('/chunk-preview') },
          { id: 'parsing', icon: Parsing, visibilityKey: undefined, run: () => router.push('/parsing') },
          { id: 'reports', icon: Reports, visibilityKey: 'reports', run: () => router.push('/reports') },
          {
            id: 'observability',
            icon: Diagnostics,
            visibilityKey: undefined,
            run: () => router.push('/observability'),
          },
          {
            id: 'governance',
            icon: DataGovernance,
            visibilityKey: undefined,
            run: () => router.push('/data-governance'),
          },
        ] as const
      )
        .filter(
          (item) =>
            canShowNavigationModule(item.visibilityKey) && (item.id !== 'observability' || canReadObservability),
        )
        .map(({ id, icon, visibilityKey, run }) => ({
          id,
          visibilityKey,
          label: t(`modules.${id}.label`),
          description: t(`modules.${id}.description`),
          keywords: t.raw(`modules.${id}.keywords`) as string[],
          icon,
          run,
        })),
    [canReadObservability, canShowNavigationModule, router, t],
  )

  const moduleWorkbenchResults = React.useMemo(() => {
    if (isSlashMode) return []
    const needle = query.trim().toLowerCase()
    if (needle.length < 2) return []

    return moduleWorkbenchItems.filter((item) =>
      matchesSearchNeedle([item.label, item.description, item.keywords.join(' ')], needle),
    )
  }, [isSlashMode, moduleWorkbenchItems, query])

  const navigationItems = React.useMemo(
    () => [
      { icon: Home, label: t('navigation.home'), run: () => router.push('/') },
      { icon: MessageSquare, label: t('navigation.newConversation'), run: () => router.push('/') },
      { icon: Database, label: t('navigation.knowledge'), run: () => router.push('/knowledge') },
      { icon: Parsing, label: t('navigation.parsing'), run: () => router.push('/parsing') },
      { icon: History, label: t('navigation.history'), run: () => router.push('/history') },
      ...(canReadSettings
        ? [{ icon: Settings, label: t('navigation.settings'), run: () => router.push('/settings') }]
        : []),
    ],
    [canReadSettings, router, t],
  )

  const actionItems = React.useMemo(
    () => [
      { icon: Upload, label: t('actions.uploadDocument'), run: () => router.push('/knowledge') },
      { icon: Settings, label: t('actions.ragSettings'), run: () => router.push('/?rag=1') },
    ],
    [router, t],
  )

  const themeItems = React.useMemo(
    () => [
      { icon: Sun, label: t('theme.light'), run: () => setTheme('light') },
      { icon: Moon, label: t('theme.dark'), run: () => setTheme('dark') },
      { icon: Laptop, label: t('theme.system'), run: () => setTheme('system') },
    ],
    [setTheme, t],
  )

  // Only actions represented by the current rows may execute.
  const commandActions = new Map<string, CommandAction>()
  if (isSlashMode) {
    for (const command of filteredSlashCommands) {
      commandActions.set(`slash:${command.id}`, {
        disabled: command.id === 'resume' && !hasResumeTarget,
        run: command.run,
      })
    }
  }
  if (showBaseCommandGroups) {
    for (const command of keyChordCommands) {
      commandActions.set(`workflow:${command.id}`, {
        disabled: command.id === 'resume' && !hasResumeTarget,
        run: command.run,
      })
    }
    for (const item of navigationItems) {
      commandActions.set(`navigation:${item.label}`, item)
    }
    for (const item of actionItems) {
      commandActions.set(`action:${item.label}`, item)
    }
    for (const item of themeItems) {
      commandActions.set(`theme:${item.label}`, item)
    }
  }
  if (hasTypedSearchQuery) {
    commandActions.set(`ai ${trimmedQuery}`, {
      run: () => {
        const params = new URLSearchParams({ prompt: trimmedQuery, autorun: '1' })
        router.push(`/?${params.toString()}`)
      },
    })
    for (const item of moduleWorkbenchResults) {
      commandActions.set(`module:${item.id}`, item)
    }
    if (!docLoading) {
      for (const doc of docResults) {
        commandActions.set(`document:${doc.id}`, {
          run: () => {
            openDocument(doc.id)
            router.push('/')
          },
        })
      }
    }
    if (!datasetLoading) {
      for (const dataset of datasetResults) {
        commandActions.set(`dataset:${dataset.id}`, {
          run: () => router.push(`/datasets/${dataset.id}/profile`),
        })
      }
    }
    if (!conversationLoading) {
      for (const conversation of conversationResults) {
        commandActions.set(`conversation:${conversation.id}`, {
          run: () => router.push(`/history?id=${conversation.id}`),
        })
      }
    }
  }

  const executeAction = (value: string) => {
    const action = commandActions.get(value)
    if (action && !action.disabled) runCommand(action.run)
  }

  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.repeat || e.defaultPrevented || e.isComposing) return
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        toggleOpen()
        clearPendingChord()
        return
      }

      if (e.key === '?' && !e.metaKey && !e.ctrlKey && !e.altKey && !isEditableTarget(e.target)) {
        e.preventDefault()
        setShowShortcutHelp(true)
        setOpen(true)
        clearPendingChord()
        return
      }

      if (open || e.metaKey || e.ctrlKey || e.altKey) return
      if (isEditableTarget(e.target)) return

      const key = normalizeChordKey(e.key)
      if (key.length !== 1) {
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

    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [
    armPendingChord,
    chordPrefixes,
    clearPendingChord,
    keyChordCommandMap,
    open,
    pendingChordPrefix,
    setOpen,
    toggleOpen,
  ])

  React.useEffect(() => {
    if (open) clearPendingChord()
  }, [clearPendingChord, open])

  React.useEffect(
    () => () => {
      if (chordTimerRef.current != null) {
        globalThis.window.clearTimeout(chordTimerRef.current)
      }
    },
    [],
  )

  return (
    <CommandDialog
      id="mimirq-command-menu"
      open={open}
      onOpenChange={setOpen}
      shouldFilter={!hasTypedSearchQuery && !isSlashMode && !isShortcutHelpQuery}
    >
      <div className="relative shrink-0">
        <CommandInput
          className="h-13 pr-16 text-sm"
          aria-label={t('search.label')}
          maxLength={COMMAND_MENU_SEARCH_MAX_LENGTH}
          placeholder={t('search.placeholder')}
          value={query}
          onValueChange={setQuery}
        />
        <Button
          type="button"
          variant="ghost"
          className="absolute right-3 top-1/2 h-11 -translate-y-1/2 rounded border border-border bg-muted/40 px-1.5 font-mono text-[10px] font-normal text-muted-foreground sm:h-7"
          aria-label={t('keyboard.close')}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') event.stopPropagation()
          }}
          onClick={() => setOpen(false)}
        >
          Esc
        </Button>
      </div>
      <CommandList className="min-h-0 flex-1 p-2">
        <CommandEmpty>{t('search.empty')}</CommandEmpty>

        {isSlashMode ? (
          <>
            <CommandGroup heading={t('groups.slash')}>
              {filteredSlashCommands.map((command) => {
                const Icon = command.icon
                return (
                  <CommandItem
                    key={command.id}
                    value={`slash:${command.id}`}
                    keywords={[command.shortcut, command.label, command.description, ...command.keywords]}
                    disabled={command.id === 'resume' && !hasResumeTarget}
                    onSelect={() => executeAction(`slash:${command.id}`)}
                  >
                    <Icon className="size-4" aria-hidden="true" />
                    <CommandRowText label={command.label} description={command.description} />
                    <CommandShortcut className="shrink-0 self-start rounded-none border-0 bg-transparent px-0 text-xs font-normal leading-[22px]">
                      {command.shortcut}
                    </CommandShortcut>
                  </CommandItem>
                )
              })}
            </CommandGroup>
            <CommandSeparator />
          </>
        ) : null}

        {showBaseCommandGroups ? (
          <>
            <CommandGroup data-command-workflow-group="true" heading={t('groups.keyboardWorkflow')}>
              {keyChordCommands.map((command) => {
                const Icon = command.icon
                return (
                  <CommandItem
                    key={command.key}
                    value={`workflow:${command.id}`}
                    keywords={[command.label, command.description, command.key]}
                    disabled={command.id === 'resume' && !hasResumeTarget}
                    onSelect={() => executeAction(`workflow:${command.id}`)}
                  >
                    <Icon className="size-4" aria-hidden="true" />
                    <CommandRowText label={command.label} description={command.description} />
                    <CommandKeySequence sequence={command.key} />
                  </CommandItem>
                )
              })}
            </CommandGroup>

            <CommandSeparator />

            {shouldShowShortcutReference ? (
              <div id="command-shortcut-reference">
                <CommandGroup heading={t('groups.viewerShortcuts')}>
                  {viewerShortcutDocs.map((shortcut) => (
                    <CommandItem
                      key={shortcut.key}
                      value={`viewer-shortcut ${shortcut.key} ${shortcut.label}`}
                      disabled
                    >
                      <FileText className="mr-2 size-4" />
                      <CommandShortcutHelp
                        label={shortcut.label}
                        description={shortcut.description}
                        shortcut={shortcut.key}
                      />
                    </CommandItem>
                  ))}
                </CommandGroup>

                <CommandSeparator />

                <CommandGroup heading={t('groups.shortcutMap')}>
                  {shortcutGuideItems.map((item) => (
                    <CommandItem
                      key={`${item.shortcut}:${item.label}`}
                      disabled
                      value={`${item.shortcut} ${item.label}`}
                    >
                      <Keyboard className="mr-2 size-4" />
                      <CommandShortcutHelp label={item.label} description={item.description} shortcut={item.shortcut} />
                    </CommandItem>
                  ))}
                </CommandGroup>

                <CommandSeparator />
              </div>
            ) : null}

            <CommandGroup heading={t('groups.navigation')}>
              {navigationItems.map((item) => (
                <CommandItem
                  key={item.label}
                  value={`navigation:${item.label}`}
                  keywords={[item.label]}
                  onSelect={() => executeAction(`navigation:${item.label}`)}
                >
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
            <CommandGroup heading={t('groups.aiActions')}>
              <CommandItem
                value={`ai ${trimmedQuery}`}
                keywords={[trimmedQuery, t('aiAction.label')]}
                onSelect={() => executeAction(`ai ${trimmedQuery}`)}
              >
                <MessageSquare className="size-4" aria-hidden="true" />
                <CommandRowText label={t('aiAction.label')} description={trimmedQuery} />
              </CommandItem>
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.modules')}>
              {moduleWorkbenchResults.length ? (
                moduleWorkbenchResults.map((item) => {
                  const Icon = item.icon
                  return (
                    <CommandItem
                      key={item.id}
                      value={`module:${item.id}`}
                      keywords={[item.label, item.description, ...item.keywords]}
                      onSelect={() => executeAction(`module:${item.id}`)}
                    >
                      <Icon className="mr-2 size-4" />
                      <CommandRowText label={item.label} description={item.description} />
                    </CommandItem>
                  )
                })
              ) : (
                <CommandItem disabled value="workbench:empty">
                  <Workflow className="mr-2 size-4" />
                  <span>{t('results.modulesEmpty')}</span>
                </CommandItem>
              )}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.documents')}>
              {!isSearchDebouncing && documentSearchQuery.error ? (
                <CommandItem disabled value="doc:error">
                  <span role="alert">{formatApiError(documentSearchQuery.error, t('results.documentsError'))}</span>
                </CommandItem>
              ) : null}
              {docLoading ? (
                <CommandItem disabled value="doc:loading">
                  <FileText className="mr-2 size-4" />
                  <span>{t('results.documentsLoading')}</span>
                </CommandItem>
              ) : docResults.length ? (
                docResults.map((doc) => (
                  <CommandItem
                    key={doc.id}
                    value={`document:${doc.id}`}
                    keywords={[doc.filename]}
                    onSelect={() => executeAction(`document:${doc.id}`)}
                  >
                    <FileTypeIcon type={doc.file_type} filename={doc.filename} className="mr-2 size-4" />
                    <span className="truncate">{doc.filename}</span>
                  </CommandItem>
                ))
              ) : !documentSearchQuery.error ? (
                <CommandItem disabled value="doc:empty">
                  <FileText className="mr-2 size-4" />
                  <span>{t('results.documentsEmpty')}</span>
                </CommandItem>
              ) : null}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.datasets')}>
              {!isSearchDebouncing && datasetSearchQuery.error ? (
                <CommandItem disabled value="dataset:error">
                  <span role="alert">{formatApiError(datasetSearchQuery.error, t('results.datasetsError'))}</span>
                </CommandItem>
              ) : null}
              {datasetLoading ? (
                <CommandItem disabled value="dataset:loading">
                  <Database className="mr-2 size-4" />
                  <span>{t('results.datasetsLoading')}</span>
                </CommandItem>
              ) : datasetResults.length ? (
                datasetResults.map((dataset) => (
                  <CommandItem
                    key={dataset.id}
                    value={`dataset:${dataset.id}`}
                    keywords={dataset.description ? [dataset.name, dataset.description] : [dataset.name]}
                    onSelect={() => executeAction(`dataset:${dataset.id}`)}
                  >
                    <Database className="mr-2 size-4" />
                    <CommandRowText
                      label={dataset.name}
                      description={dataset.description === null ? undefined : dataset.description}
                    />
                  </CommandItem>
                ))
              ) : !datasetSearchQuery.error ? (
                <CommandItem disabled value="dataset:empty">
                  <Database className="mr-2 size-4" />
                  <span>{t('results.datasetsEmpty')}</span>
                </CommandItem>
              ) : null}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.conversations')}>
              {!isSearchDebouncing && conversationSearchQuery.error ? (
                <CommandItem disabled value="conversation:error">
                  <span role="alert">
                    {formatApiError(conversationSearchQuery.error, t('results.conversationsError'))}
                  </span>
                </CommandItem>
              ) : null}
              {conversationLoading ? (
                <CommandItem disabled value="conversation:loading">
                  <MessageSquare className="mr-2 size-4" />
                  <span>{t('results.conversationsLoading')}</span>
                </CommandItem>
              ) : conversationResults.length ? (
                conversationResults.map((conversation) => (
                  <CommandItem
                    key={conversation.id}
                    value={`conversation:${conversation.id}`}
                    keywords={[conversation.title, conversation.last_message].filter(
                      (value): value is string => typeof value === 'string',
                    )}
                    onSelect={() => executeAction(`conversation:${conversation.id}`)}
                  >
                    <MessageSquare className="mr-2 size-4" />
                    <CommandRowText
                      label={
                        conversation.title === null ||
                        conversation.title === undefined ||
                        conversation.title.trim() === ''
                          ? t('results.untitledConversation')
                          : conversation.title
                      }
                      description={conversation.last_message === null ? undefined : conversation.last_message}
                    />
                  </CommandItem>
                ))
              ) : !conversationSearchQuery.error ? (
                <CommandItem disabled value="conversation:empty">
                  <MessageSquare className="mr-2 size-4" />
                  <span>{t('results.conversationsEmpty')}</span>
                </CommandItem>
              ) : null}
            </CommandGroup>

            <CommandSeparator />
          </>
        ) : null}

        {showBaseCommandGroups ? (
          <>
            <CommandGroup heading={t('groups.actions')}>
              {actionItems.map((item) => (
                <CommandItem
                  key={item.label}
                  value={`action:${item.label}`}
                  keywords={[item.label]}
                  onSelect={() => executeAction(`action:${item.label}`)}
                >
                  <item.icon className="mr-2 size-4" />
                  <span>{item.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>

            <CommandSeparator />

            <CommandGroup heading={t('groups.theme')}>
              {themeItems.map((item) => (
                <CommandItem
                  key={item.label}
                  value={`theme:${item.label}`}
                  keywords={[item.label]}
                  onSelect={() => executeAction(`theme:${item.label}`)}
                >
                  <item.icon className="mr-2 size-4" />
                  <span>{item.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        ) : null}
      </CommandList>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border/60 bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <kbd className="font-mono">↑ ↓</kbd>
            {t('keyboard.navigate')}
          </span>
          <span className="inline-flex items-center gap-1">
            <CornerDownLeft className="size-3" aria-hidden="true" />
            {t('keyboard.execute')}
          </span>
        </span>
        {trimmedQuery === '' ? (
          <Button
            type="button"
            variant="ghost"
            className="h-11 gap-1.5 px-1 text-[11px] font-normal text-muted-foreground sm:h-8"
            aria-expanded={showShortcutHelp}
            aria-controls="command-shortcut-reference"
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') event.stopPropagation()
            }}
            onClick={() => setShowShortcutHelp((shown) => !shown)}
          >
            <Keyboard className="size-3" aria-hidden="true" />
            {t('keyboard.help')}
          </Button>
        ) : (
          <span>{t('keyboard.helpHint')}</span>
        )}
      </div>
    </CommandDialog>
  )
}
