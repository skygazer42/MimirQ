'use client'

import { useEffect, useRef } from 'react'
import type { EChartsOption } from 'echarts'

import { cn } from '@/lib/utils'

export function EChart({
  option,
  className,
}: Readonly<{
  option: EChartsOption
  className?: string
}>) {
  const hostRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let disposed = false
    let cleanup = () => {}

    void import('echarts').then((echarts) => {
      if (disposed || !hostRef.current) return

      const chart = echarts.getInstanceByDom(hostRef.current) ?? echarts.init(hostRef.current, undefined, { renderer: 'svg' })
      chart.setOption(option, true)

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
  }, [option])

  return <div ref={hostRef} className={cn('h-full w-full min-w-0', className)} />
}
