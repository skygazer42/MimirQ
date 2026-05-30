'use client'

import {
  cloneElement,
  isValidElement,
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react'

import { cn } from '@/lib/utils'

type SafeResponsiveChartProps = Readonly<{
  children: ReactNode
  className?: string
  minHeight?: number
}>

export function SafeResponsiveChart({
  children,
  className,
  minHeight = 280,
}: SafeResponsiveChartProps) {
  const frameRef = useRef<number | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 })

  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const update = () => {
      const rect = root.getBoundingClientRect()
      setSize({
        width: Math.floor(rect.width),
        height: Math.floor(rect.height || minHeight),
      })
    }

    frameRef.current = globalThis.window.requestAnimationFrame(update)
    const observer = new ResizeObserver(update)
    observer.observe(root)

    return () => {
      if (frameRef.current !== null) {
        globalThis.window.cancelAnimationFrame(frameRef.current)
      }
      observer.disconnect()
    }
  }, [minHeight])

  const chart = isValidElement(children)
    ? cloneElement(children as ReactElement<{ width?: number; height?: number }>, {
        width: size.width,
        height: size.height || minHeight,
      })
    : null

  return (
    <div ref={rootRef} className={cn('h-[280px] min-w-0', className)}>
      {size.width > 0 && (size.height > 0 || minHeight > 0) ? chart : null}
    </div>
  )
}
