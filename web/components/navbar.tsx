/**
 * 左侧固定导航栏组件
 */
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { MessageSquare, Database, Layers, History, Settings, FileText, Share2, Plus, Scissors, BarChart3, Wand2, ShieldCheck, Activity, User, LogIn, LogOut, PanelLeftClose, PanelLeftOpen, Coins, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/ui/status-badge'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { ModeToggle } from '@/components/mode-toggle'
import { useAuth } from '@/hooks/use-auth'
import { useBackendMeta } from '@/hooks/use-backend-meta'
import { useBackendReady } from '@/hooks/use-backend-ready'

type MenuItem = {
  icon: React.ComponentType<{ className?: string }>
  label: string
  href: string
}

type MenuSection = {
  title: string
  items: MenuItem[]
  collapsible?: boolean
  defaultCollapsed?: boolean
}

const menuSections: MenuSection[] = [
  {
    title: '核心',
    items: [
      { icon: MessageSquare, label: '对话', href: '/' },
      { icon: History, label: '问答历史', href: '/history' },
    ],
  },
  {
    title: '数据',
    items: [
      { icon: Layers, label: '数据集', href: '/datasets' },
      { icon: Database, label: '知识库', href: '/knowledge' },
      { icon: Share2, label: '知识图谱', href: '/graph' },
    ],
  },
  {
    title: '工具',
    collapsible: true,
    defaultCollapsed: true,
    items: [
      { icon: FileText, label: '文档解析', href: '/parsing' },
      { icon: Scissors, label: '切块预览', href: '/chunk-preview' },
      { icon: ShieldCheck, label: '数据治理', href: '/data-governance' },
      { icon: BarChart3, label: 'RAGAS 评测', href: '/evaluations' },
      { icon: FileText, label: '报告中心', href: '/reports' },
      { icon: Wand2, label: '提示词', href: '/prompts' },
    ],
  },
  {
    title: '系统',
    collapsible: true,
    defaultCollapsed: true,
    items: [
      { icon: Settings, label: '设置', href: '/settings' },
      { icon: Activity, label: '诊断', href: '/diagnostics' },
      { icon: Coins, label: '用量/配额', href: '/usage' },
      { icon: ShieldCheck, label: '审计日志', href: '/audit' },
    ],
  },
]

const menuItems: MenuItem[] = menuSections.flatMap((s) => s.items)

function isActiveRoute(pathname: string, href: string) {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(`${href}/`)
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
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {}
    for (const s of menuSections) {
      if (s.collapsible && s.defaultCollapsed) initial[s.title] = true
    }
    return initial
  })
  const isSidebarOpen = externalIsOpen ?? internalIsOpen
  const setSidebarOpen = externalSetOpen ?? setInternalIsOpen
  const pathname = usePathname()
  const router = useRouter()
  const { user, isAuthenticated, isDevMode, logout } = useAuth()
  const { data: backendMeta } = useBackendMeta()
  const backendReady = useBackendReady()
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

  // Dev UX: warm up route chunks in the background so first-click navigation feels snappier.
  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return
    if (globalThis.window === undefined) return
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
          'peer flex-shrink-0 bg-sidebar text-sidebar-foreground border-r border-border/50 flex flex-col transition-all duration-200 ease-out z-50',
          'fixed inset-y-0 left-0 md:relative',
          isSidebarOpen ? 'w-[240px] translate-x-0' : 'w-[240px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden'
        )}
      >
        {/* Logo */}
        <div className="h-12 px-4 border-b border-sidebar-border flex items-center gap-2.5">
          <Link href="/" className="flex items-center gap-2.5 group rounded-md focus-ring">
            <div className="size-7 rounded-lg bg-primary text-primary-foreground flex items-center justify-center transition-all duration-150 group-hover:shadow-glow">
              <span className="text-primary-foreground font-bold text-sm">M</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[13px] font-semibold text-foreground leading-none tracking-tight">MimirQ</span>
              <span className="text-2xs text-muted-foreground font-medium mt-0.5">Knowledge Base</span>
            </div>
          </Link>
        </div>

        {/* New Chat */}
        <div className="px-3 pt-3 pb-1">
          <Button
            ref={firstActionRef}
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2"
            onClick={() => {
              router.push('/')
              closeSidebarOnMobile()
            }}
          >
            <Plus className="h-3.5 w-3.5" />
            <span>新对话</span>
          </Button>
        </div>

        {/* Navigation */}
        <div className="flex-1 min-h-0 px-2 py-2 overflow-y-auto overscroll-contain custom-scrollbar">
          <div className="space-y-4">
            {menuSections.map((section) => {
              const isCollapsed = section.collapsible && collapsedSections[section.title]
              const hasActiveChild = section.items.some((item) => isActiveRoute(pathname, item.href))
              const showItems = !isCollapsed || hasActiveChild

              return (
                <div key={section.title} className="space-y-0.5">
                  {section.collapsible ? (
                    <button
                      type="button"
                      onClick={() => setCollapsedSections((prev) => ({ ...prev, [section.title]: !prev[section.title] }))}
                      className="w-full flex items-center justify-between px-2.5 pb-1 text-[11px] font-medium text-muted-foreground/60 uppercase tracking-wider hover:text-muted-foreground transition-colors duration-150"
                    >
                      <span>{section.title}</span>
                      <ChevronRight className={cn("h-3 w-3 transition-transform duration-150", !isCollapsed && "rotate-90")} />
                    </button>
                  ) : (
                    <p className="px-2.5 pb-1 text-[11px] font-medium text-muted-foreground/60 uppercase tracking-wider">
                      {section.title}
                    </p>
                  )}
                  {showItems && section.items.map((item) => {
                    const Icon = item.icon
                    const isActive = isActiveRoute(pathname, item.href)

                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        prefetch
                        onClick={closeSidebarOnMobile}
                        aria-current={isActive ? 'page' : undefined}
                        className={cn(
                          'relative flex items-center gap-2.5 px-2.5 h-8 rounded-md text-[13px] transition-all duration-150 group focus-ring',
                          isActive
                            ? 'bg-accent text-foreground font-medium border-l-2 border-primary -ml-px'
                            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                        )}
                      >
                        <Icon
                          className={cn(
                            "h-4 w-4 shrink-0 transition-colors duration-150",
                            isActive ? "text-primary" : "text-muted-foreground/60 group-hover:text-foreground"
                          )}
                        />
                        <span className="truncate">{item.label}</span>
                      </Link>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-border/50">
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label={isAuthenticated ? "打开设置" : "前往登录 / 注册"}
              title={isAuthenticated ? "打开设置" : "前往登录 / 注册"}
              className="flex-1 flex items-center gap-2.5 p-2 rounded-md hover:bg-accent transition-colors duration-150 group text-left focus-ring"
              onClick={() => {
                if (isAuthenticated) {
                  router.push('/settings')
                } else {
                  router.push('/auth')
                }
                closeSidebarOnMobile()
              }}
            >
              <div className="relative size-8 shrink-0">
                <div className="absolute inset-0 rounded-md bg-muted flex items-center justify-center text-muted-foreground group-hover:text-foreground transition-colors duration-150">
                  <User className="h-4 w-4" />
                </div>
                {isAuthenticated && (
                  <div className="absolute -right-0.5 -bottom-0.5 size-2.5 bg-success border-2 border-sidebar rounded-full" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-medium text-foreground truncate">
                  {user?.username || user?.email || (isDevMode ? '开发模式' : '未登录')}
                </p>
                <p className="text-2xs text-muted-foreground truncate leading-tight">
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
          'fixed bottom-4 z-50 size-8 rounded-md shadow-soft bg-card border border-border/50 text-muted-foreground hover:text-foreground transition-all duration-150',
          isSidebarOpen
            ? 'left-[224px] opacity-0 pointer-events-none md:peer-hover:opacity-100 md:peer-hover:pointer-events-auto md:peer-focus-within:opacity-100 md:peer-focus-within:pointer-events-auto md:hover:opacity-100 md:hover:pointer-events-auto md:focus-visible:opacity-100 md:focus-visible:pointer-events-auto'
            : 'left-4 opacity-100'
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
