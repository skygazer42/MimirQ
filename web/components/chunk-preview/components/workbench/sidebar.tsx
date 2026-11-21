'use client'

import dynamic from 'next/dynamic'

export const Sidebar = dynamic(() => import('./sidebar-client').then((mod) => mod.Sidebar), {
  ssr: false,
  loading: () => (
    <div
      role="status"
      className="flex min-h-0 w-full flex-1 items-center justify-center py-10 text-[13px] text-muted-foreground"
    >
      正在读取配置…
    </div>
  ),
})
