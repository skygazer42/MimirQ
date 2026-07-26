'use client'

import { useEffect, useRef } from 'react'
import type { EChartsOption } from 'echarts'

import { cn } from '@/lib/utils'

export type EChartEventHandler = (params: unknown) => void

export function EChart({
  option,
  className,
  onEvents,
}: Readonly<{
  option: EChartsOption
  className?: string
  /**
   * ECharts event handlers keyed by event name (e.g. `click`).
   * Pass a stable (memoized) object: the chart re-initializes when it changes.
   */
  onEvents?: Readonly<Record<string, EChartEventHandler>>
}>) {
  const hostRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let disposed = false
    let cleanup = () => {}

    void import('echarts').then((echarts) => {
      if (disposed || !hostRef.current) return

      const chart = echarts.getInstanceByDom(hostRef.current) ?? echarts.init(hostRef.current, undefined, { renderer: 'svg' })
      chart.setOption(option, true)

      for (const [eventName, handler] of Object.entries(onEvents ?? {})) {
        chart.off(eventName)
        chart.on(eventName, handler)
      }

      const observer = typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => {
            chart.resize()
          })

      observer?.observe(hostRef.current)

      cleanup = () => {
        observer?.disconnect()
        chart.dispose()
      }
    })

    return () => {
      disposed = true
      cleanup()
    }
  }, [option, onEvents])

  return <div ref={hostRef} className={cn('h-full w-full min-w-0', className)} />
}
