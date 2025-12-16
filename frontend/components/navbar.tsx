/**
 * 左侧固定导航栏组件
 */
'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  MessageSquare,
  Database,
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
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ModeToggle } from '@/components/mode-toggle'

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
    icon: Scissors,
    label: '切块预览',
    href: '/chunk-preview',
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

  return (
    <>
      <nav
        className={cn(
          'flex-shrink-0 bg-white dark:bg-slate-950 border-r border-slate-100 dark:border-slate-800 flex flex-col transition-all duration-300 ease-in-out relative z-50',
          isSidebarOpen ? 'w-[280px]' : 'w-0 overflow-hidden'
        )}
      >
        {/* Logo 区域 */}
        <div className="h-16 px-6 border-b border-slate-50 dark:border-slate-800 flex items-center gap-3">
          <Link href="/" className="flex items-center gap-3 group">
            <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center shadow-sm group-hover:shadow-md transition-all duration-300">
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
            className="w-full justify-start gap-2 bg-primary hover:bg-primary/90 text-primary-foreground shadow-sm h-10 rounded-xl transition-all"
            onClick={() => setSidebarOpen(false)}
          >
            <Plus className="h-4 w-4" />
            <span className="font-medium">新对话</span>
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
                    onClick={() => setSidebarOpen(false)}
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
        <div className="p-4 border-t border-slate-50 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/30">
          <div className="flex items-center gap-2">
            <div className="flex-1 flex items-center gap-3 p-2 rounded-xl hover:bg-white dark:hover:bg-slate-800 hover:shadow-sm transition-all cursor-pointer border border-transparent hover:border-slate-100 dark:hover:border-slate-700">
              <div className="w-9 h-9 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center text-white text-sm font-bold shadow-inner">
                U
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 truncate">用户</p>
                <p className="text-xs text-slate-400 dark:text-slate-500 truncate">专业版</p>
              </div>
            </div>
            <ModeToggle />
          </div>
        </div>
      </nav>

      {/* 侧边栏折叠按钮 */}
      <Button
        variant="ghost"
        size="icon"
        className={cn(
          'fixed top-1/2 -translate-y-1/2 z-50 rounded-full shadow-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700 transition-all duration-300 ease-in-out',
          isSidebarOpen ? 'left-[260px]' : 'left-4'
        )}
        onClick={() => setSidebarOpen(!isSidebarOpen)}
      >
        {isSidebarOpen ? (
          <ChevronLeft className="h-4 w-4 text-slate-600 dark:text-slate-300" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-600 dark:text-slate-300" />
        )}
      </Button>
    </>
  )
}
