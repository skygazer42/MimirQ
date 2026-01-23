/**
 * 左侧固定导航栏组件
 */
'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import {
  MessageSquare,
  Database,
  Activity,
  Layers,
  History,
  Settings,
  FileText,
  Share2,
  Plus,
  Scissors,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  Star,
  Wand2,
  ShieldCheck,
  AlertTriangle,
  Grid3X3,
  User,
  LogIn,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/ui/status-badge'
import { cn } from '@/lib/utils'
import { ModeToggle } from '@/components/mode-toggle'
import { healthApi } from '@/lib/api-client'
import { useAuth } from '@/hooks/use-auth'

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
      { icon: BarChart3, label: 'RAGAS 评测', href: '/evaluations' },
      { icon: Wand2, label: '提示词', href: '/prompts' },
    ],
  },
  {
    title: '系统',
    items: [{ icon: Settings, label: '设置', href: '/settings' }],
  },
]

const menuItems: MenuItem[] = menuSections.flatMap((s) => s.items)

function isActiveRoute(pathname: string, href: string) {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function Navbar({
  isSidebarOpen: externalIsOpen,
  setSidebarOpen: externalSetOpen,
}: {
  isSidebarOpen?: boolean
  setSidebarOpen?: (isOpen: boolean) => void
} = {}) {
  const [internalIsOpen, setInternalIsOpen] = useState(true)
  const isSidebarOpen = externalIsOpen ?? internalIsOpen
  const setSidebarOpen = externalSetOpen ?? setInternalIsOpen
  const pathname = usePathname()
  const router = useRouter()
  const [backendOk, setBackendOk] = useState<boolean | null>(null)
  const { user, isAuthenticated, isDevMode, logout } = useAuth()
  const closeSidebarOnMobile = useCallback(() => {
    if (typeof window === 'undefined') return
    try {
      if (window.matchMedia('(max-width: 768px)').matches) setSidebarOpen(false)
    } catch {
      // ignore
    }
  }, [setSidebarOpen])

  // Dev UX: warm up route chunks in the background so first-click navigation feels snappier.
  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return
    if (typeof window === 'undefined') return
    const key = '__mimirq_routes_prefetched__'
    if ((window as any)[key]) return
    ;(window as any)[key] = true

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
    const w = window as any
    if (typeof w.requestIdleCallback === 'function') {
      const id = w.requestIdleCallback(prefetchAll, { timeout: 2000 })
      return () => w.cancelIdleCallback?.(id)
    }

    const t = setTimeout(prefetchAll, 800)
    return () => clearTimeout(t)
  }, [router, pathname])

  useEffect(() => {
    let alive = true
    const ping = async () => {
      try {
        if (!alive) return
        await healthApi.health()
        if (!alive) return
        setBackendOk(true)
      } catch {
        if (!alive) return
        setBackendOk(false)
      }
    }
    ping()
    const t = setInterval(ping, 30_000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  return (
    <>
      {/* Mobile Overlay */}
      {isSidebarOpen ? (
        <button
          type="button"
          aria-label="关闭侧边栏"
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity md:hidden border-0 p-0 focus:outline-none"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}

      <nav
        aria-label="主导航"
        className={cn(
          'peer flex-shrink-0 bg-sidebar text-sidebar-foreground border-r border-sidebar-border flex flex-col transition-all duration-300 ease-in-out z-50',
          'fixed inset-y-0 left-0 md:relative', // Mobile: fixed, Desktop: relative
          isSidebarOpen ? 'w-[280px] translate-x-0' : 'w-[280px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden'
        )}
      >
        {/* Logo 区域 */}
        <div className="h-16 px-6 border-b border-sidebar-border flex items-center gap-3">
          <Link href="/" className="flex items-center gap-3 group rounded-xl focus-ring">
            <div className="w-8 h-8 bg-gradient-to-br from-primary to-primary/80 rounded-xl flex items-center justify-center shadow-sm group-hover:shadow-lg group-hover:shadow-primary/30 transition-all duration-300 motion-safe:group-hover:scale-105">
              <span className="text-primary-foreground font-bold text-lg">M</span>
            </div>
            <div className="flex flex-col">
              <span className="font-bold text-foreground leading-none tracking-tight">MimirQ</span>
              <span className="text-[10px] text-muted-foreground font-medium tracking-wide mt-1">智能知识库</span>
            </div>
          </Link>
        </div>

        {/* 新对话按钮 */}
        <div className="p-4 pb-2">
          <Button
            className={cn(
              "w-full justify-start gap-2 h-11 rounded-2xl font-semibold transition-all duration-300",
              // Softer, more neutral “glass” look to match the page theme.
              "bg-card/70 backdrop-blur-xl",
              "border border-border/70",
              "text-foreground",
              // Subtle tint + lift on hover (keeps brand feel without being too blue).
              "hover:bg-gradient-to-r hover:from-sky-50/80 hover:via-white hover:to-teal-50/70",
              "dark:hover:from-sky-950/30 dark:hover:via-slate-900/40 dark:hover:to-teal-950/25",
              "shadow-sm hover:shadow-md hover:shadow-sky-500/10",
              "motion-safe:hover:-translate-y-0.5 motion-safe:active:translate-y-0"
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

        {/* 导航菜单 */}
        {/* Allow internal scroll so items are never clipped on short viewports. */}
        <div className="flex-1 min-h-0 px-3 py-2 overflow-y-auto overscroll-contain no-scrollbar">
          <div className="space-y-4">
            {menuSections.map((section) => (
              <div key={section.title} className="space-y-1">
                <p className="px-3 text-[11px] font-semibold text-muted-foreground mb-2 uppercase tracking-wider">
                  {section.title}
                </p>
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
                          'flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group focus-ring',
                          isActive
                            ? 'bg-muted text-foreground font-medium'
                            : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                        )}
                      >
                        <Icon className={cn("h-4 w-4 transition-colors", isActive ? "text-foreground" : "text-muted-foreground/70 group-hover:text-foreground")} />
                        <span className="text-sm">{item.label}</span>
                      </Link>
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>

        {/* 底部信息 */}
        <div className="p-4 border-t border-sidebar-border bg-background/60">
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label={isAuthenticated ? "打开设置" : "前往登录 / 注册"}
              title={isAuthenticated ? "打开设置" : "前往登录 / 注册"}
              className="flex-1 flex items-center gap-3 p-2 rounded-xl hover:bg-accent transition-all duration-200 border border-transparent hover:border-border group text-left focus-ring"
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
                <div className="absolute inset-0 bg-gradient-to-tr from-muted to-background rounded-xl border border-border shadow-sm group-hover:border-primary/30 transition-colors" />
                <div className="absolute inset-0 flex items-center justify-center text-muted-foreground group-hover:text-primary transition-colors">
                  <User className="h-5 w-5" />
                </div>
                {isAuthenticated && (
                  <div className="absolute -right-0.5 -bottom-0.5 w-3 h-3 bg-green-500 border-2 border-background rounded-full" />
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
                className="h-8 w-8 rounded-lg hover:bg-accent hover:text-red-500 transition-colors"
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
            <StatusBadge
              status={backendOk === true ? "completed" : backendOk === false ? "failed" : "processing"}
              label={`Backend：${backendOk === true ? "OK" : backendOk === false ? "Down" : "..."}`}
              dense
            />
          </div>
        </div>
      </nav>

      {/* 侧边栏折叠按钮 */}
      <Button
        variant="ghost"
        size="icon"
        aria-label={isSidebarOpen ? '收起侧边栏' : '展开侧边栏'}
        title={isSidebarOpen ? '收起侧边栏' : '展开侧边栏'}
        className={cn(
          'fixed bottom-4 z-50 h-11 w-11 rounded-xl shadow-soft bg-background border border-border text-muted-foreground hover:text-primary hover:bg-muted transition-all duration-200 ease-in-out sm:h-10 sm:w-10',
          isSidebarOpen
            ? 'left-[260px] opacity-0 pointer-events-none md:peer-hover:opacity-100 md:peer-hover:pointer-events-auto md:peer-focus-within:opacity-100 md:peer-focus-within:pointer-events-auto md:hover:opacity-100 md:hover:pointer-events-auto'
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
