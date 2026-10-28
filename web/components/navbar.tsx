/**
 * 左侧固定导航栏组件
 */
'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useLinkStatus } from 'next/link'
import { Portal as TooltipPortal } from '@radix-ui/react-tooltip'
import {
  AuditLog,
  Chunking,
  Conversation,
  ConversationHistory,
  DataGovernance,
  Dataset,
  Diagnostics,
  Evaluation,
  Feedback,
  Groups,
  Ingestion,
  KnowledgeBase,
  KnowledgeGraph,
  Members,
  Parsing,
  Prompts,
  Quarantine,
  Reports,
  RuleSet,
  Usage,
  ChevronDown,
  ChevronRight,
  LogIn,
  LogOut,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Palette,
  Plus,
  Search,
  Settings,
  User,
} from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Link, usePathname, useRouter } from '@/i18n/navigation'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { BrandLogo } from '@/components/brand-logo'
import { BRAND_NAME } from '@/lib/brand'
import { SURFACE_THEMES } from '@/lib/theme-surface'
import { cn } from '@/lib/utils'
import { ModeToggle } from '@/components/mode-toggle'
import { ThemeCustomizer } from '@/components/theme-customizer'
import { useAuth } from '@/hooks/use-auth'
import { useBackendMetaDetails } from '@/hooks/use-backend-meta'
import { useBackendReady } from '@/hooks/use-backend-ready'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { useCommandMenuState } from '@/store/command-menu'
import { TENANT_PERMISSIONS, tenantAccessAllows, type TenantPermission } from '@/lib/tenant-permissions'
import { canShowAdminControlledNavigationModule, type AdminControlledNavigationModule } from '@/lib/navigation-visibility'

type SectionId = 'core' | 'ingestion' | 'knowledge' | 'analysis' | 'system'

type MenuItem = {
  icon: React.ComponentType<{ className?: string }>
  labelKey: string
  href: string
  requiredPermission?: TenantPermission
  visibilityKey?: AdminControlledNavigationModule
}

type MenuSection = {
  id: SectionId
  titleKey: string
  items: MenuItem[]
}

// 导航信息架构：按「核心 → 入库流程 → 知识库管理 → 分析工具 → 系统」分组，降低认知负担。
const menuSections: MenuSection[] = [
  {
    id: 'core',
    titleKey: 'sections.core',
    items: [
      { icon: Conversation, labelKey: 'items.conversation', href: '/' },
      { icon: ConversationHistory, labelKey: 'items.history', href: '/history' },
    ],
  },
  {
    id: 'knowledge',
    titleKey: 'sections.knowledge',
    items: [
      { icon: Dataset, labelKey: 'items.datasets', href: '/datasets' },
      { icon: KnowledgeBase, labelKey: 'items.knowledgeBase', href: '/knowledge' },
      { icon: Quarantine, labelKey: 'items.quarantine', href: '/knowledge/quarantine' },
      { icon: Feedback, labelKey: 'items.feedback', href: '/knowledge/feedback' },
    ],
  },
  {
    id: 'ingestion',
    titleKey: 'sections.ingestion',
    items: [
      { icon: Ingestion, labelKey: 'items.ingestion', href: '/knowledge/ingestion' },
      { icon: Parsing, labelKey: 'items.parsing', href: '/parsing' },
      { icon: DataGovernance, labelKey: 'items.dataGovernance', href: '/data-governance' },
      { icon: RuleSet, labelKey: 'items.governanceProfiles', href: '/data-governance/profiles', visibilityKey: 'governanceProfiles' },
      { icon: Chunking, labelKey: 'items.chunkPreview', href: '/chunk-preview' },
    ],
  },
  {
    id: 'analysis',
    titleKey: 'sections.analysis',
    items: [
      { icon: KnowledgeGraph, labelKey: 'items.knowledgeGraph', href: '/graph', visibilityKey: 'knowledgeGraph' },
      { icon: Evaluation, labelKey: 'items.ragas', href: '/evaluations', visibilityKey: 'ragas' },
      { icon: Reports, labelKey: 'items.reports', href: '/reports', visibilityKey: 'reports' },
      { icon: Prompts, labelKey: 'items.prompts', href: '/prompts', visibilityKey: 'prompts' },
    ],
  },
  {
    id: 'system',
    titleKey: 'sections.system',
    items: [
      { icon: Diagnostics, labelKey: 'items.diagnostics', href: '/diagnostics', requiredPermission: TENANT_PERMISSIONS.OBSERVABILITY_READ },
      { icon: Usage, labelKey: 'items.usage', href: '/usage', requiredPermission: TENANT_PERMISSIONS.USAGE_READ },
      { icon: AuditLog, labelKey: 'items.audit', href: '/audit', requiredPermission: TENANT_PERMISSIONS.AUDIT_READ },
      { icon: Members, labelKey: 'items.members', href: '/settings/rbac', requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ },
      { icon: Groups, labelKey: 'items.groups', href: '/settings/groups', requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ },
      { icon: Settings, labelKey: 'items.settings', href: '/settings', requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ },
    ],
  },
]

const DEFAULT_OPEN_SECTIONS = new Set<SectionId>(['core', 'knowledge', 'ingestion', 'analysis'])
const OPEN_SECTIONS_STORAGE_KEY = 'mimirq_navbar_open_sections_v2'
const NAVIGATION_PARENT_ROUTES: Record<string, string> = {
  '/knowledge/similarity': '/evaluations',
}

function isActiveRoute(pathname: string, href: string) {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(`${href}/`)
}

function getMostSpecificActiveHref(pathname: string, items: MenuItem[]): string | null {
  let activeHref: string | null = null

  for (const item of items) {
    if (!isActiveRoute(pathname, item.href)) continue
    if (activeHref === null || item.href.length > activeHref.length) {
      activeHref = item.href
    }
  }

  return activeHref
}

function sectionHasActiveRoute(activeHref: string | null, items: MenuItem[]) {
  if (!activeHref) return false
  return items.some((item) => item.href === activeHref)
}

function trimmedPrimitiveString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') return String(value).trim()
  return ''
}

function formatDepStatus(status: unknown): { label: string; className: string } {
  const label = trimmedPrimitiveString(status) || 'unknown'
  const lower = label.toLowerCase()
  if (lower === 'connected' || lower === 'ready') {
    return { label, className: 'text-success' }
  }
  if (lower === 'disabled' || lower === 'not_configured' || lower === 'unknown') {
    return { label, className: 'text-muted-foreground' }
  }
  return { label, className: 'text-destructive' }
}

function createInitialOpenSections(): Record<SectionId, boolean> {
  return menuSections.reduce<Record<SectionId, boolean>>(
    (sections, section) => {
      sections[section.id] = DEFAULT_OPEN_SECTIONS.has(section.id)
      return sections
    },
    {
      core: false,
      ingestion: false,
      knowledge: false,
      analysis: false,
      system: false,
    }
  )
}

function sanitizeOpenSections(value: unknown): Record<SectionId, boolean> {
  const fallback = createInitialOpenSections()
  if (!value || typeof value !== 'object') return fallback

  const candidate = value as Partial<Record<SectionId, unknown>>
  return {
    core: typeof candidate.core === 'boolean' ? candidate.core : fallback.core,
    ingestion: typeof candidate.ingestion === 'boolean' ? candidate.ingestion : fallback.ingestion,
    knowledge: typeof candidate.knowledge === 'boolean' ? candidate.knowledge : fallback.knowledge,
    analysis: typeof candidate.analysis === 'boolean' ? candidate.analysis : fallback.analysis,
    system: typeof candidate.system === 'boolean' ? candidate.system : fallback.system,
  }
}

function loadOpenSections(): Record<SectionId, boolean> {
  if (globalThis.window === undefined) return createInitialOpenSections()

  try {
    const raw = readClientStorage(OPEN_SECTIONS_STORAGE_KEY)
    if (!raw) return createInitialOpenSections()
    return sanitizeOpenSections(JSON.parse(raw))
  } catch {
    return createInitialOpenSections()
  }
}

function RailNavigationIcon({ Icon, label }: Readonly<{ Icon: MenuItem['icon']; label: string }>) {
  const { pending } = useLinkStatus()
  const t = useTranslations('Navbar')

  return (
    <>
      {pending ? (
        <Loader2 className="size-[18px] animate-spin motion-reduce:animate-none" aria-hidden="true" />
      ) : <Icon className="size-[18px]" />}
      {pending ? <span role="status" className="sr-only">{t('toolbar.opening', { label })}</span> : null}
    </>
  )
}

export function Navbar({
  isSidebarOpen: externalIsOpen,
  setSidebarOpen: externalSetOpen,
  variant = 'default',
}: Readonly<{
  isSidebarOpen?: boolean
  setSidebarOpen?: (isOpen: boolean) => void
  variant?: 'default' | 'rail'
}> = {}) {
  const navRef = useRef<HTMLElement | null>(null)
  const toggleButtonRef = useRef<HTMLButtonElement | null>(null)
  const firstActionRef = useRef<HTMLButtonElement | null>(null)
  const prevIsSidebarOpenRef = useRef<boolean | null>(null)
  const restoreToggleFocusOnCloseRef = useRef(false)
  const [internalIsOpen, setInternalIsOpen] = useState(true)
  const [openSections, setOpenSections] = useState<Record<SectionId, boolean>>(createInitialOpenSections)
  const [hasHydratedOpenSections, setHasHydratedOpenSections] = useState(false)
  const [hasHydratedNavigationAccess, setHasHydratedNavigationAccess] = useState(false)
  const isSidebarOpen = externalIsOpen ?? internalIsOpen
  const setSidebarOpen = externalSetOpen ?? setInternalIsOpen
  const pathname = usePathname()
  const router = useRouter()
  const { user, isAuthenticated, isDevMode, logout } = useAuth()
  const t = useTranslations('Navbar')
  const { data: backendMeta } = useBackendMetaDetails()
  const backendReady = useBackendReady()
  const tenantAccess = useTenantAccess()
  const navigationTenantAccess = hasHydratedNavigationAccess ? tenantAccess.data : undefined
  const allowDevNavigation = hasHydratedNavigationAccess && isDevMode
  const commandMenuOpen = useCommandMenuState((state) => state.open)
  const setCommandMenuOpen = useCommandMenuState((state) => state.setOpen)
  const canAccessPermission = useCallback(
    (permission?: TenantPermission) =>
      !permission || allowDevNavigation || tenantAccessAllows(navigationTenantAccess, permission),
    [allowDevNavigation, navigationTenantAccess]
  )
  const canShowNavigationModule = useCallback(
    (moduleKey?: AdminControlledNavigationModule) =>
      !moduleKey || allowDevNavigation || canShowAdminControlledNavigationModule(navigationTenantAccess, moduleKey),
    [allowDevNavigation, navigationTenantAccess]
  )
  const visibleMenuSections = useMemo(
    () =>
      menuSections
        .map((section) => ({
          ...section,
          items: section.items.filter(
            (item) => canAccessPermission(item.requiredPermission) && canShowNavigationModule(item.visibilityKey)
          ),
        }))
        .filter((section) => section.items.length > 0),
    [canAccessPermission, canShowNavigationModule]
  )
  const visibleMenuItems = useMemo(() => visibleMenuSections.flatMap((section) => section.items), [visibleMenuSections])
  const activePathname = NAVIGATION_PARENT_ROUTES[pathname] || pathname
  const activeHref = getMostSpecificActiveHref(activePathname, visibleMenuItems)
  const readyDetails = backendReady.data ?? null
  const backendOk =
    (() => {
    if (typeof readyDetails?.ok === 'boolean') {
        return readyDetails.ok;
    }
    else if (backendReady.isError) {
            return false;
        }
        else {
            return null;
        }
})()
  const lastReadyAt = Math.max(backendReady.dataUpdatedAt || 0, backendReady.errorUpdatedAt || 0) || null
  const closeSidebarOnMobile = useCallback(() => {
    if (globalThis.window === undefined) return
    try {
      if (globalThis.window.matchMedia('(max-width: 768px)').matches) setSidebarOpen(false)
    } catch {
      // ignore
    }
  }, [setSidebarOpen])
  const toggleSection = useCallback((sectionId: SectionId) => {
    setOpenSections((current) => ({
      ...current,
      [sectionId]: !current[sectionId],
    }))
  }, [])
  const handleSidebarTogglePointerDown = useCallback(() => {
    restoreToggleFocusOnCloseRef.current = false
  }, [])
  const handleSidebarToggleKeyDown = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      restoreToggleFocusOnCloseRef.current = true
    }
  }, [])
  const handleSidebarToggle = useCallback(() => {
    if (isSidebarOpen) {
      restoreToggleFocusOnCloseRef.current =
        restoreToggleFocusOnCloseRef.current || document.activeElement === toggleButtonRef.current
    } else {
      restoreToggleFocusOnCloseRef.current = false
    }
    setSidebarOpen(!isSidebarOpen)
  }, [isSidebarOpen, setSidebarOpen])

  // Accessibility: prevent focus from entering the sidebar when collapsed/hidden.
  useEffect(() => {
    const el = navRef.current as (HTMLElement & { inert: boolean }) | null
    if (!el) return
    const inertNow = !isSidebarOpen
    try {
      el.inert = inertNow
    } catch {
      // ignore: inert is not supported in all environments
    }
  }, [isSidebarOpen])

  // Accessibility: close the mobile overlay with Escape.
  useEffect(() => {
    if (!isSidebarOpen) return
    if (globalThis.window === undefined) return

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return
      if (e.key !== 'Escape') return
      try {
        // Only treat as an overlay on small screens.
        if (!globalThis.window.matchMedia('(max-width: 768px)').matches) return
      } catch {
        return
      }
      e.preventDefault()
      restoreToggleFocusOnCloseRef.current = true
      setSidebarOpen(false)
    }

    globalThis.window.addEventListener('keydown', onKeyDown)
    return () => globalThis.window.removeEventListener('keydown', onKeyDown)
  }, [isSidebarOpen, setSidebarOpen])

  // Accessibility: restore focus to the toggle on close; move focus into the sidebar on open.
  useEffect(() => {
    if (globalThis.window === undefined) return
    if (prevIsSidebarOpenRef.current === null) {
      prevIsSidebarOpenRef.current = isSidebarOpen
      return
    }

    const prev = prevIsSidebarOpenRef.current
    prevIsSidebarOpenRef.current = isSidebarOpen
    if (prev === isSidebarOpen) return

    const active = document.activeElement
    if (isSidebarOpen) {
      // Only move focus when the user opened the sidebar from the toggle (keyboard).
      if (active && toggleButtonRef.current && active !== toggleButtonRef.current) return
      requestAnimationFrame(() => {
        firstActionRef.current?.focus()
      })
      return
    }

    const navEl = navRef.current
    const shouldRestore =
      !active || active === document.body || Boolean(navEl && active instanceof Node && navEl.contains(active))
    const shouldRestoreToggleFocus = restoreToggleFocusOnCloseRef.current
    restoreToggleFocusOnCloseRef.current = false
    if (!shouldRestore || !shouldRestoreToggleFocus) return

    requestAnimationFrame(() => {
      toggleButtonRef.current?.focus()
    })
  }, [isSidebarOpen])

  useEffect(() => {
    setOpenSections(loadOpenSections())
    setHasHydratedOpenSections(true)
    // Keep SSR and the first client render structurally identical. Tenant access can
    // be cached on the client, so applying it before mount can reorder/insert links.
    setHasHydratedNavigationAccess(true)
  }, [])

  useEffect(() => {
    const activeSection = visibleMenuSections.find((section) => sectionHasActiveRoute(activeHref, section.items))
    if (!activeSection) return

    setOpenSections((current) => {
      if (current[activeSection.id]) return current
      return {
        ...current,
        [activeSection.id]: true,
      }
    })
  }, [activeHref, visibleMenuSections])

  useEffect(() => {
    if (!hasHydratedOpenSections) return
    if (globalThis.window === undefined) return
    writeClientStorage(OPEN_SECTIONS_STORAGE_KEY, JSON.stringify(openSections))
  }, [hasHydratedOpenSections, openSections])

  // Dev UX: warm up route chunks in the background so first-click navigation feels snappier.
  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return
    if (globalThis.window === undefined) return
    if (globalThis.navigator?.webdriver) return
    const key = '__mimirq_routes_prefetched__'
    const routeCache = globalThis.window as typeof globalThis.window & Record<string, boolean>
    if (routeCache[key]) return
    routeCache[key] = true

    const hrefs = visibleMenuItems.map((i) => i.href).filter(Boolean)
    const prefetchAll = () => {
      for (const href of hrefs) {
        if (href === pathname) continue
        try {
          router.prefetch(href)
        } catch {
          // ignore
        }
      }
    }

    // Prefer idle time to avoid blocking initial render.
    const w = globalThis.window as Window & {
      requestIdleCallback?: (
        callback: (deadline: { didTimeout: boolean; timeRemaining: () => number }) => void,
        options?: { timeout?: number }
      ) => number
      cancelIdleCallback?: (id: number) => void
    }
    if (typeof w.requestIdleCallback === 'function') {
      const id = w.requestIdleCallback(prefetchAll, { timeout: 2000 })
      return () => w.cancelIdleCallback?.(id)
    }

    const t = setTimeout(prefetchAll, 800)
    return () => clearTimeout(t)
  }, [router, pathname, visibleMenuItems])

  const authMode = String(backendMeta?.features?.auth_mode || '')
  const vectorBackend = String(
    backendMeta?.features?.vector_backend || readyDetails?.vector?.backend || ''
  )
  const buildSha = String(backendMeta?.build?.sha || '')
  const buildShaShort = buildSha ? buildSha.slice(0, 8) : ''
  const checkedAtLabel = lastReadyAt ? new Date(lastReadyAt).toLocaleTimeString() : '—'

  const depRows: Array<{ key: string; status: unknown; note?: string; error?: unknown }> = readyDetails
    ? [
        {
          key: 'DB',
          status: readyDetails.database?.status,
          error: readyDetails.database?.error,
        },
        {
          key: `Vector (${String(readyDetails.vector?.backend || vectorBackend || '-')})`,
          status: readyDetails.vector?.status,
          error: readyDetails.vector?.error,
        },
        {
          key: 'Redis',
          status: readyDetails.redis?.status,
          note: (() => {
            const r = readyDetails.redis
            if (!r) return undefined
            if (!r.enabled) return 'disabled'
            const required = Boolean(r.required)
            const cache = Boolean(r.embedding_cache_enabled)
            return `${required ? 'required' : 'optional'}${cache ? ', cache' : ''}`
          })(),
          error: readyDetails.redis?.error,
        },
        {
          key: 'MinIO',
          status: readyDetails.minio?.status,
          note: (() => {
            const m = readyDetails.minio
            if (!m) return undefined
            if (!m.enabled) return 'disabled'
            return m.bucket ? `bucket: ${m.bucket}` : undefined
          })(),
          error: readyDetails.minio?.error,
        },
      ]
    : []

  const userDisplayName =
    user?.username || user?.email || (isDevMode ? t('user.developerMode') : t('user.unauthenticatedName'))
  const userInitial = Array.from(user?.username?.trim() || user?.email?.trim() || '')[0]?.toLocaleUpperCase()
  const userStatusLine = isAuthenticated ? user?.email || t('user.onlineStatus') : t('user.offlineEnvironment')
  const canOpenDiagnostics = canAccessPermission(TENANT_PERMISSIONS.OBSERVABILITY_READ)

  if (variant === 'rail') {
    return (
      <TooltipProvider delayDuration={250}>
        <nav aria-label={t('toolbar.navLabel')} className="flex h-full w-16 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
          <Link href="/" aria-label={BRAND_NAME} className="mx-auto mt-6 mb-6 block rounded-md focus-ring">
            <BrandLogo variant="mark" className="size-8" decorative priority />
          </Link>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain no-scrollbar">
            {visibleMenuItems.filter((item) => item.href !== '/settings').map((item) => {
              const Icon = item.icon
              const active = item.href === activeHref
              const label = t(item.labelKey)
              return (
                <Tooltip key={item.href}>
                  <TooltipTrigger asChild>
                    <Link
                      href={item.href}
                      prefetch={false}
                      aria-label={label}
                      aria-current={active ? 'page' : undefined}
                      className={cn(
                        'flex min-h-11 cursor-pointer items-center justify-center border-l-2 border-transparent transition-colors duration-150 hover:bg-muted focus-ring motion-reduce:transition-none',
                        active ? 'border-primary bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      <RailNavigationIcon Icon={Icon} label={label} />
                    </Link>
                  </TooltipTrigger>
                  <TooltipPortal>
                    <TooltipContent side="right" sideOffset={10}>{label}</TooltipContent>
                  </TooltipPortal>
                </Tooltip>
              )
            })}
          </div>
          <div className="flex shrink-0 flex-col items-center border-t border-sidebar-border py-3">
            <Link href="/settings" aria-label={t('items.settings')} title={t('items.settings')} aria-current={activeHref === '/settings' ? 'page' : undefined} className={cn('grid size-10 place-items-center rounded-md focus-ring', activeHref === '/settings' ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
              <Settings className="size-[18px]" />
            </Link>
            <ThemeCustomizer trigger={
              <Button type="button" variant="ghost" size="icon" className="size-11 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={t('toolbar.appearance')} title={t('toolbar.appearance')}>
                <Palette className="size-[18px]" aria-hidden="true" />
              </Button>
            } />
            <ModeToggle />
          </div>
        </nav>
      </TooltipProvider>
    )
  }

  return (
    <>
      {/* Mobile Overlay */}
      {isSidebarOpen ? (
      <button
        type="button"
        aria-label={t('toolbar.sidebarClose')}
          className="fixed inset-0 z-40 bg-black/50 transition-opacity md:hidden border-0 p-0 focus:outline-none"
          onClick={() => {
            restoreToggleFocusOnCloseRef.current = false
            setSidebarOpen(false)
          }}
        />
      ) : null}

      <nav
        id="mimirq-sidebar"
        ref={navRef}
        aria-label={t('toolbar.navLabel')}
        aria-hidden={!isSidebarOpen}
        className={cn(
          'peer flex-shrink-0 border-r border-sidebar-border/60 bg-sidebar text-sidebar-foreground flex flex-col transition-transform duration-200 ease-out motion-reduce:transition-none z-50',
          'fixed inset-y-0 left-0 md:relative', // Mobile: fixed, Desktop: relative
          isSidebarOpen ? 'w-[264px] translate-x-0' : 'w-[264px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden'
        )}
      >
        {/* Logo 区域 */}
        <div className="flex h-16 shrink-0 items-center gap-3 px-5">
          <Link href="/" aria-label={BRAND_NAME} className="rounded-md transition-opacity hover:opacity-75 focus-ring motion-reduce:transition-none">
            <BrandLogo className="w-[132px]" decorative priority />
          </Link>
          {isSidebarOpen ? (
            <Button
              ref={toggleButtonRef}
              variant="ghost"
              size="icon"
              className="ml-auto size-9 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
              onPointerDown={handleSidebarTogglePointerDown}
              onKeyDown={handleSidebarToggleKeyDown}
              onClick={handleSidebarToggle}
              aria-controls="mimirq-sidebar"
              aria-expanded={true}
              aria-label={t('toolbar.collapse')}
              title={t('toolbar.collapse')}
            >
              <PanelLeftClose className="size-4" />
            </Button>
          ) : null}
        </div>

        {/* 新对话按钮 */}
        <div className="px-3 pb-2 pt-4">
          <Button
            ref={firstActionRef}
            variant="ghost"
            className={cn(
              "h-10 w-full justify-start gap-2.5 rounded-md border border-sidebar-border/80 bg-card px-3 text-body font-medium text-sidebar-foreground transition-colors duration-150 shadow-none sm:h-10",
              "hover:border-sidebar-border hover:bg-muted",
              "active:scale-[0.98]"
            )}
            onClick={() => {
              router.push('/')
              closeSidebarOnMobile()
            }}
          >
            <Plus className="size-4 text-muted-foreground" />
            <span>{t('actions.newConversation')}</span>
          </Button>
        </div>

        <div className="px-3 pb-2">
          <button
            type="button"
            className="group flex h-10 w-full items-center justify-between gap-2.5 rounded-md bg-transparent px-3 text-left text-sidebar-foreground/80 shadow-none transition-colors duration-150 hover:bg-muted hover:text-foreground focus-ring"
            onClick={() => {
              setCommandMenuOpen(true)
              closeSidebarOnMobile()
            }}
            aria-label={t('command.triggerLabel')}
            aria-haspopup="dialog"
            aria-expanded={commandMenuOpen}
            aria-controls="mimirq-command-menu"
            title={t('command.triggerLabel')}
          >
            <div className="flex min-w-0 items-center gap-3">
              <Search className="size-4 shrink-0" />
              <div className="min-w-0">
                <p className="truncate text-body font-medium">{t('command.triggerLabel')}</p>
              </div>
            </div>
            <kbd className="shrink-0 text-micro font-normal text-muted-foreground">⌘K</kbd>
          </button>
        </div>

        {/* 导航菜单 */}
        {/* Allow internal scroll so items are never clipped on short viewports. */}
        <div className="flex-1 min-h-0 px-3 py-2 overflow-y-auto overscroll-contain no-scrollbar">
          <div className="space-y-4">
            {visibleMenuSections.map((section) => {
              const isOpen = openSections[section.id] ?? false
              const hasActiveItem = sectionHasActiveRoute(activeHref, section.items)
              const ToggleIcon = isOpen ? ChevronDown : ChevronRight

              return (
                <section
                  key={section.id}
                  className="space-y-1"
                >
                  <button
                    type="button"
                    className={cn(
                      'flex w-full items-center justify-between gap-3 rounded-md px-3 py-1.5 text-left transition-colors duration-150 focus-ring',
                      hasActiveItem ? 'text-muted-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                    )}
                    onClick={() => toggleSection(section.id)}
                    aria-expanded={isOpen}
                    aria-controls={`sidebar-section-${section.id}`}
                  >
                    <div className="min-w-0">
                      <p className="text-caption font-medium">{t(section.titleKey)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <ToggleIcon className="size-3.5 shrink-0" />
                    </div>
                  </button>

                  <div
                    id={`sidebar-section-${section.id}`}
                    className={cn(
                      'grid overflow-hidden transition-[grid-template-rows,opacity] duration-300 ease-out',
                      isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                    )}
                  >
                    <div className="overflow-hidden">
                      <div className="space-y-1 pb-1">
                        {section.items.map((item) => {
                          const Icon = item.icon
                          const isActive = activeHref === item.href

                          return (
                            <div key={item.href}>
                              <Link
                                href={item.href}
                                prefetch={false}
                                onClick={closeSidebarOnMobile}
                                aria-current={isActive ? 'page' : undefined}
                                className={cn(
                                  'relative flex items-center gap-3 px-3 py-2.5 rounded-md transition-colors duration-150 group focus-ring',
                                  'before:pointer-events-none before:absolute before:left-1 before:top-2 before:bottom-2 before:w-[3px] before:rounded-full before:transition-all before:duration-200',
                                  isActive
                                    ? 'text-sidebar-foreground font-semibold bg-primary/5 shadow-none before:bg-primary'
                                    : 'font-medium text-sidebar-foreground/80 hover:bg-muted hover:text-sidebar-foreground before:bg-transparent'
                                )}
                              >
                                <Icon
                                  className={cn(
                                    'size-4 transition-colors duration-150',
                                    isActive ? 'text-sidebar-foreground' : 'text-muted-foreground group-hover:text-sidebar-foreground'
                                  )}
                                />
                                <span className="text-sm">{t(item.labelKey)}</span>
                              </Link>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                </section>
              )
            })}
          </div>
        </div>

        {/* 底部信息 */}
        <div className="p-3 border-t border-sidebar-border/60 bg-sidebar">
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label={isAuthenticated ? t('user.openSettings') : t('auth.goToLogin')}
              title={isAuthenticated ? t('user.openSettings') : t('auth.goToLogin')}
              className="group flex min-w-0 flex-1 items-center gap-3 rounded-md p-2 text-left transition-colors duration-150 hover:bg-muted focus-ring motion-reduce:transition-none"
              onClick={() => {
                if (isAuthenticated) {
                  router.push('/settings')
                } else {
                  router.push('/auth')
                }
                closeSidebarOnMobile()
              }}
            >
              <div className="relative flex size-9 shrink-0 items-center justify-center rounded-full border border-sidebar-border bg-secondary text-sm font-medium text-sidebar-foreground" aria-hidden="true">
                {isAuthenticated && userInitial ? userInitial : <User className="size-4" />}
              </div>
              <div className="flex-1 min-w-0">
                <p className="truncate text-sm font-medium leading-5 text-sidebar-foreground">
                  {userDisplayName}
                </p>
                <p className="mt-0.5 truncate text-caption text-muted-foreground">
                  {userStatusLine}
                </p>
              </div>
            </button>
            <div className="flex flex-col gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-lg hover:bg-destructive/8 hover:text-destructive transition-all duration-200"
                onClick={() => {
                  if (isAuthenticated) {
                    logout()
                    return
                  }
                  router.push('/auth')
                }}
                title={isAuthenticated ? t('auth.logout') : t('auth.login')}
                aria-label={isAuthenticated ? t('auth.logout') : t('auth.login')}
              >
                {isAuthenticated ? (
                  <LogOut className="size-4" />
                ) : (
                  <LogIn className="size-4" />
                )}
              </Button>
              <ModeToggle />
            </div>
          </div>

          <div className="mt-2">
            <ThemeCustomizer
              trigger={
                <Button
                  variant="ghost"
                  className="h-9 w-full justify-start gap-2 rounded-md px-2 text-compact font-medium text-sidebar-foreground/80 shadow-none transition-colors duration-150 hover:bg-muted hover:text-foreground"
                  title={t('toolbar.appearance')}
                  aria-label={t('toolbar.appearance')}
                >
                  <Palette className="size-4" aria-hidden="true" />
                  <span>{t('toolbar.appearance')}</span>
                  <span className="ml-auto text-micro font-medium text-muted-foreground">
                    {t('toolbar.appearanceHint', { count: SURFACE_THEMES.length })}
                  </span>
                </Button>
              }
            />
          </div>

          <div className="mt-2 flex items-center justify-between gap-2">
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="flex min-h-8 items-center gap-2 rounded-md px-2 text-caption font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-ring"
                  aria-label={t('deps.openStatus')}
                  title={t('deps.openStatus')}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      'size-1.5 rounded-full',
                      backendOk === true ? 'bg-success' : backendOk === false ? 'bg-warning' : 'bg-muted-foreground'
                    )}
                  />
                  <span>{backendOk === true ? t('deps.statusReady') : backendOk === false ? t('deps.statusNotReady') : t('deps.statusChecking')}</span>
                </button>
              </PopoverTrigger>
              <PopoverContent align="start" side="top" className="w-80">
                <div className="space-y-3 text-xs">
                  <div className="flex items-center justify-between">
                    <p className="font-semibold">{t('deps.ready')}</p>
                    <span
                      className={cn(
                        "font-medium",
                        (() => {
    if (backendOk === true) {
        return "text-success";
    }
    else if (backendOk === false) {
            return "text-destructive";
        }
        else {
            return "text-muted-foreground";
        }
})()
                      )}
                    >
                      {(() => {
    if (backendOk === true) {
        return "OK";
    }
    else if (backendOk === false) {
            return "Down";
        }
        else {
            return "...";
        }
})()}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-[11px] text-muted-foreground">
                    <div className="flex items-center justify-between gap-2">
                      <span>Auth</span>
                      <span className="text-foreground">{authMode || '-'}</span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span>Vector</span>
                      <span className="text-foreground">{vectorBackend || '-'}</span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span>Build</span>
                      <span className="font-mono text-foreground">{buildShaShort || '-'}</span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span>Checked</span>
                      <span className="text-foreground">{checkedAtLabel}</span>
                    </div>
                  </div>

                  <div className="rounded-md border border-border/60 bg-background/40 p-2.5">
                    {readyDetails ? (
                      <div className="space-y-2">
                        {depRows.map((row) => {
                          const st = formatDepStatus(row.status)
                          const errText = trimmedPrimitiveString(row.error)
                          return (
                            <div key={row.key} className="space-y-0.5">
                              <div className="flex items-start justify-between gap-2">
                                <span className="font-medium text-foreground">{row.key}</span>
                                <span className={cn("font-medium", st.className)}>{st.label}</span>
                              </div>
                              {row.note ? <div className="text-[11px] text-muted-foreground">{row.note}</div> : null}
                              {errText ? (
                                <div
                                  className="text-[11px] text-muted-foreground max-w-[260px] truncate"
                                  title={errText}
                                >
                                  {errText}
                                </div>
                              ) : null}
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <p className="text-[11px] text-muted-foreground">{t('deps.unavailable')}</p>
                    )}
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    {canOpenDiagnostics ? (
                      <Link href="/diagnostics" className="text-[11px] text-primary hover:underline">
                        {t('deps.diagnosticsLink')}
                      </Link>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">仅管理员可查看诊断</span>
                    )}
                    <span className="text-[11px] text-muted-foreground">{t('deps.requestIdHint')}</span>
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </nav>

      {!isSidebarOpen ? (
        <Button
          ref={toggleButtonRef}
          variant="ghost"
          size="icon"
          aria-controls="mimirq-sidebar"
          aria-expanded={false}
          aria-label={t('toolbar.expand')}
          title={t('toolbar.expand')}
          className="fixed left-4 top-4 z-50 size-9 rounded-md bg-card text-muted-foreground shadow-none hover:bg-muted hover:text-foreground"
          onPointerDown={handleSidebarTogglePointerDown}
          onKeyDown={handleSidebarToggleKeyDown}
          onClick={handleSidebarToggle}
        >
          <PanelLeftOpen className="size-4" />
        </Button>
      ) : null}
    </>
  )
}
