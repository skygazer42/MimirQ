'use client'

import { useEffect, useRef, useState } from 'react'
import type { EChartsOption, EChartsType } from 'echarts'

import { Button } from '@/components/ui/button'
import { reportClientError } from '@/lib/client-logging'
import { cn } from '@/lib/utils'

export type EChartEventHandler = (params: unknown) => void

type EChartProps = {
  option: EChartsOption
  className?: string
  onEvents?: Readonly<Record<string, EChartEventHandler>>
}

export function EChart({ option, className, onEvents }: Readonly<EChartProps>) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [chart, setChart] = useState<EChartsType | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    const host = hostRef.current
    if (host === null) return

    let disposed = false
    let cleanup: (() => void) | undefined

    void import('echarts')
      .then((echarts) => {
        if (disposed) return

        const instance = echarts.init(host, undefined, { renderer: 'svg' })
        let observer: ResizeObserver | undefined
        cleanup = () => {
          observer?.disconnect()
          instance.dispose()
        }

        if (typeof ResizeObserver !== 'undefined') {
          observer = new ResizeObserver(() => instance.resize())
          observer.observe(host)
        }
        setChart(instance)
      })
      .catch((error: unknown) => {
        if (disposed) return
        cleanup?.()
        cleanup = undefined
        setLoadFailed(true)
        reportClientError('图表初始化失败', error)
      })

    return () => {
      disposed = true
      cleanup?.()
    }
  }, [loadAttempt])

  useEffect(() => {
    if (chart === null || chart.isDisposed()) return
    chart.setOption(option, true)
  }, [chart, option])

  useEffect(() => {
    if (chart === null || chart.isDisposed() || onEvents === undefined) return
    const handlers = Object.entries(onEvents)
    for (const [eventName, handler] of handlers) {
      chart.on(eventName, handler)
    }

    return () => {
      if (chart.isDisposed()) return
      for (const [eventName, handler] of handlers) {
        chart.off(eventName, handler)
      }
    }
  }, [chart, onEvents])

  return (
    <>
      <div ref={hostRef} className={cn('h-full w-full min-w-0', className, loadFailed && 'hidden')} />
      {loadFailed && (
        <div role="alert" className={cn('flex h-full items-center justify-center gap-3', className)}>
          <span>图表加载失败</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setLoadFailed(false)
              setLoadAttempt((previous) => previous + 1)
            }}
          >
            重新加载
          </Button>
        </div>
      )}
    </>
  )
}
