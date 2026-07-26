'use client'

import {
  ArrowRightLeft,
  BarChart3,
  Network,
  Search,
  Table2,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import type { SnapshotView, StudioCanvasView } from '../types'

export function SnapshotStudioToolbar({
  searchValue,
  nodeType,
  relationType,
  nodeTypes,
  relationTypes,
  layout,
  studioView,
  activeSnapshotView,
  onSearchChange,
  onNodeTypeChange,
  onRelationTypeChange,
  onLayoutChange,
  onStudioViewChange,
  onSnapshotViewChange,
  onDiffClick,
  isRunning,
}: Readonly<{
  searchValue: string
  nodeType: string
  relationType: string
  nodeTypes: string[]
  relationTypes: string[]
  layout: string
  studioView: StudioCanvasView
  activeSnapshotView: SnapshotView
  onSearchChange: (value: string) => void
  onNodeTypeChange: (value: string) => void
  onRelationTypeChange: (value: string) => void
  onLayoutChange: (value: string) => void
  onStudioViewChange: (value: StudioCanvasView) => void
  onSnapshotViewChange: (value: SnapshotView) => void
  onDiffClick: () => void
  isRunning: boolean
}>) {
  const selectClassName =
    'h-8 rounded-full border border-border/40 bg-background/58 px-2.5 text-[11.5px] font-medium text-foreground/82 shadow-none outline-none transition-colors hover:border-primary/24 hover:bg-background/76 focus:ring-2 focus:ring-primary/12'

  return (
    <div className="shrink-0 border-b border-border/44 bg-background/82 px-4 py-2.5 backdrop-blur">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto no-scrollbar">
          <div className="relative w-[156px] shrink-0 xl:w-[176px] 2xl:w-[196px]">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/70"
              aria-hidden="true"
            />
            <Input
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="搜索节点 / 关系"
              className="h-8 rounded-full border-border/40 bg-background/58 pl-9 pr-2 text-[11.5px] shadow-none"
            />
          </div>

          <div className="inline-flex shrink-0 items-center gap-1.5">
            <select
              aria-label="节点类型"
              value={nodeType}
              onChange={(event) => onNodeTypeChange(event.target.value)}
              className={cn(selectClassName, 'w-[86px] shrink-0')}
            >
              <option value="all">节点类型</option>
              {nodeTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>

            <select
              aria-label="关系类型"
              value={relationType}
              onChange={(event) => onRelationTypeChange(event.target.value)}
              className={cn(selectClassName, 'w-[86px] shrink-0')}
            >
              <option value="all">关系类型</option>
              {relationTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>

          <select
            aria-label="布局"
            value={layout}
            onChange={(event) => onLayoutChange(event.target.value)}
            className={cn(selectClassName, 'w-[68px] shrink-0')}
          >
            <option value="force">布局</option>
            <option value="radial">径向</option>
            <option value="layered">分层</option>
          </select>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <div className="grid h-8 shrink-0 grid-cols-3 gap-1 rounded-full border border-border/38 bg-card/58 p-1 shadow-[inset_0_1px_0_hsl(var(--card)/0.62)]">
            {[
              {
                value: 'graph',
                label: '图谱视图',
                compactLabel: '图谱',
                icon: <Network className="h-3.5 w-3.5" aria-hidden="true" />,
              },
              {
                value: 'table',
                label: '表格视图',
                compactLabel: '表格',
                icon: <Table2 className="h-3.5 w-3.5" aria-hidden="true" />,
              },
              {
                value: 'stats',
                label: '统计视图',
                compactLabel: '统计',
                icon: <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />,
              },
            ].map((item) => (
              <button
                key={item.value}
                type="button"
                className={cn(
                  'inline-flex items-center justify-center gap-1 rounded-full px-2 text-[11.5px] font-semibold transition-colors',
                  studioView === item.value
                    ? 'bg-info text-primary-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                )}
                onClick={() =>
                  onStudioViewChange(item.value as StudioCanvasView)
                }
              >
                <span className="hidden 2xl:inline-flex">{item.icon}</span>
                <span className="hidden 2xl:inline">{item.label}</span>
                <span className="2xl:hidden">{item.compactLabel}</span>
              </button>
            ))}
          </div>

          <Button
            variant="outline"
            className="h-8 shrink-0 gap-1.5 rounded-full border-info/22 bg-info/[0.09] px-2.5 text-[11.5px] font-semibold text-info shadow-none hover:border-info/34 hover:bg-info/[0.15] hover:text-info 2xl:px-3"
            onClick={onDiffClick}
            disabled={isRunning}
          >
            <ArrowRightLeft
              className={cn('h-3.5 w-3.5', isRunning && 'animate-spin')}
              aria-hidden="true"
            />
            <span className="hidden 2xl:inline">Diff 对比</span>
            <span className="2xl:hidden">Diff</span>
          </Button>

          <div className="grid h-8 shrink-0 grid-cols-2 gap-1 rounded-full border border-border/38 bg-card/58 p-1 shadow-[inset_0_1px_0_hsl(var(--card)/0.62)]">
            <button
              type="button"
              className={cn(
                'inline-flex items-center justify-center gap-1 rounded-full px-2 text-[11.5px] font-medium transition-colors',
                activeSnapshotView === 'a'
                  ? 'bg-success/10 text-success'
                  : 'text-muted-foreground hover:bg-muted/50'
              )}
              onClick={() => onSnapshotViewChange('a')}
            >
              <span className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-success/15 text-[10px] font-bold text-success">
                A
              </span>
              <span className="hidden 2xl:inline">视图 A</span>
            </button>
            <button
              type="button"
              className={cn(
                'inline-flex items-center justify-center gap-1 rounded-full px-2 text-[11.5px] font-medium transition-colors',
                activeSnapshotView === 'b'
                  ? 'bg-info/10 text-info'
                  : 'text-muted-foreground hover:bg-muted/50'
              )}
              onClick={() => onSnapshotViewChange('b')}
            >
              <span className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-info/15 text-[10px] font-bold text-info">
                B
              </span>
              <span className="hidden 2xl:inline">视图 B</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
