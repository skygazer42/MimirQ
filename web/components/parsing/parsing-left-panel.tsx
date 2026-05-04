'use client'

import { PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

type ParsingLeftPanelProps = {
 collapsed: boolean
 onToggleCollapsed: () => void
 children: React.ReactNode
 className?: string
}

export function ParsingLeftPanel({
 collapsed,
 onToggleCollapsed,
 children,
 className,
}: Readonly<ParsingLeftPanelProps>) {
 const t = useTranslations('ParsingWorkbench')

 return (
 <aside
 className={cn(
 'group/sidebar relative z-10 flex min-h-0 flex-shrink-0 flex-col overflow-visible border-r border-border/60 bg-card dark:bg-background',
 collapsed ? 'w-0 border-r-0' : 'w-60',
 className
 )}
 style={{ width: collapsed ? 0 : 240 }}
 >
 <Button
 variant="ghost"
 size="icon"
 className={cn(
 'absolute top-2 z-30 h-6 w-6 rounded-lg border border-border/60 bg-card text-muted-foreground shadow-none backdrop-blur-sm transition-all duration-200 hover:bg-muted hover:text-foreground motion-reduce:transition-none',
 collapsed ? 'right-[-2.25rem] opacity-100' : 'right-2 opacity-0 group-hover/sidebar:opacity-100'
 )}
 onClick={onToggleCollapsed}
 title={collapsed ? t('leftPanel.expandSidebar') : t('leftPanel.collapseSidebar')}
 aria-label={collapsed ? t('leftPanel.expandSidebar') : t('leftPanel.collapseSidebar')}
 >
 {collapsed ? <PanelRightOpen className="w-3 h-3" /> : <PanelRightClose className="w-3 h-3" />}
 </Button>

 <div className={cn('flex min-h-0 w-full flex-1 flex-col overflow-hidden', collapsed && 'invisible')}>
 {children}
 </div>
 </aside>
 )
}
