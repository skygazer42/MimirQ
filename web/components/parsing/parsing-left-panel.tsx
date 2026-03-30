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
        'group/sidebar relative flex flex-col flex-shrink-0 min-h-0 overflow-hidden bg-card dark:bg-background border-r border-border/60 z-10',
        collapsed ? 'w-0 border-r-0' : 'w-80',
        className
      )}
      style={{ width: collapsed ? 0 : 320 }}
    >
      <Button
        variant="ghost"
        size="icon"
        className={cn(
          'absolute -right-3 top-3 z-30 h-6 w-6 rounded-full border border-border/60 bg-card shadow-sm dark:shadow-none hover:bg-muted dark:hover:bg-muted text-muted-foreground hover:text-muted-foreground transition-opacity opacity-0 group-hover/sidebar:opacity-100 motion-reduce:transition-none',
          collapsed && 'opacity-100 -right-8 translate-x-2'
        )}
        onClick={onToggleCollapsed}
        title={collapsed ? t('leftPanel.expandSidebar') : t('leftPanel.collapseSidebar')}
        aria-label={collapsed ? t('leftPanel.expandSidebar') : t('leftPanel.collapseSidebar')}
      >
        {collapsed ? <PanelRightOpen className="w-3 h-3" /> : <PanelRightClose className="w-3 h-3" />}
      </Button>

      <div className={cn('flex-1 flex flex-col min-h-0 w-full overflow-hidden', collapsed && 'invisible')}>
        {children}
      </div>
    </aside>
  )
}
