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
  Wand2,
  ShieldCheck,
  User,
  LogIn,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ModeToggle } from '@/components/mode-toggle'
import { healthApi } from '@/lib/api-client'
import { useAuth } from '@/hooks/use-auth'

// 导航菜单配置
const menuItems = [
  {
    icon: MessageSquare,
    label: '对话',
    href: '/',
  },
  {
    icon: Database,
    label: '知识库',
    href: '/knowledge',
  },
  {
    icon: Layers,
    label: '数据集',
    href: '/datasets',
  },
  {
    icon: History,
    label: '问答历史',
    href: '/history',
  },
  {
    icon: FileText,
    label: '文档解析',
    href: '/parsing',
  },
  {
    icon: ShieldCheck,
    label: '数据治理',
    href: '/data-governance',
  },
  {
    icon: Scissors,
    label: '切块预览',
    href: '/chunk-preview',
  },
  {
    icon: Share2,
    label: '知识图谱',
    href: '/graph',
  },
  {
    icon: BarChart3,
    label: 'RAGAS 评测',
    href: '/evaluations',
  },
  {
    icon: Wand2,
    label: '提示词',
    href: '/prompts',
  },
  {
    icon: Settings,
    label: '设置',
    href: '/settings',
  },
]

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
      {isSidebarOpen && (
        <div 
            className="fixed inset-0 bg-black/50 z-40 md:hidden backdrop-blur-sm transition-opacity"
            onClick={() => setSidebarOpen(false)}
        />
      )}

      <nav
        className={cn(
          'flex-shrink-0 bg-white dark:bg-slate-950 border-r border-slate-100 dark:border-slate-800 flex flex-col transition-all duration-300 ease-in-out z-50',
          'fixed inset-y-0 left-0 md:relative', // Mobile: fixed, Desktop: relative
          isSidebarOpen ? 'w-[280px] translate-x-0' : 'w-[280px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden'
        )}
      >
        {/* Logo 区域 */}
        <div className="h-16 px-6 border-b border-slate-50 dark:border-slate-800 flex items-center gap-3">
          <Link href="/" className="flex items-center gap-3 group">
            <div className="w-8 h-8 bg-gradient-to-br from-primary to-primary/80 rounded-xl flex items-center justify-center shadow-sm group-hover:shadow-lg group-hover:shadow-primary/30 transition-all duration-300 group-hover:scale-105">
              <span className="text-primary-foreground font-bold text-lg">M</span>
            </div>
            <div className="flex flex-col">
              <span className="font-bold text-slate-900 dark:text-slate-100 leading-none tracking-tight">MimirQ</span>
              <span className="text-[10px] text-slate-500 dark:text-slate-400 font-medium tracking-wide mt-1">智能知识库</span>
            </div>
          </Link>
        </div>

        {/* 新对话按钮 */}
        <div className="p-4 pb-2">
          <Button
            className={cn(
              "w-full justify-start gap-2 h-11 rounded-2xl font-semibold transition-all duration-300",
              // Softer, more neutral “glass” look to match the page theme.
              "bg-white/70 dark:bg-slate-900/60 backdrop-blur-xl",
              "border border-slate-200/70 dark:border-slate-700/70",
              "text-slate-900 dark:text-slate-100",
              // Subtle tint + lift on hover (keeps brand feel without being too blue).
              "hover:bg-gradient-to-r hover:from-sky-50/80 hover:via-white hover:to-teal-50/70",
              "dark:hover:from-sky-950/30 dark:hover:via-slate-900/40 dark:hover:to-teal-950/25",
              "shadow-sm hover:shadow-md hover:shadow-sky-500/10",
              "hover:-translate-y-0.5 active:translate-y-0"
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
        <div className="flex-1 px-3 py-2 overflow-y-auto">
          <div className="space-y-1">
            <p className="px-3 text-xs font-semibold text-slate-400 dark:text-slate-500 mb-2 uppercase tracking-wider">菜单</p>
            {menuItems.map((item) => {
              const Icon = item.icon
              const isActive = pathname === item.href

              return (
                <div key={item.href}>
                  <Link
                    href={item.href}
                    prefetch
                    onClick={closeSidebarOnMobile}
                    aria-current={isActive ? 'page' : undefined}
                    className={cn(
                      'flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group',
                      isActive
                        ? 'bg-slate-100 dark:bg-slate-800/50 text-slate-900 dark:text-slate-100 font-medium'
                        : 'text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50 hover:text-slate-900 dark:hover:text-slate-100'
                    )}
                  >
                    <Icon className={cn("h-4 w-4 transition-colors", isActive ? "text-slate-900 dark:text-slate-100" : "text-slate-400 dark:text-slate-500 group-hover:text-slate-600 dark:group-hover:text-slate-300")} />
                    <span className="text-sm">{item.label}</span>
                  </Link>
                </div>
              )
            })}
          </div>
        </div>

        {/* 底部信息 */}
        <div className="p-4 border-t border-slate-100 dark:border-slate-800 bg-slate-50/30 dark:bg-slate-900/20">
          <div className="flex items-center gap-2">
            <div className="flex-1 flex items-center gap-3 p-2 rounded-xl hover:bg-white dark:hover:bg-slate-800/80 hover:shadow-md hover:shadow-slate-200/50 dark:hover:shadow-none transition-all duration-300 border border-transparent hover:border-slate-200 dark:hover:border-slate-700 group cursor-pointer">
              <div className="relative w-10 h-10 flex-shrink-0">
                <div className="absolute inset-0 bg-gradient-to-tr from-slate-100 to-slate-50 dark:from-slate-800 dark:to-slate-700 rounded-xl border border-slate-200 dark:border-slate-600 shadow-sm group-hover:border-primary/30 transition-colors" />
                <div className="absolute inset-0 flex items-center justify-center text-slate-500 dark:text-slate-400 group-hover:text-primary transition-colors">
                  <User className="h-5 w-5" />
                </div>
                {isAuthenticated && (
                  <div className="absolute -right-0.5 -bottom-0.5 w-3 h-3 bg-green-500 border-2 border-white dark:border-slate-900 rounded-full" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 truncate group-hover:text-primary transition-colors">
                  {user?.username || user?.email || (isDevMode ? '开发模式' : '未登录')}
                </p>
                <p className="text-[11px] text-slate-400 dark:text-slate-500 truncate leading-tight mt-0.5">
                  {isAuthenticated ? user?.email || '在线' : '本地开发环境'}
                </p>
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-lg hover:bg-white dark:hover:bg-slate-800 hover:text-red-500 transition-colors"
                onClick={() => {
                  if (isAuthenticated) {
                    logout()
                    return
                  }
                  router.push('/auth')
                }}
                title={isAuthenticated ? '退出登录' : '登录 / 注册'}
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

          <div className="mt-2 flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
            <span
              className={cn(
                'inline-block h-2 w-2 rounded-full',
                backendOk === true && 'bg-green-500',
                backendOk === false && 'bg-red-500',
                backendOk === null && 'bg-slate-300 dark:bg-slate-600'
              )}
            />
            <span>
              Backend：{backendOk === true ? 'OK' : backendOk === false ? 'Down' : '...'}
            </span>
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
          'fixed bottom-4 z-50 h-10 w-10 rounded-xl shadow-sm bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-500 hover:text-primary transition-all duration-300 ease-in-out',
          isSidebarOpen ? 'left-[260px] opacity-0 group-hover:opacity-100 hover:opacity-100' : 'left-4 opacity-100'
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