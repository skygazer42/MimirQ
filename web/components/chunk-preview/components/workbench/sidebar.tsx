/**
 * Sidebar - 左侧配置栏
 */
'use client'

import dynamic from 'next/dynamic'

type SidebarVariant = 'panel' | 'dialog' | 'pane'
type SidebarProps = Readonly<{ variant?: SidebarVariant }>

const ChunkPreviewSidebarClient = dynamic(
  () => import('./sidebar-client').then((mod) => mod.Sidebar),
  {
    ssr: false,
    loading: () => <div className="h-full w-full rounded-2xl border border-border/60 bg-muted/20 animate-pulse" />,
  }
)

export function Sidebar(props: SidebarProps = {}) {
  return <ChunkPreviewSidebarClient {...props} />
}
