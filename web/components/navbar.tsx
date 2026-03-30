/**
 * 左侧固定导航栏组件
 */
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
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
import { useCommandMenuState } from '@/store/command-menu'

type MenuItem = {
  icon: React.ComponentType<{ className?: string }>
  label: string
  href: string
}

// 导航信息架构：按「核心 → 入库流程 → 知识库管理 → 分析工具 → 系统」分组，降低认知负担。
const menuSections: Array<{ title: string; items: MenuItem[] }> = [
  {
    title: '核心',
    items: [
      { icon: MessageSquare, label: '对话', href: '/' },
      { icon: History, label: '问答历史', href: '/history' },
    ],
  },
  {
    title: '入库流程',
    items: [
      { icon: FileText, label: '文档解析', href: '/parsing' },
      { icon: ShieldCheck, label: '数据治理', href: '/data-governance' },
      { icon: Braces, label: '治理配置', href: '/data-governance/profiles' },
      { icon: Hash, label: 'Common Lines 学习', href: '/data-governance/common-lines' },
      { icon: Scissors, label: '切块预览', href: '/chunk-preview' },
    ],
  },
  {
    title: '知识库管理',
    items: [
      { icon: Layers, label: '数据集', href: '/datasets' },
      { icon: Database, label: '知识库', href: '/knowledge' },
      { icon: Activity, label: '入库监控', href: '/knowledge/ingestion' },
      { icon: AlertTriangle, label: '隔离队列', href: '/knowledge/quarantine' },
      { icon: Star, label: '反馈质检', href: '/knowledge/feedback' },
    ],
  },
  {
    title: '分析工具',
    items: [
      { icon: Grid3X3, label: 'RAG 可视化', href: '/knowledge/similarity' },
      { icon: Share2, label: '知识图谱', href: '/graph' },
      { icon: GitCompare, label: 'KG 快照', href: '/graph/snapshots' },
      { icon: FileSearch, label: 'KG 诊断', href: '/graph/diagnostics' },
      { icon: BarChart3, label: 'RAGAS 评测', href: '/evaluations' },
      { icon: SlidersHorizontal, label: '检索消融', href: '/evaluations/ablations' },
      { icon: FileText, label: '报告中心', href: '/reports' },
      { icon: Wand2, label: '提示词', href: '/prompts' },
    ],
  },
  {
    title: '系统',
    items: [
      { icon: Activity, label: '诊断', href: '/diagnostics' },
      { icon: Coins, label: '用量/配额', href: '/usage' },
      { icon: ShieldCheck, label: '审计日志', href: '/audit' },
      { icon: ShieldCheck, label: '访问审查', href: '/access-review' },
      { icon: User, label: '成员权限', href: '/settings/rbac' },
      { icon: Users, label: '组管理', href: '/settings/groups' },
      { icon: Settings, label: '设置', href: '/settings' },
    ],
  },
]

const DEFAULT_OPEN_SECTIONS = new Set(['核心', '知识库管理'])

const menuItems: MenuItem[] = menuSections.flatMap((s) => s.items)

function isActiveRoute(pathname: string, href: string) {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(`${href}/`)
}

function sectionHasActiveRoute(pathname: string, items: MenuItem[]) {
  return items.some((item) => isActiveRoute(pathname, item.href))
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
  const [internalIsOpen, setInternalIsOpen] = useState(true)
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      menuSections.map((section) => [section.title, DEFAULT_OPEN_SECTIONS.has(section.title)] as const)
    )
  )
  const isSidebarOpen = externalIsOpen ?? internalIsOpen
  const setSidebarOpen = externalSetOpen ?? setInternalIsOpen
  const pathname = usePathname()
  const router = useRouter()
  const { user, isAuthenticated, isDevMode, logout } = useAuth()
  const { data: backendMeta } = useBackendMeta()
  const backendReady = useBackendReady()
  const commandMenuOpen = useCommandMenuState((state) => state.open)
  const setCommandMenuOpen = useCommandMenuState((state) => state.setOpen)
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
  const toggleSection = useCallback((sectionTitle: string) => {
    setOpenSections((current) => ({
      ...current,
      [sectionTitle]: !current[sectionTitle],
    }))
  }, [])

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
    if (!shouldRestore) return

    requestAnimationFrame(() => {
      toggleButtonRef.current?.focus()
    })
  }, [isSidebarOpen])

  useEffect(() => {
    const activeSection = menuSections.find((section) => sectionHasActiveRoute(pathname, section.items))
    if (!activeSection) return

    setOpenSections((current) => {
      if (current[activeSection.title]) return current
      return {
        ...current,
        [activeSection.title]: true,
      }
    })
  }, [pathname])

  // Dev UX: warm up route chunks in the background so first-click navigation feels snappier.
  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return
    if (globalThis.window === undefined) return
    if (globalThis.navigator?.webdriver) return
    const key = '__mimirq_routes_prefetched__'
    if ((globalThis.window as any)[key]) return
    ;(globalThis.window as any)[key] = true

    const hrefs = menuItems.map((i) => i.href).filter(Boolean)
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
  }, [router, pathname])

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

  return (
    <>
      {/* Mobile Overlay */}
      {isSidebarOpen ? (
        <button
          type="button"
          aria-label="关闭侧边栏"
          className="fixed inset-0 z-40 bg-black/50 transition-opacity md:hidden border-0 p-0 focus:outline-none"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}

      <nav
        id="mimirq-sidebar"
        ref={navRef}
        aria-label="主导航"
        aria-hidden={!isSidebarOpen}
        className={cn(
          'peer flex-shrink-0 border-r border-sidebar-border/80 bg-sidebar/85 text-sidebar-foreground backdrop-blur-xl supports-[backdrop-filter]:bg-sidebar/72 flex flex-col transition-transform duration-200 ease-out z-50',
          'fixed inset-y-0 left-0 md:relative', // Mobile: fixed, Desktop: relative
          isSidebarOpen ? 'w-[280px] translate-x-0' : 'w-[280px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden'
        )}
      >
        {/* Logo 区域 */}
        <div className="h-16 px-6 border-b border-sidebar-border flex items-center gap-3">
          <Link href="/" className="flex items-center gap-3 group rounded-xl focus-ring">
            <div className="size-8 rounded-xl bg-primary text-primary-foreground flex items-center justify-center shadow-sm border border-primary/20 transition-colors duration-200 group-hover:border-primary/30">
              <span className="text-primary-foreground font-bold text-lg">M</span>
            </div>
            <div className="flex flex-col">
              <span className="font-semibold text-foreground leading-none">MimirQ</span>
              <span className="text-[10px] text-muted-foreground font-medium mt-1">智能知识库</span>
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
              "hover:bg-accent hover:border-border",
              "active:bg-accent/80"
            )}
            onClick={() => {
              router.push('/')
              closeSidebarOnMobile()
            }}
          >
            <Plus className="h-4 w-4" />
            <span>新对话</span>
          </Button>
        </div>

        <div className="px-4 pb-2">
          <button
            type="button"
            className="group flex w-full items-center justify-between gap-3 rounded-2xl border border-dashed border-border/70 bg-background/70 px-3 py-3 text-left transition-colors duration-200 hover:border-primary/40 hover:bg-accent/60 focus-ring"
            onClick={() => {
              setCommandMenuOpen(true)
              closeSidebarOnMobile()
            }}
            aria-label="打开命令搜索"
            aria-haspopup="dialog"
            aria-expanded={commandMenuOpen}
            aria-controls="mimirq-command-menu"
            title="打开命令搜索"
          >
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-xl bg-muted text-muted-foreground transition-colors duration-200 group-hover:bg-primary/10 group-hover:text-primary">
                <Search className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">打开命令搜索</p>
                <p className="text-[11px] text-muted-foreground">快速跳转到页面和常用操作</p>
              </div>
            </div>
            <span className="rounded-lg border border-border bg-card px-2 py-1 text-[11px] font-semibold text-muted-foreground shadow-sm">⌘K</span>
          </button>
        </div>

        {/* 导航菜单 */}
        {/* Allow internal scroll so items are never clipped on short viewports. */}
        <div className="flex-1 min-h-0 px-3 py-2 overflow-y-auto overscroll-contain no-scrollbar">
          <div className="space-y-3">
            {menuSections.map((section, index) => {
              const isOpen = openSections[section.title] ?? false
              const hasActiveItem = sectionHasActiveRoute(pathname, section.items)
              const ToggleIcon = isOpen ? ChevronDown : ChevronRight

              return (
                <section
                  key={section.title}
                  className={cn('space-y-1.5', index > 0 ? 'border-t border-sidebar-border/70 pt-3' : '')}
                >
                  <button
                    type="button"
                    className={cn(
                      'flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left transition-colors duration-200 focus-ring',
                      hasActiveItem ? 'text-foreground' : 'text-muted-foreground hover:bg-muted/30 hover:text-foreground'
                    )}
                    onClick={() => toggleSection(section.title)}
                    aria-expanded={isOpen}
                    aria-controls={`sidebar-section-${section.title}`}
                  >
                    <div className="min-w-0">
                      <p className="text-[11px] font-medium uppercase tracking-[0.18em]">{section.title}</p>
                      <p className="text-[10px] text-muted-foreground">{section.items.length} 个入口</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {hasActiveItem ? (
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">当前</span>
                      ) : null}
                      <ToggleIcon className="h-4 w-4 shrink-0" />
                    </div>
                  </button>

                  <div
                    id={`sidebar-section-${section.title}`}
                    className={cn(
                      'grid overflow-hidden transition-[grid-template-rows,opacity] duration-200 ease-out',
                      isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-70'
                    )}
                  >
                    <div className="overflow-hidden">
                      <div className="space-y-1 pb-1">
                        {section.items.map((item) => {
                          const Icon = item.icon
                          const isActive = isActiveRoute(pathname, item.href)

                          return (
                            <div key={item.href}>
                              <Link
                                href={item.href}
                                prefetch
                                onClick={closeSidebarOnMobile}
                                aria-current={isActive ? 'page' : undefined}
                                className={cn(
                                  'relative flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors duration-200 group focus-ring',
                                  'before:pointer-events-none before:absolute before:left-1 before:top-2 before:bottom-2 before:w-0.5 before:rounded-full before:bg-transparent',
                                  isActive
                                    ? 'bg-muted text-foreground font-medium before:bg-primary/80'
                                    : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                                )}
                              >
                                <Icon
                                  className={cn(
                                    'h-4 w-4 transition-colors',
                                    isActive ? 'text-primary' : 'text-muted-foreground/70 group-hover:text-foreground'
                                  )}
                                />
                                <span className="text-sm">{item.label}</span>
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
        <div className="p-4 border-t border-sidebar-border bg-background/60">
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label={isAuthenticated ? "打开设置" : "前往登录 / 注册"}
              title={isAuthenticated ? "打开设置" : "前往登录 / 注册"}
              className="flex-1 flex items-center gap-3 p-2 rounded-xl hover:bg-accent transition-colors duration-200 border border-transparent hover:border-border group text-left focus-ring"
              onClick={() => {
                if (isAuthenticated) {
                  router.push('/settings')
                } else {
                  router.push('/auth')
                }
                closeSidebarOnMobile()
              }}
            >
              <div className="relative w-10 h-10 flex-shrink-0">
                <div className="absolute inset-0 rounded-xl border border-border bg-muted/50 shadow-sm group-hover:border-primary/30 transition-colors duration-200" />
                <div className="absolute inset-0 flex items-center justify-center text-muted-foreground group-hover:text-primary transition-colors">
                  <User className="h-5 w-5" />
                </div>
                {isAuthenticated && (
                  <div className="absolute -right-0.5 -bottom-0.5 size-3 bg-success border-2 border-background rounded-full" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-foreground truncate group-hover:text-primary transition-colors">
                  {user?.username || user?.email || (isDevMode ? '开发模式' : '未登录')}
                </p>
                <p className="text-[11px] text-muted-foreground truncate leading-tight mt-0.5">
                  {isAuthenticated ? user?.email || '在线' : '本地开发环境'}
                </p>
              </div>
            </button>
            <div className="flex flex-col gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-lg hover:bg-accent hover:text-destructive transition-colors duration-200"
                onClick={() => {
                  if (isAuthenticated) {
                    logout()
                    return
                  }
                  router.push('/auth')
                }}
                title={isAuthenticated ? '退出登录' : '登录 / 注册'}
                aria-label={isAuthenticated ? '退出登录' : '登录 / 注册'}
              >
                {isAuthenticated ? (
                  <LogOut className="h-4 w-4" />
                ) : (
                  <LogIn className="h-4 w-4" />
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
                  aria-label="查看后端依赖状态"
                  title="查看后端依赖状态"
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
                    <p className="font-semibold">依赖就绪</p>
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
                              {row.note ? <div className="text-[10px] text-muted-foreground">{row.note}</div> : null}
                              {errText ? (
                                <div
                                  className="text-[10px] text-muted-foreground max-w-[260px] truncate"
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
                      <p className="text-[11px] text-muted-foreground">未能获取依赖状态（后端未启动或网络不可达）。</p>
                    )}
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    <Link href="/diagnostics" className="text-[11px] text-primary hover:underline">
                      诊断页
                    </Link>
                    <span className="text-[11px] text-muted-foreground">请求包含 X-Request-ID</span>
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </nav>

      {/* 侧边栏折叠按钮 */}
      <Button
        ref={toggleButtonRef}
        variant="ghost"
        size="icon"
        aria-controls="mimirq-sidebar"
        aria-expanded={isSidebarOpen}
        aria-label={isSidebarOpen ? '收起侧边栏' : '展开侧边栏'}
        title={isSidebarOpen ? '收起侧边栏' : '展开侧边栏'}
        className={cn(
          'fixed bottom-4 z-50 size-11 rounded-xl shadow-soft bg-background border border-border text-muted-foreground hover:text-primary hover:bg-muted transition-colors duration-200 ease-out sm:size-10 supports-[padding:env(safe-area-inset-bottom)]:bottom-[calc(env(safe-area-inset-bottom)+1rem)]',
          isSidebarOpen
            ? 'left-[260px] opacity-0 pointer-events-none md:peer-hover:opacity-100 md:peer-hover:pointer-events-auto md:peer-focus-within:opacity-100 md:peer-focus-within:pointer-events-auto md:hover:opacity-100 md:hover:pointer-events-auto md:focus-visible:opacity-100 md:focus-visible:pointer-events-auto'
            : 'left-4 opacity-100 supports-[padding:env(safe-area-inset-left)]:left-[calc(env(safe-area-inset-left)+1rem)]'
        )}
        onClick={() => setSidebarOpen(!isSidebarOpen)}
      >
        {isSidebarOpen ? (
          <PanelLeftClose className="h-5 w-5" />
        ) : (
          <PanelLeftOpen className="h-5 w-5" />
        )}
      </Button>
    </>
  )
}
