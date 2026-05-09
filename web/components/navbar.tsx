/**
 * 左侧固定导航栏组件
 */
'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  Activity,
  BarChart3,
  Braces,
  ChevronDown,
  ChevronRight,
  Coins,
  Database,
  FileSearch,
  FileText,
  GitCompare,
  Grid3X3,
  Hash,
  History,
  Layers,
  LogIn,
  LogOut,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Scissors,
  Search,
  Settings,
  Share2,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  User,
  Users,
  Wand2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/ui/status-badge'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Link, usePathname, useRouter } from '@/i18n/navigation'
import { cn } from '@/lib/utils'
import { ModeToggle } from '@/components/mode-toggle'
import { useAuth } from '@/hooks/use-auth'
import { useBackendMeta } from '@/hooks/use-backend-meta'
import { useBackendReady } from '@/hooks/use-backend-ready'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { useCommandMenuState } from '@/store/command-menu'
import { TENANT_PERMISSIONS, tenantAccessAllows, type TenantPermission } from '@/lib/tenant-permissions'

type SectionId = 'core' | 'ingestion' | 'knowledge' | 'analysis' | 'system'

type MenuItem = {
  icon: React.ComponentType<{ className?: string }>
  labelKey: string
  href: string
  requiredPermission?: TenantPermission
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
      { icon: MessageSquare, labelKey: 'items.conversation', href: '/' },
      { icon: History, labelKey: 'items.history', href: '/history' },
    ],
  },
  {
    id: 'knowledge',
    titleKey: 'sections.knowledge',
    items: [
      { icon: Layers, labelKey: 'items.datasets', href: '/datasets' },
      { icon: Database, labelKey: 'items.knowledgeBase', href: '/knowledge' },
      { icon: Activity, labelKey: 'items.ingestion', href: '/knowledge/ingestion' },
      { icon: ShieldAlert, labelKey: 'items.quarantine', href: '/knowledge/quarantine' },
      { icon: Star, labelKey: 'items.feedback', href: '/knowledge/feedback' },
    ],
  },
  {
    id: 'ingestion',
    titleKey: 'sections.ingestion',
    items: [
      { icon: FileText, labelKey: 'items.parsing', href: '/parsing' },
      { icon: ShieldCheck, labelKey: 'items.dataGovernance', href: '/data-governance' },
      { icon: Braces, labelKey: 'items.governanceProfiles', href: '/data-governance/profiles' },
      { icon: Hash, labelKey: 'items.commonLines', href: '/data-governance/common-lines' },
      { icon: Scissors, labelKey: 'items.chunkPreview', href: '/chunk-preview' },
    ],
  },
  {
    id: 'analysis',
    titleKey: 'sections.analysis',
    items: [
      { icon: Grid3X3, labelKey: 'items.ragVisualization', href: '/knowledge/similarity' },
      { icon: Share2, labelKey: 'items.knowledgeGraph', href: '/graph' },
      { icon: GitCompare, labelKey: 'items.graphSnapshots', href: '/graph/snapshots' },
      { icon: FileSearch, labelKey: 'items.graphDiagnostics', href: '/graph/diagnostics' },
      { icon: BarChart3, labelKey: 'items.ragas', href: '/evaluations' },
      { icon: SlidersHorizontal, labelKey: 'items.ablations', href: '/evaluations/ablations' },
      { icon: FileText, labelKey: 'items.reports', href: '/reports' },
      { icon: Wand2, labelKey: 'items.prompts', href: '/prompts' },
    ],
  },
  {
    id: 'system',
    titleKey: 'sections.system',
    items: [
      { icon: Activity, labelKey: 'items.diagnostics', href: '/diagnostics', requiredPermission: TENANT_PERMISSIONS.OBSERVABILITY_READ },
      { icon: Coins, labelKey: 'items.usage', href: '/usage', requiredPermission: TENANT_PERMISSIONS.USAGE_READ },
      { icon: ShieldCheck, labelKey: 'items.audit', href: '/audit', requiredPermission: TENANT_PERMISSIONS.AUDIT_READ },
      { icon: ShieldCheck, labelKey: 'items.accessReview', href: '/access-review', requiredPermission: TENANT_PERMISSIONS.AUDIT_READ },
      { icon: User, labelKey: 'items.members', href: '/settings/rbac', requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ },
      { icon: Users, labelKey: 'items.groups', href: '/settings/groups', requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ },
      { icon: Settings, labelKey: 'items.settings', href: '/settings', requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ },
    ],
  },
]

const DEFAULT_OPEN_SECTIONS = new Set<SectionId>(['core', 'knowledge'])
const OPEN_SECTIONS_STORAGE_KEY = 'mimirq_navbar_open_sections_v1'

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
    const raw = globalThis.window.localStorage.getItem(OPEN_SECTIONS_STORAGE_KEY)
    if (!raw) return createInitialOpenSections()
    return sanitizeOpenSections(JSON.parse(raw))
  } catch {
    return createInitialOpenSections()
  }
}

export function Navbar({
  isSidebarOpen: externalIsOpen,
  setSidebarOpen: externalSetOpen,
}: Readonly<{
  isSidebarOpen?: boolean
  setSidebarOpen?: (isOpen: boolean) => void
}> = {}) {
  const navRef = useRef<HTMLElement | null>(null)
  const toggleButtonRef = useRef<HTMLButtonElement | null>(null)
  const firstActionRef = useRef<HTMLButtonElement | null>(null)
  const prevIsSidebarOpenRef = useRef<boolean | null>(null)
  const restoreToggleFocusOnCloseRef = useRef(false)
  const [internalIsOpen, setInternalIsOpen] = useState(true)
  const [openSections, setOpenSections] = useState<Record<SectionId, boolean>>(createInitialOpenSections)
  const [hasHydratedOpenSections, setHasHydratedOpenSections] = useState(false)
  const isSidebarOpen = externalIsOpen ?? internalIsOpen
  const setSidebarOpen = externalSetOpen ?? setInternalIsOpen
  const pathname = usePathname()
  const router = useRouter()
  const { user, isAuthenticated, isDevMode, logout } = useAuth()
  const t = useTranslations('Navbar')
  const { data: backendMeta } = useBackendMeta()
  const backendReady = useBackendReady()
  const tenantAccess = useTenantAccess()
  const commandMenuOpen = useCommandMenuState((state) => state.open)
  const setCommandMenuOpen = useCommandMenuState((state) => state.setOpen)
  const canAccessPermission = useCallback(
    (permission?: TenantPermission) => !permission || tenantAccessAllows(tenantAccess.data, permission),
    [tenantAccess.data]
  )
  const visibleMenuSections = useMemo(
    () =>
      menuSections
        .map((section) => ({
          ...section,
          items: section.items.filter((item) => canAccessPermission(item.requiredPermission)),
        }))
        .filter((section) => section.items.length > 0),
    [canAccessPermission]
  )
  const visibleMenuItems = useMemo(() => visibleMenuSections.flatMap((section) => section.items), [visibleMenuSections])
  const activeHref = getMostSpecificActiveHref(pathname, visibleMenuItems)
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
    const el = navRef.current as any
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
    try {
      globalThis.window.localStorage.setItem(OPEN_SECTIONS_STORAGE_KEY, JSON.stringify(openSections))
    } catch {
      // ignore unavailable or quota-limited storage
    }
  }, [hasHydratedOpenSections, openSections])

  // Dev UX: warm up route chunks in the background so first-click navigation feels snappier.
  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return
    if (globalThis.window === undefined) return
    if (globalThis.navigator?.webdriver) return
    const key = '__mimirq_routes_prefetched__'
    if ((globalThis.window as any)[key]) return
    ;(globalThis.window as any)[key] = true

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
    const w = globalThis.window as any
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

  const statusBadgeState = backendOk === true ? 'completed' : backendOk === false ? 'failed' : 'processing'
  const statusBadgeSuffix = backendOk === true ? 'OK' : backendOk === false ? 'Down' : '...'
  const statusBadgeLabel = `${t('status.badgePrefix')}${statusBadgeSuffix}`
  const userDisplayName =
    user?.username || user?.email || (isDevMode ? t('user.developerMode') : t('user.unauthenticatedName'))
  const userStatusLine = isAuthenticated ? user?.email || t('user.onlineStatus') : t('user.offlineEnvironment')
  const canOpenSettings = canAccessPermission(TENANT_PERMISSIONS.SETTINGS_READ)
  const canOpenDiagnostics = canAccessPermission(TENANT_PERMISSIONS.OBSERVABILITY_READ)

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
          'peer flex-shrink-0 border-r border-sidebar-border/80 bg-sidebar/85 text-sidebar-foreground backdrop-blur-xl supports-[backdrop-filter]:bg-sidebar/72 flex flex-col transition-transform duration-200 ease-out z-50',
          'fixed inset-y-0 left-0 md:relative', // Mobile: fixed, Desktop: relative
          isSidebarOpen ? 'w-[264px] translate-x-0' : 'w-[264px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden'
        )}
      >
        {/* Logo 区域 */}
        <div className="h-14 px-5 border-b border-sidebar-border/50 flex items-center gap-3">
          <Link href="/" className="flex items-center gap-3 group rounded-xl focus-ring">
            <div className="size-8 rounded-lg bg-foreground text-background flex items-center justify-center">
              <span className="font-bold text-lg">M</span>
            </div>
            <div className="flex flex-col">
              <span className="font-semibold text-foreground leading-none">MimirQ</span>
              <span className="text-micro text-muted-foreground font-medium mt-1">{t('brand.tagline')}</span>
            </div>
          </Link>
        </div>

        {/* 新对话按钮 */}
        <div className="p-4 pb-2">
          <Button
            ref={firstActionRef}
            className={cn(
              "w-full justify-start gap-2 h-11 rounded-2xl font-semibold transition-colors duration-200",
              "bg-card border border-border shadow-sm text-foreground",
              "hover:bg-[#CAF0F8]/55 hover:border-[#CAF0F8]/70",
              "active:bg-accent/80"
            )}
            onClick={() => {
              router.push('/')
              closeSidebarOnMobile()
            }}
          >
            <Plus className="size-4" />
            <span>{t('actions.newConversation')}</span>
          </Button>
        </div>

        <div className="px-4 pb-2">
          <button
            type="button"
            className="group flex w-full items-center justify-between gap-3 rounded-2xl border border-dashed border-border/70 bg-background/70 px-3 py-3 text-left transition-colors duration-200 hover:border-[#CAF0F8]/70 hover:bg-[#CAF0F8]/55 focus-ring"
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
              <div className="flex size-9 items-center justify-center rounded-xl bg-muted text-muted-foreground transition-colors duration-200 group-hover:bg-[#CAF0F8]/65 group-hover:text-foreground">
                <Search className="size-4" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">{t('command.triggerLabel')}</p>
                <p className="text-[11px] text-muted-foreground">{t('command.triggerHint')}</p>
              </div>
            </div>
            <span className="rounded-md border border-border/50 bg-muted/40 px-2 py-0.5 text-[11px] font-medium text-muted-foreground shadow-subtle">⌘K</span>
          </button>
        </div>

        {/* 导航菜单 */}
        {/* Allow internal scroll so items are never clipped on short viewports. */}
        <div className="flex-1 min-h-0 px-3 py-2 overflow-y-auto overscroll-contain no-scrollbar">
          <div className="space-y-4">
            {visibleMenuSections.map((section, index) => {
              const isOpen = openSections[section.id] ?? false
              const hasActiveItem = sectionHasActiveRoute(activeHref, section.items)
              const ToggleIcon = isOpen ? ChevronDown : ChevronRight

              return (
                <section
                  key={section.id}
                  className={cn('space-y-1.5', index > 0 ? 'border-t border-sidebar-border/50 pt-3' : '')}
                >
                  <button
                    type="button"
                    className={cn(
                      'flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left transition-colors duration-200 focus-ring',
                      hasActiveItem ? 'text-foreground' : 'text-muted-foreground/70 hover:bg-foreground/[0.04] hover:text-foreground'
                    )}
                    onClick={() => toggleSection(section.id)}
                    aria-expanded={isOpen}
                    aria-controls={`sidebar-section-${section.id}`}
                  >
                    <div className="min-w-0">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">{t(section.titleKey)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <ToggleIcon className="size-4 shrink-0" />
                    </div>
                  </button>

                  <div
                    id={`sidebar-section-${section.id}`}
                    className={cn(
                      'grid overflow-hidden transition-[grid-template-rows,opacity] duration-200 ease-out',
                      isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-70'
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
                                prefetch
                                onClick={closeSidebarOnMobile}
                                aria-current={isActive ? 'page' : undefined}
                                className={cn(
                                  'relative flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors duration-200 group focus-ring',
                                  'before:pointer-events-none before:absolute before:left-1 before:top-2 before:bottom-2 before:w-[2.5px] before:rounded-full before:bg-transparent',
                                  isActive
                                    ? 'text-foreground font-medium before:bg-foreground/80'
                                    : 'text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground'
                                )}
                              >
                                <Icon
                                  className={cn(
                                    'size-4 transition-colors',
                                    isActive ? 'text-foreground' : 'text-muted-foreground/70 group-hover:text-foreground'
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
        <div className="p-4 border-t border-sidebar-border/50 bg-transparent">
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label={isAuthenticated ? t('user.openSettings') : t('auth.goToLogin')}
              title={isAuthenticated ? t('user.openSettings') : t('auth.goToLogin')}
              className="flex-1 flex items-center gap-3 p-2 rounded-xl hover:bg-[#CAF0F8]/55 transition-colors duration-200 border border-transparent hover:border-[#CAF0F8]/70 group text-left focus-ring"
              onClick={() => {
                if (isAuthenticated) {
                  router.push(canOpenSettings ? '/settings' : '/')
                } else {
                  router.push('/auth')
                }
                closeSidebarOnMobile()
              }}
            >
              <div className="relative w-10 h-10 flex-shrink-0">
                <div className="absolute inset-0 rounded-xl border border-border bg-muted/50 shadow-sm group-hover:border-[#CAF0F8]/70 group-hover:bg-[#CAF0F8]/45 transition-colors duration-200" />
                <div className="absolute inset-0 flex items-center justify-center text-muted-foreground group-hover:text-foreground transition-colors">
                  <User className="size-5" />
                </div>
                {isAuthenticated && (
                  <div className="absolute -right-0.5 -bottom-0.5 size-3 bg-success border-2 border-background rounded-full" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-foreground truncate group-hover:text-primary transition-colors">
                  {userDisplayName}
                </p>
                <p className="text-[11px] text-muted-foreground truncate leading-tight mt-0.5">
                  {userStatusLine}
                </p>
              </div>
            </button>
            <div className="flex flex-col gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-lg hover:bg-[#CAF0F8]/55 hover:text-destructive transition-colors duration-200"
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

          <div className="mt-3 flex items-center justify-between gap-2">
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="rounded-full focus-ring"
                  aria-label={t('deps.openStatus')}
                  title={t('deps.openStatus')}
                >
                  <StatusBadge
                    status={(() => {
    if (backendOk === true) {
        return "completed";
    }
    else if (backendOk === false) {
            return "failed";
        }
        else {
            return "processing";
        }
})()}
                    label={`Deps：${(() => {
    if (backendOk === true) {
        return "OK";
    }
    else if (backendOk === false) {
            return "Down";
        }
        else {
            return "...";
        }
})()}`}
                    dense
                  />
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

      {/* 侧边栏折叠按钮 */}
      {isSidebarOpen ? (
        <Button
          ref={toggleButtonRef}
          variant="ghost"
          size="icon"
          aria-controls="mimirq-sidebar"
          aria-expanded={true}
          aria-label={t('toolbar.collapse')}
          title={t('toolbar.collapse')}
          className={cn(
            'fixed z-50 border border-border bg-background/92 text-muted-foreground shadow-soft backdrop-blur transition-colors duration-200 ease-out hover:bg-muted',
            'bottom-4 left-[264px] size-11 rounded-xl opacity-0 pointer-events-none hover:text-primary supports-[padding:env(safe-area-inset-bottom)]:bottom-[calc(env(safe-area-inset-bottom)+1rem)] md:peer-hover:opacity-100 md:peer-hover:pointer-events-auto md:peer-focus-within:opacity-100 md:peer-focus-within:pointer-events-auto md:hover:opacity-100 md:hover:pointer-events-auto md:focus-visible:opacity-100 md:focus-visible:pointer-events-auto sm:size-10'
          )}
          onPointerDown={handleSidebarTogglePointerDown}
          onKeyDown={handleSidebarToggleKeyDown}
          onClick={handleSidebarToggle}
        >
          <PanelLeftClose className="size-5" />
        </Button>
      ) : (
        <div className="fixed left-0 top-0 z-50 h-16 w-4 overflow-visible md:top-14 md:h-14 md:w-5">
          <div className="group/sidebar-toggle relative h-full w-full overflow-visible">
            <Button
              ref={toggleButtonRef}
              variant="outline"
              size="icon"
              aria-controls="mimirq-sidebar"
              aria-expanded={false}
              aria-label={t('toolbar.expand')}
              title={t('toolbar.expand')}
              className={cn(
                'absolute z-50 border border-border bg-background/92 text-foreground shadow-soft backdrop-blur transition-all duration-200 ease-out hover:bg-muted',
                'left-3 top-4 size-9 rounded-full pointer-events-auto md:left-0 md:top-1/2 md:-translate-y-1/2 supports-[padding:env(safe-area-inset-left)]:md:left-[calc(env(safe-area-inset-left)-0.15rem)]',
                'md:-translate-x-[110%] md:scale-95 md:opacity-0 md:pointer-events-none',
                'md:group-hover/sidebar-toggle:translate-x-2 md:group-hover/sidebar-toggle:scale-100 md:group-hover/sidebar-toggle:opacity-100 md:group-hover/sidebar-toggle:pointer-events-auto',
                'md:group-focus-within/sidebar-toggle:translate-x-2 md:group-focus-within/sidebar-toggle:scale-100 md:group-focus-within/sidebar-toggle:opacity-100 md:group-focus-within/sidebar-toggle:pointer-events-auto',
                'focus-visible:translate-x-0 focus-visible:scale-100 focus-visible:opacity-100 focus-visible:pointer-events-auto md:focus-visible:translate-x-2'
              )}
              onPointerDown={handleSidebarTogglePointerDown}
              onKeyDown={handleSidebarToggleKeyDown}
              onClick={handleSidebarToggle}
            >
              <PanelLeftOpen className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
