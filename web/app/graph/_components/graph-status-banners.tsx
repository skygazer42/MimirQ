'use client'

import type { ReactNode } from 'react'

import { Lightbulb, Route, X, Link as LinkIcon } from '@/components/icons'

import { IconButton } from '@/components/ui/icon-button'

type GraphStatusBannersProps = Readonly<{
  isPathMode: boolean
  hasPathStart: boolean
  hasPathEnd: boolean
  isConnectMode: boolean
  connectSourceLabel: string | null
  isExplainMode: boolean
  currentStepIndex: number
  explainStepCount: number
  onExitPathMode: () => void
  onExitConnectMode: () => void
  onExitExplainMode: () => void
}>

type GraphModeBannerProps = Readonly<{
  toneClassName: string
  dismissLabel: string
  onDismiss: () => void
  children: ReactNode
}>

function GraphModeBanner({ toneClassName, dismissLabel, onDismiss, children }: GraphModeBannerProps) {
  return (
    <div
      className={`flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5 animate-in fade-in duration-150 motion-reduce:animate-none ${toneClassName}`}
    >
      {children}
      <IconButton
        label={dismissLabel}
        onClick={onDismiss}
        className="ml-2 h-7 w-7 rounded-full hover:bg-current/10"
      >
        <X className="w-4 h-4" />
      </IconButton>
    </div>
  )
}

export function GraphStatusBanners({
  isPathMode,
  hasPathStart,
  hasPathEnd,
  isConnectMode,
  connectSourceLabel,
  isExplainMode,
  currentStepIndex,
  explainStepCount,
  onExitPathMode,
  onExitConnectMode,
  onExitExplainMode,
}: GraphStatusBannersProps) {
  const pathMessage = (() => {
    if (hasPathStart) {
      return hasPathEnd ? '路径分析完成' : '请点击选择【终点】'
    }
    return '请点击选择【起点】'
  })()

  return (
    <>
      {isPathMode ? (
        <GraphModeBanner
          toneClassName="bg-muted/35 text-foreground"
          dismissLabel="退出路径分析"
          onDismiss={onExitPathMode}
        >
          <Route className="w-4 h-4" />
          <span className="text-sm font-medium">{pathMessage}</span>
        </GraphModeBanner>
      ) : null}

      {isConnectMode ? (
        <GraphModeBanner
          toneClassName="bg-muted/35 text-foreground"
          dismissLabel="退出连接模式"
          onDismiss={onExitConnectMode}
        >
          <LinkIcon className="w-4 h-4" />
          <span className="text-sm font-medium">正在连接: {connectSourceLabel} ... 请点击目标节点</span>
        </GraphModeBanner>
      ) : null}

      {isExplainMode ? (
        <GraphModeBanner
          toneClassName="bg-muted/35 text-foreground"
          dismissLabel="退出推理演示"
          onDismiss={onExitExplainMode}
        >
          <Lightbulb className="w-4 h-4" />
          <span className="text-sm font-medium">
            推理路径演示中... ({currentStepIndex + 1}/{explainStepCount})
          </span>
        </GraphModeBanner>
      ) : null}
    </>
  )
}
