'use client'

import { useState } from 'react'

import {
  Box,
  BoxSelect,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Layout,
  Maximize,
  Maximize2,
  Minimize2,
  PlayCircle,
  Route,
  Type,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

type GraphFloatingControlsProps = Readonly<{
  viewMode: '2d' | '3d'
  isExplainMode: boolean
  isPathMode: boolean
  showEdgeLabels: boolean
  isFullscreen: boolean
  exportOpen: boolean
  layoutLabel: string
  onZoomIn: () => void
  onZoomOut: () => void
  onZoomToFit: () => void
  onToggleViewMode: () => void
  onStartExplainMode: () => void
  onCycleLayoutMode: () => void
  onTogglePathMode: () => void
  onToggleShowEdgeLabels: () => void
  onToggleFullscreen: () => void
  onExportOpenChange: (open: boolean) => void
  onExportPngDownload: () => void
  onExportSvgDownload: () => void
  onExportPngCopy: () => void
  onExportSvgCopy: () => void
}>

export function GraphFloatingControls({
  viewMode,
  isExplainMode,
  isPathMode,
  showEdgeLabels,
  isFullscreen,
  exportOpen,
  layoutLabel,
  onZoomIn,
  onZoomOut,
  onZoomToFit,
  onToggleViewMode,
  onStartExplainMode,
  onCycleLayoutMode,
  onTogglePathMode,
  onToggleShowEdgeLabels,
  onToggleFullscreen,
  onExportOpenChange,
  onExportPngDownload,
  onExportSvgDownload,
  onExportPngCopy,
  onExportSvgCopy,
}: GraphFloatingControlsProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)

  return (
    <div className="absolute bottom-8 right-8 z-10 flex items-end gap-2">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-10 w-10 rounded-xl border border-border/60 bg-card/92 text-muted-foreground shadow-soft backdrop-blur-sm hover:bg-card hover:text-foreground"
        title={isCollapsed ? '展开工具栏' : '收起工具栏'}
        aria-label={isCollapsed ? '展开工具栏' : '收起工具栏'}
        aria-expanded={!isCollapsed}
        onClick={() => {
          if (!isCollapsed && exportOpen) {
            onExportOpenChange(false)
          }
          setIsCollapsed((value) => !value)
        }}
      >
        {isCollapsed ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </Button>

      <div
        className={cn(
          'overflow-hidden transition-[width,opacity,transform] duration-200 ease-out',
          isCollapsed ? 'w-0 translate-x-2 opacity-0 pointer-events-none' : 'w-[3.125rem] translate-x-0 opacity-100'
        )}
      >
        <div className="flex w-[3.125rem] flex-col gap-1 rounded-xl border border-border/60 bg-card/92 p-1.5 shadow-soft backdrop-blur-sm">
          <Button variant="ghost" size="icon" onClick={onZoomIn} className="rounded-lg" title="放大" aria-label="放大">
            <ZoomIn className="w-5 h-5" />
          </Button>
          <Button variant="ghost" size="icon" onClick={onZoomOut} className="rounded-lg" title="缩小" aria-label="缩小">
            <ZoomOut className="w-5 h-5" />
          </Button>
          <div className="h-px bg-muted mx-2 my-0.5" />
          <Button variant="ghost" size="icon" onClick={onZoomToFit} className="rounded-lg" title="适应屏幕" aria-label="适应屏幕">
            <Maximize className="w-5 h-5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleViewMode}
            className={cn('rounded-lg', viewMode === '3d' && 'bg-primary/10 text-primary ring-1 ring-primary/20')}
            title={viewMode === '3d' ? '切换至 2D 平面' : '切换至 3D 空间'}
            aria-label={viewMode === '3d' ? '切换至 2D 平面' : '切换至 3D 空间'}
          >
            {viewMode === '3d' ? <Box className="w-5 h-5" /> : <BoxSelect className="w-5 h-5" />}
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={onStartExplainMode}
            className={cn('rounded-lg', isExplainMode && 'bg-primary/10 text-primary ring-1 ring-primary/20')}
            title="推理演示 (Explain)"
            aria-label="推理演示"
          >
            <PlayCircle className="w-5 h-5" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={onCycleLayoutMode}
            className="rounded-lg"
            title={`切换布局: ${layoutLabel}`}
            aria-label={`切换布局：${layoutLabel}`}
          >
            <Layout className="w-5 h-5" />
            <span className="sr-only">{layoutLabel}</span>
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={onTogglePathMode}
            className={cn('rounded-lg', isPathMode && 'bg-primary/10 text-primary ring-1 ring-primary/20')}
            title="路径发现 (Shortest Path)"
            aria-label="路径发现"
          >
            <Route className="w-5 h-5" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleShowEdgeLabels}
            className={cn('rounded-lg', showEdgeLabels && 'bg-primary/10 text-primary ring-1 ring-primary/20')}
            title="显示/隐藏连线标签"
            aria-label="显示或隐藏连线标签"
          >
            <Type className="w-5 h-5" />
          </Button>
          <div className="h-px bg-muted mx-2 my-0.5" />

          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleFullscreen}
            className={cn('rounded-lg', isFullscreen && 'bg-primary/10 text-primary ring-1 ring-primary/20')}
            title={isFullscreen ? '退出全屏' : '全屏模式'}
            aria-label={isFullscreen ? '退出全屏模式' : '进入全屏模式'}
          >
            {isFullscreen ? <Minimize2 className="w-5 h-5" /> : <Maximize2 className="w-5 h-5" />}
          </Button>
          <div className="h-px bg-muted mx-2 my-0.5" />

          <Popover open={exportOpen} onOpenChange={onExportOpenChange}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn('rounded-lg', exportOpen && 'bg-primary/10 text-primary ring-1 ring-primary/20')}
                title="导出 PNG/SVG"
                aria-label="导出图谱"
              >
                <Download className="w-5 h-5" />
              </Button>
            </PopoverTrigger>
            <PopoverContent side="left" align="end" className="w-64 p-2">
              <div className="px-1.5 py-1 text-[11px] font-semibold text-muted-foreground uppercase">Export</div>
              <div className="grid grid-cols-2 gap-2 p-1">
                <Button type="button" size="sm" variant="outline" className="h-8" onClick={onExportPngDownload}>
                  PNG
                </Button>
                <Button type="button" size="sm" variant="outline" className="h-8" onClick={onExportSvgDownload}>
                  SVG
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-2 p-1">
                <Button type="button" size="sm" variant="ghost" className="h-8 justify-start" onClick={onExportPngCopy}>
                  <Copy className="w-4 h-4 mr-2" />
                  Copy PNG
                </Button>
                <Button type="button" size="sm" variant="ghost" className="h-8 justify-start" onClick={onExportSvgCopy}>
                  <Copy className="w-4 h-4 mr-2" />
                  Copy SVG
                </Button>
              </div>
              <div className="px-2 pb-1 text-[11px] text-muted-foreground">当前视图：{viewMode === '3d' ? '3D' : '2D'}</div>
            </PopoverContent>
          </Popover>
        </div>
      </div>
    </div>
  )
}
