/**
 * 左侧固定导航栏组件
 */
'use client'

import { Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ComponentType } from 'react'
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
  Network,
  Members,
  Parsing,
  Prompts,
  Quarantine,
  Reports,
  RuleSet,
  Usage,
  ChevronDown,
  ChevronRight,
  LogOut,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Palette,
  Plus,
  Search,
  Settings,
  User,
  ChevronsUpDown,
} from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Link, usePathname, useRouter } from '@/i18n/navigation'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { BrandLogo } from '@/components/brand-logo'
import { BRAND_NAME } from '@/lib/brand'
import { cn } from '@/lib/utils'
import { ThemeAppearancePanel, ThemeCustomizer } from '@/components/theme-customizer'
import { RecentConversations } from '@/components/recent-conversations'
import { useAuth } from '@/hooks/use-auth'
import { useBackendHealth } from '@/hooks/use-backend-health'
import { useBackendReady } from '@/hooks/use-backend-ready'
import { useIsMobile } from '@/hooks/use-media-query'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { useCommandMenuState } from '@/store/command-menu'
import { TENANT_PERMISSIONS, tenantAccessAllows, type TenantPermission } from '@/lib/tenant-permissions'
import {
  canShowAdminControlledNavigationModule,
  type AdminControlledNavigationModule,
} from '@/lib/navigation-visibility'

type SectionId = 'core' | 'ingestion' | 'knowledge' | 'analysis' | 'system'

type MenuItem = {
  icon: ComponentType<{ className?: string }>
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
      {
        icon: RuleSet,
        labelKey: 'items.governanceProfiles',
        href: '/data-governance/profiles',
        visibilityKey: 'governanceProfiles',
      },
      { icon: Chunking, labelKey: 'items.chunkPreview', href: '/chunk-preview' },
    ],
  },
  {
    id: 'analysis',
    titleKey: 'sections.analysis',
    items: [
      { icon: KnowledgeGraph, labelKey: 'items.knowledgeGraph', href: '/graph', visibilityKey: 'knowledgeGraph' },
      { icon: Network, labelKey: 'items.enterpriseOntology', href: '/ontology' },
      { icon: Evaluation, labelKey: 'items.ragas', href: '/evaluations', visibilityKey: 'ragas' },
      { icon: Reports, labelKey: 'items.reports', href: '/reports', visibilityKey: 'reports' },
      { icon: Prompts, labelKey: 'items.prompts', href: '/prompts', visibilityKey: 'prompts' },
    ],
  },
  {
    id: 'system',
    titleKey: 'sections.system',
    items: [
      {
        icon: Diagnostics,
        labelKey: 'items.diagnostics',
        href: '/diagnostics',
        requiredPermission: TENANT_PERMISSIONS.OBSERVABILITY_READ,
      },
      { icon: Usage, labelKey: 'items.usage', href: '/usage', requiredPermission: TENANT_PERMISSIONS.USAGE_READ },
      { icon: AuditLog, labelKey: 'items.audit', href: '/audit', requiredPermission: TENANT_PERMISSIONS.AUDIT_READ },
      {
        icon: Members,
        labelKey: 'items.members',
        href: '/settings/rbac',
        requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ,
      },
      {
        icon: Groups,
        labelKey: 'items.groups',
        href: '/settings/groups',
        requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ,
      },
      {
        icon: Settings,
        labelKey: 'items.settings',
        href: '/settings',
        requiredPermission: TENANT_PERMISSIONS.SETTINGS_READ,
      },
    ],
  },
]

const DEFAULT_OPEN_SECTIONS = new Set<SectionId>(['core'])
const OPEN_SECTIONS_STORAGE_KEY = 'mimirq_navbar_open_sections_v3'
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
    },
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
      ) : (
        <Icon className="size-[18px]" />
      )}
      {pending ? (
        <span role="status" className="sr-only">
          {t('toolbar.opening', { label })}
        </span>
      ) : null}
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
  const toggleButtonRef = useRef<HTMLButtonElement | null>(null)
  const firstActionRef = useRef<HTMLButtonElement | null>(null)
  const sidebarFocusTargetRef = useRef<'firstAction' | 'toggle' | null>(null)
  const [internalIsOpen, setInternalIsOpen] = useState(true)
  const isSidebarOpen = externalIsOpen ?? internalIsOpen
  const setSidebarOpen = externalSetOpen ?? setInternalIsOpen
  const isMobile = useIsMobile()
  const isSidebarVisible = variant === 'default' && isSidebarOpen
  const isSidebarOverlayOpen = isMobile && isSidebarVisible
  const [openSections, setOpenSections] = useState<Record<SectionId, boolean>>(createInitialOpenSections)
  const [hasHydratedOpenSections, setHasHydratedOpenSections] = useState(false)
  const [hasHydratedNavigationAccess, setHasHydratedNavigationAccess] = useState(false)
  const [commandShortcut, setCommandShortcut] = useState('Ctrl K')
  const [accountView, setAccountView] = useState<'closed' | 'main' | 'appearance'>('closed')
  const accountMenuOpen = isSidebarVisible && accountView !== 'closed'
  const previousAccountView = useRef(accountView)
  const appearanceButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!isSidebarVisible) setAccountView('closed')
  }, [isSidebarVisible])

  useLayoutEffect(() => {
    if (previousAccountView.current === 'appearance' && accountView === 'main' && accountMenuOpen)
      appearanceButtonRef.current?.focus()
    previousAccountView.current = accountView
  }, [accountMenuOpen, accountView])
  const pathname = usePathname()
  const router = useRouter()
  const { user, isAuthenticated, isDevMode, logout } = useAuth()
  const t = useTranslations('Navbar')
  const backendReady = useBackendReady()
  const tenantAccess = useTenantAccess()
  const canReadBackendHealth = tenantAccessAllows(tenantAccess.data, TENANT_PERMISSIONS.OBSERVABILITY_READ)
  const backendHealth = useBackendHealth({
    enabled: canReadBackendHealth,
  })
  const navigationTenantAccess = hasHydratedNavigationAccess ? tenantAccess.data : undefined
  const allowDevNavigation = hasHydratedNavigationAccess && isDevMode
  const commandMenuOpen = useCommandMenuState((state) => state.open)
  const setCommandMenuOpen = useCommandMenuState((state) => state.setOpen)
  const canAccessPermission = useCallback(
    (permission?: TenantPermission) =>
      !permission || allowDevNavigation || tenantAccessAllows(navigationTenantAccess, permission),
    [allowDevNavigation, navigationTenantAccess],
  )
  const canShowNavigationModule = useCallback(
    (moduleKey?: AdminControlledNavigationModule) =>
      !moduleKey || allowDevNavigation || canShowAdminControlledNavigationModule(navigationTenantAccess, moduleKey),
    [allowDevNavigation, navigationTenantAccess],
  )
  const visibleMenuSections = useMemo(
    () =>
      menuSections
        .map((section) => ({
          ...section,
          items: section.items.filter(
            (item) => canAccessPermission(item.requiredPermission) && canShowNavigationModule(item.visibilityKey),
          ),
        }))
        .filter((section) => section.items.length > 0),
    [canAccessPermission, canShowNavigationModule],
  )
  const visibleMenuItems = useMemo(() => visibleMenuSections.flatMap((section) => section.items), [visibleMenuSections])
  const activePathname = NAVIGATION_PARENT_ROUTES[pathname] || pathname
  const activeHref = getMostSpecificActiveHref(activePathname, visibleMenuItems)
  const closeSidebarOnMobile = useCallback(() => {
    if (isSidebarOverlayOpen) setSidebarOpen(false)
  }, [isSidebarOverlayOpen, setSidebarOpen])
  const toggleSection = useCallback((sectionId: SectionId) => {
    setOpenSections((current) => ({ ...createInitialOpenSections(), [sectionId]: !current[sectionId] }))
  }, [])
  const handleSidebarToggle = useCallback(() => {
    sidebarFocusTargetRef.current = isSidebarOpen ? 'toggle' : 'firstAction'
    setSidebarOpen(!isSidebarOpen)
  }, [isSidebarOpen, setSidebarOpen])

  useEffect(() => {
    if (!isSidebarOverlayOpen) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.key !== 'Escape') return
      event.preventDefault()
      handleSidebarToggle()
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [handleSidebarToggle, isSidebarOverlayOpen])

  useLayoutEffect(() => {
    const focusTarget = sidebarFocusTargetRef.current
    sidebarFocusTargetRef.current = null
    if (variant === 'rail') return
    if (isSidebarOpen && focusTarget === 'firstAction') firstActionRef.current?.focus()
    if (!isSidebarOpen && focusTarget === 'toggle') toggleButtonRef.current?.focus()
  }, [isSidebarOpen, variant])

  useEffect(() => {
    setOpenSections(loadOpenSections())
    setCommandShortcut(/Mac|iPhone|iPad|iPod/.test(navigator.platform) ? '⌘ K' : 'Ctrl K')
    setHasHydratedOpenSections(true)
    // Keep SSR and the first client render structurally identical. Tenant access can
    // be cached on the client, so applying it before mount can reorder/insert links.
    setHasHydratedNavigationAccess(true)
  }, [])

  useEffect(() => {
    const activeSection = visibleMenuSections.find((section) => sectionHasActiveRoute(activeHref, section.items))
    if (!activeSection || activeSection.id === 'core') return

    setOpenSections((current) => {
      if (
        current[activeSection.id] &&
        Object.entries(current).every(([id, open]) => id === 'core' || id === activeSection.id || !open)
      )
        return current
      return {
        ...createInitialOpenSections(),
        [activeSection.id]: true,
      }
    })
  }, [activeHref, visibleMenuSections])

  useEffect(() => {
    if (!hasHydratedOpenSections) return
    if (globalThis.window === undefined) return
    writeClientStorage(OPEN_SECTIONS_STORAGE_KEY, JSON.stringify(openSections))
  }, [hasHydratedOpenSections, openSections])

  const profileName = user?.username?.trim()
  const userDisplayName =
    profileName !== undefined && profileName !== ''
      ? profileName
      : (user?.email ?? (isDevMode ? t('user.workspace') : t('user.account')))
  const userInitial = Array.from(userDisplayName)[0]?.toLocaleUpperCase()
  const userStatusLine = isAuthenticated ? (user?.email ?? t('user.onlineStatus')) : t('user.offlineEnvironment')
  const cache = canReadBackendHealth && !backendHealth.isError ? backendHealth.data?.redis : undefined
  const optionalCacheDegraded = cache?.enabled === true && cache.required === false && cache.status === 'disconnected'
  const serviceStatusKey =
    backendReady.isError || backendReady.data?.ok === false
      ? 'statusNotReady'
      : backendReady.data === undefined
        ? 'statusChecking'
        : canReadBackendHealth && backendHealth.isError
          ? 'statusUnknown'
          : optionalCacheDegraded
            ? 'statusDegraded'
            : 'statusReady'
  const serviceStatus = t(`deps.${serviceStatusKey}`)
  const serviceStatusClass =
    serviceStatusKey === 'statusReady'
      ? 'bg-success'
      : serviceStatusKey === 'statusNotReady'
        ? 'bg-destructive'
        : 'bg-warning'
  const canOpenDiagnostics = canAccessPermission(TENANT_PERMISSIONS.OBSERVABILITY_READ)
  const canOpenSettings = canAccessPermission(TENANT_PERMISSIONS.SETTINGS_READ)

  if (variant === 'rail') {
    return (
      <TooltipProvider delayDuration={250}>
        <nav
          aria-label={t('toolbar.navLabel')}
          className="flex h-full w-16 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground"
        >
          <Link
            href="/"
            prefetch={false}
            aria-label={BRAND_NAME}
            className="mx-auto mt-6 mb-6 block rounded-md focus-ring"
          >
            <BrandLogo variant="mark" className="size-8" decorative priority />
          </Link>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain no-scrollbar">
            {visibleMenuItems
              .filter((item) => item.href !== '/settings')
              .map((item) => {
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
                          active
                            ? 'border-l-accent bg-card text-accent shadow-[0_1px_2px_hsl(var(--foreground)/0.06)] hover:bg-card'
                            : 'text-muted-foreground hover:text-foreground',
                        )}
                      >
                        <RailNavigationIcon Icon={Icon} label={label} />
                      </Link>
                    </TooltipTrigger>
                    <TooltipPortal>
                      <TooltipContent side="right" sideOffset={10}>
                        {label}
                      </TooltipContent>
                    </TooltipPortal>
                  </Tooltip>
                )
              })}
          </div>
          <div className="flex shrink-0 flex-col items-center border-t border-sidebar-border/80 py-3">
            {canOpenSettings ? (
              <Link
                href="/settings"
                prefetch={false}
                aria-label={t('items.settings')}
                title={t('items.settings')}
                aria-current={activeHref === '/settings' ? 'page' : undefined}
                className={cn(
                  'grid size-10 place-items-center rounded-md border-l-2 border-transparent transition-colors duration-150 focus-ring motion-reduce:transition-none',
                  activeHref === '/settings'
                    ? 'border-l-accent bg-card text-accent shadow-[0_1px_2px_hsl(var(--foreground)/0.06)]'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                <Settings className="size-[18px]" />
              </Link>
            ) : null}
            <ThemeCustomizer
              trigger={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-11 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                  aria-label={t('toolbar.appearance')}
                  title={t('toolbar.appearance')}
                >
                  <Palette className="size-[18px]" aria-hidden="true" />
                </Button>
              }
            />
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
          tabIndex={-1}
          aria-label={t('toolbar.sidebarClose')}
          className="fixed inset-0 z-40 bg-black/50 transition-opacity md:hidden border-0 p-0 focus:outline-none"
          onClick={handleSidebarToggle}
        />
      ) : null}

      <nav
        id="mimirq-sidebar"
        aria-label={t('toolbar.navLabel')}
        inert={!isSidebarOpen}
        className={cn(
          'peer flex-shrink-0 border-r border-sidebar-border bg-sidebar text-sidebar-foreground flex flex-col transition-transform duration-200 ease-out motion-reduce:transition-none z-50',
          'fixed inset-y-0 left-0 md:relative', // Mobile: fixed, Desktop: relative
          isSidebarOpen
            ? 'w-[208px] translate-x-0'
            : 'w-[208px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden',
        )}
      >
        {/* Logo 区域 */}
        <div className="flex h-[52px] shrink-0 items-center gap-3 border-b border-sidebar-border/75 px-4">
          <Link
            href="/"
            prefetch={false}
            aria-label={BRAND_NAME}
            className="rounded-md transition-opacity hover:opacity-75 focus-ring motion-reduce:transition-none"
          >
            <BrandLogo className="w-28" decorative priority />
          </Link>
          {isSidebarOpen ? (
            <Button
              ref={toggleButtonRef}
              variant="ghost"
              size="icon"
              className="ml-auto size-9 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
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
        <div className="px-3 pb-2 pt-2">
          <Button
            ref={firstActionRef}
            variant="ghost"
            className={cn(
              'h-8.5 max-md:h-11 w-full justify-start gap-2.5 rounded-md border border-sidebar-border bg-card px-3 text-[13px] font-medium text-sidebar-foreground transition-colors duration-150 shadow-[0_1px_2px_hsl(var(--foreground)/0.05)]',
              'hover:border-accent/40 hover:bg-card hover:shadow-[0_2px_6px_hsl(var(--foreground)/0.07)]',
              'active:scale-[0.98]',
            )}
            onClick={() => {
              router.push('/')
              closeSidebarOnMobile()
            }}
          >
            <Plus className="size-4 text-accent" />
            <span>{t('actions.newConversation')}</span>
          </Button>
        </div>

        <div className="px-3 pb-2">
          <button
            type="button"
            className="group flex h-8.5 max-md:h-11 w-full items-center justify-between gap-2.5 rounded-md border border-sidebar-border/70 bg-background/60 px-3 text-left text-sidebar-foreground/80 transition-colors duration-150 hover:border-sidebar-border hover:bg-card hover:text-foreground focus-ring"
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
                <p className="truncate text-[13px] font-normal">{t('command.triggerLabel')}</p>
              </div>
            </div>
            <kbd className="shrink-0 rounded-[5px] border border-border/90 bg-card px-1.5 py-0.5 font-mono text-[10px] font-medium leading-none text-muted-foreground shadow-[0_1px_0_hsl(var(--border))]">
              {commandShortcut}
            </kbd>
          </button>
        </div>

        {/* 导航菜单 */}
        {/* Allow internal scroll so items are never clipped on short viewports. */}
        <div className="flex-1 min-h-0 px-3 py-2 overflow-y-auto overscroll-contain no-scrollbar">
          <Suspense fallback={<p className="px-3 py-2 text-xs text-muted-foreground">{t('recent.loading')}</p>}>
            <RecentConversations enabled={isSidebarOpen} onNavigate={closeSidebarOnMobile} />
          </Suspense>
          <div className="space-y-4">
            {visibleMenuSections
              .filter((section) => section.id !== 'core')
              .map((section) => {
                const isOpen = openSections[section.id] ?? false
                const hasActiveItem = sectionHasActiveRoute(activeHref, section.items)
                const ToggleIcon = isOpen ? ChevronDown : ChevronRight

                return (
                  <section key={section.id} className="space-y-1">
                    <button
                      type="button"
                      className={cn(
                        'flex w-full items-center justify-between gap-3 rounded-md px-3 py-1.5 text-left transition-colors duration-150 focus-ring',
                        hasActiveItem
                          ? 'text-foreground/80'
                          : 'text-muted-foreground/85 hover:bg-muted hover:text-foreground',
                      )}
                      onClick={() => toggleSection(section.id)}
                      aria-expanded={isOpen}
                      aria-controls={`sidebar-section-${section.id}`}
                    >
                      <div className="min-w-0">
                        <p className="text-[11.5px] font-semibold">{t(section.titleKey)}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {!isOpen && hasActiveItem ? (
                          <span className="size-1.5 shrink-0 rounded-full bg-accent" aria-hidden="true" />
                        ) : null}
                        <ToggleIcon className="size-3.5 shrink-0" />
                      </div>
                    </button>

                    <div
                      id={`sidebar-section-${section.id}`}
                      inert={!isOpen}
                      aria-hidden={!isOpen}
                      className={cn(
                        'grid overflow-hidden transition-[grid-template-rows,opacity] duration-300 ease-out',
                        isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
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
                                    'relative flex h-8.5 max-md:h-11 items-center gap-2.5 border-l-2 border-transparent px-2.5 py-1.5 rounded-md transition-colors duration-150 group focus-ring',
                                    isActive
                                      ? 'border-l-accent bg-card text-sidebar-foreground font-medium shadow-[0_1px_2px_hsl(var(--foreground)/0.06)] ring-1 ring-sidebar-border/80'
                                      : 'font-normal text-sidebar-foreground/80 hover:bg-muted hover:text-sidebar-foreground',
                                  )}
                                >
                                  <Icon
                                    className={cn(
                                      'size-4 transition-colors duration-150',
                                      isActive
                                        ? 'text-accent'
                                        : 'text-muted-foreground group-hover:text-sidebar-foreground',
                                    )}
                                  />
                                  <span className="text-[13px]">{t(item.labelKey)}</span>
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

        <div className="shrink-0 border-t border-sidebar-border/80 bg-sidebar p-2.5">
          <Popover open={accountMenuOpen} onOpenChange={(open) => setAccountView(open ? 'main' : 'closed')}>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label={t('user.menu')}
                className="flex min-h-14 w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-card/85 hover:ring-1 hover:ring-sidebar-border/70 focus-ring"
              >
                <span className="relative grid size-9 shrink-0 place-items-center rounded-full bg-card text-sm font-medium text-sidebar-foreground ring-1 ring-sidebar-border shadow-[0_1px_2px_hsl(var(--foreground)/0.05)]">
                  {isAuthenticated && userInitial ? userInitial : <User className="size-4" aria-hidden="true" />}
                  <span
                    title={serviceStatus}
                    aria-hidden="true"
                    className={cn(
                      'absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full ring-2 ring-sidebar',
                      serviceStatusClass,
                      serviceStatusKey === 'statusChecking' && 'animate-pulse motion-reduce:animate-none',
                    )}
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-sidebar-foreground">{userDisplayName}</span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">{userStatusLine}</span>
                </span>
                <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              </button>
            </PopoverTrigger>
            <PopoverContent
              aria-label={accountView === 'appearance' ? t('toolbar.appearance') : t('user.menu')}
              align="start"
              side="top"
              sideOffset={8}
              collisionPadding={12}
              className="flex max-h-[min(32rem,var(--radix-popover-content-available-height))] w-80 max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-xl p-0"
            >
              {accountView === 'appearance' ? (
                <ThemeAppearancePanel onBack={() => setAccountView('main')} />
              ) : (
                <div className="min-h-0 overflow-y-auto overscroll-contain p-2">
                  <div className="border-b border-border/60 px-3 pb-3 pt-2">
                    <p className="text-sm font-medium">{userDisplayName}</p>
                    <p className="mt-1 break-words text-xs text-muted-foreground">{userStatusLine}</p>
                  </div>
                  {canOpenDiagnostics ? (
                    <Link
                      href="/diagnostics"
                      onClick={() => {
                        setAccountView('closed')
                        closeSidebarOnMobile()
                      }}
                      className="my-1 flex min-h-12 items-center gap-2.5 rounded-lg px-3 py-2 text-xs hover:bg-muted focus-ring"
                    >
                      <span aria-hidden="true" className={cn('size-2 shrink-0 rounded-full', serviceStatusClass)} />
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium">{t('deps.summaryLabel')}</span>
                        <span className="mt-1 block text-muted-foreground">{serviceStatus}</span>
                      </span>
                      <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                    </Link>
                  ) : (
                    <div className="my-1 flex min-h-12 items-center gap-2.5 px-3 py-2 text-xs">
                      <span aria-hidden="true" className={cn('size-2 shrink-0 rounded-full', serviceStatusClass)} />
                      <span>{serviceStatus}</span>
                    </div>
                  )}
                  <div className="border-t border-border/60 pt-1">
                    <Button
                      ref={appearanceButtonRef}
                      type="button"
                      variant="ghost"
                      className="h-11 w-full justify-start gap-2.5 px-3 text-sm font-normal"
                      onClick={() => setAccountView('appearance')}
                    >
                      <Palette className="size-4" aria-hidden="true" />
                      <span className="flex-1 text-left">{t('toolbar.appearance')}</span>
                      <ChevronRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
                    </Button>
                    {canOpenSettings ? (
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-11 w-full justify-start gap-2.5 px-3 text-sm font-normal"
                        onClick={() => {
                          setAccountView('closed')
                          router.push('/settings')
                          closeSidebarOnMobile()
                        }}
                      >
                        <Settings className="size-4" aria-hidden="true" />
                        {t('items.settings')}
                      </Button>
                    ) : null}
                  </div>
                  {isAuthenticated && (
                    <div className="mt-1 border-t border-border/60 pt-1">
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-11 w-full justify-start gap-2.5 px-3 text-sm font-normal text-destructive hover:text-destructive"
                        onClick={() => {
                          setAccountView('closed')
                          logout()
                        }}
                      >
                        <LogOut className="size-4" aria-hidden="true" />
                        {t('auth.logout')}
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </PopoverContent>
          </Popover>
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
          className="fixed left-4 top-4 z-50 size-9 rounded-md border border-border/80 bg-card text-muted-foreground shadow-subtle hover:bg-muted hover:text-foreground"
          onClick={handleSidebarToggle}
        >
          <PanelLeftOpen className="size-4" />
        </Button>
      ) : null}
    </>
  )
}
