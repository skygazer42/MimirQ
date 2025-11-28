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
  Plus,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

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
    icon: Settings,
    label: '设置',
    href: '/settings',
  },
]

export function Navbar() {
  const pathname = usePathname()

  return (
    <nav className="w-64 h-screen bg-gray-50 border-r border-gray-200 flex flex-col">
      {/* Logo 区域 */}
      <div className="p-6 border-b border-gray-200">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center shadow-md group-hover:shadow-lg transition-shadow">
            <span className="text-white font-bold text-xl">M</span>
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">MimirQ</h1>
            <p className="text-xs text-gray-500">智能知识库</p>
          </div>
        </Link>
      </div>

      {/* 新对话按钮 */}
      <div className="p-4">
        <Button
          className="w-full bg-blue-600 hover:bg-blue-700 text-white shadow-sm"
          size="lg"
        >
          <Plus className="h-5 w-5 mr-2" />
          新对话
        </Button>
      </div>

      {/* 导航菜单 */}
      <div className="flex-1 px-3 py-2 overflow-y-auto">
        <ul className="space-y-1">
          {menuItems.map((item) => {
            const Icon = item.icon
            const isActive = pathname === item.href

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 px-4 py-3 rounded-lg transition-colors',
                    'hover:bg-gray-100 active:bg-gray-200',
                    isActive
                      ? 'bg-blue-50 text-blue-600 font-medium'
                      : 'text-gray-700'
                  )}
                >
                  <Icon className="h-5 w-5 flex-shrink-0" />
                  <span className="text-sm">{item.label}</span>
                </Link>
              </li>
            )
          })}
        </ul>
      </div>

      {/* 底部信息 */}
      <div className="p-4 border-t border-gray-200 bg-white">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-green-400 to-blue-500 rounded-full flex items-center justify-center text-white text-sm font-medium">
            U
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-900 truncate">用户</p>
            <p className="text-xs text-gray-500">免费版</p>
          </div>
        </div>
      </div>
    </nav>
  )
}
