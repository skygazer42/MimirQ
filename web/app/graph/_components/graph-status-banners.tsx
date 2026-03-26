'use client'

import type { ReactNode } from 'react'

import { Lightbulb, Route, X, Link as LinkIcon } from 'lucide-react'

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
      className={`pointer-events-auto absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-full px-4 py-2 shadow-lg animate-in fade-in slide-in-from-top-4 motion-reduce:animate-none ${toneClassName}`}
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
          toneClassName="bg-primary text-primary-foreground"
          dismissLabel="退出路径分析"
          onDismiss={onExitPathMode}
        >
          <Route className="w-4 h-4" />
          <span className="text-sm font-medium">{pathMessage}</span>
        </GraphModeBanner>
      ) : null}

      {isConnectMode ? (
        <GraphModeBanner
          toneClassName="bg-success text-success-foreground"
          dismissLabel="退出连接模式"
          onDismiss={onExitConnectMode}
        >
          <LinkIcon className="w-4 h-4" />
          <span className="text-sm font-medium">正在连接: {connectSourceLabel} ... 请点击目标节点</span>
        </GraphModeBanner>
      ) : null}

      {isExplainMode ? (
        <GraphModeBanner
          toneClassName="bg-info text-info-foreground"
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
