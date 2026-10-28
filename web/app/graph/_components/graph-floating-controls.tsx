'use client'

import { Box, Copy, Download, Layout, Maximize, Maximize2, Minimize2, MoreHorizontal, PlayCircle, Route, Type, ZoomIn, ZoomOut } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import styles from './graph-workspace.module.css'

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
  viewMode, isExplainMode, isPathMode, showEdgeLabels, isFullscreen, exportOpen, layoutLabel,
  onZoomIn, onZoomOut, onZoomToFit, onToggleViewMode, onStartExplainMode, onCycleLayoutMode,
  onTogglePathMode, onToggleShowEdgeLabels, onToggleFullscreen, onExportOpenChange,
  onExportPngDownload, onExportSvgDownload, onExportPngCopy, onExportSvgCopy,
}: GraphFloatingControlsProps) {
  return <div className={styles.controls} aria-label="图谱画布工具">
    <Button variant="ghost" size="icon" onClick={onZoomOut} aria-label="缩小"><ZoomOut /></Button>
    <Button variant="ghost" size="icon" onClick={onZoomIn} aria-label="放大"><ZoomIn /></Button>
    <Button variant="ghost" size="icon" onClick={onZoomToFit} aria-label="适应屏幕"><Maximize /></Button>
    <Popover><PopoverTrigger asChild><Button variant="ghost" size="icon" aria-label="更多画布工具"><MoreHorizontal /></Button></PopoverTrigger>
      <PopoverContent side="top" align="start" className={styles.toolsMenu}>
        <button type="button" onClick={onToggleViewMode}><Box />{viewMode === '3d' ? '切换至 2D 平面' : '切换至 3D 空间'}</button>
        <button type="button" onClick={onCycleLayoutMode}><Layout />切换布局：{layoutLabel}</button>
        <button type="button" onClick={onToggleShowEdgeLabels} aria-pressed={showEdgeLabels}><Type />{showEdgeLabels ? '隐藏连线标签' : '显示连线标签'}</button>
        <button type="button" onClick={onTogglePathMode} aria-pressed={isPathMode}><Route />{isPathMode ? '退出路径发现' : '路径发现'}</button>
        <button type="button" onClick={onStartExplainMode} aria-pressed={isExplainMode}><PlayCircle />推理演示</button>
        <button type="button" onClick={onToggleFullscreen}>{isFullscreen ? <Minimize2 /> : <Maximize2 />}{isFullscreen ? '退出全屏模式' : '进入全屏模式'}</button>
      </PopoverContent>
    </Popover>
    <Popover open={exportOpen} onOpenChange={onExportOpenChange}><PopoverTrigger asChild><Button variant="ghost" size="icon" aria-label="导出图谱图片"><Download /></Button></PopoverTrigger>
      <PopoverContent side="top" align="start" className={styles.toolsMenu}>
        <button type="button" onClick={onExportPngDownload}><Download />下载 PNG</button><button type="button" onClick={onExportSvgDownload}><Download />下载 SVG</button>
        <button type="button" onClick={onExportPngCopy}><Copy />复制 PNG</button><button type="button" onClick={onExportSvgCopy}><Copy />复制 SVG</button>
      </PopoverContent>
    </Popover>
  </div>
}
