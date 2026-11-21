'use client'

import { cloneElement, useEffect, useRef, useState, type ReactElement } from 'react'

import { cn } from '@/lib/utils'

type SafeResponsiveChartProps = Readonly<{
  children: ReactElement<{ width?: number; height?: number }>
  className?: string
  minHeight?: number
}>

export function SafeResponsiveChart({ children, className, minHeight = 280 }: SafeResponsiveChartProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 })

  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const update = () => {
      const rect = root.getBoundingClientRect()
      const measuredHeight = Math.floor(rect.height)
      const nextSize = {
        width: Math.floor(rect.width),
        height: measuredHeight > 0 ? measuredHeight : minHeight,
      }
      setSize((current) =>
        current.width === nextSize.width && current.height === nextSize.height ? current : nextSize,
      )
    }

    const frameId = globalThis.window.requestAnimationFrame(update)
    const observer = new ResizeObserver(update)
    observer.observe(root)

    return () => {
      globalThis.window.cancelAnimationFrame(frameId)
      observer.disconnect()
    }
  }, [minHeight])

  return (
    <div ref={rootRef} className={cn('h-[280px] min-w-0', className)}>
      {size.width > 0 && size.height > 0 ? cloneElement(children, size) : null}
    </div>
  )
}
